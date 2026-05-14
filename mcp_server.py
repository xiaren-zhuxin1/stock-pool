import asyncio
import json
import sys
import os
import time
import builtins
import sqlite3
import threading
import requests
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Callable
from contextlib import contextmanager
from functools import wraps
from collections import OrderedDict

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError):
        pass

script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)
sys.path.insert(0, parent_dir)

from provider_manager import ProviderManager
from mcp_tools import TOOLS
from errors import (
    create_success_response, create_error_response, handle_error,
    ValidationError, DataNotFoundError, ProviderError, Logger,
)
from storage import (
    init_database_schema,
    save_stock_info as storage_save_stock_info,
    save_daily_data as storage_save_daily_data,
    save_valuation_data as storage_save_valuation_data,
    save_technical_data as storage_save_technical_data,
    save_fund_flow_data as storage_save_fund_flow_data,
    get_stock_info as storage_get_stock_info,
    get_daily_data as storage_get_daily_data,
    get_valuation_data as storage_get_valuation_data,
    get_technical_data as storage_get_technical_data,
    get_fund_flow_data as storage_get_fund_flow_data,
    get_daily_data_for_technical,
    check_data_freshness as storage_check_data_freshness,
)
from minute_data import (
    save_minute_data as minute_save_minute_data,
    get_minute_data as minute_get_minute_data,
    minute_fetch_days_for_range,
    minute_kline_range,
)
from indicators import calculate_ma, calculate_technical_indicators, ema, rsi, calculate_returns, calculate_volume_analysis, generate_technical_signals, calculate_support_resistance
from sync_jobs import json_dumps, json_loads


def _log(*args, **kwargs):
    kwargs.setdefault('file', sys.stderr)
    return builtins.print(*args, **kwargs)


class LRUCache:
    def __init__(self, max_size: int = 100, ttl: int = 300):
        self.max_size = max_size
        self.ttl = ttl
        self.cache: OrderedDict = OrderedDict()
        self.lock = threading.Lock()
    
    def get(self, key: str) -> Optional[Any]:
        with self.lock:
            if key not in self.cache:
                return None
            value, timestamp = self.cache[key]
            if time.time() - timestamp > self.ttl:
                del self.cache[key]
                return None
            self.cache.move_to_end(key)
            return value
    
    def set(self, key: str, value: Any) -> None:
        with self.lock:
            if key in self.cache:
                del self.cache[key]
            elif len(self.cache) >= self.max_size:
                self.cache.popitem(last=False)
            self.cache[key] = (value, time.time())
    
    def clear(self) -> None:
        with self.lock:
            self.cache.clear()


def cached(cache_instance: LRUCache, key_func: Callable):
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = key_func(*args, **kwargs)
            cached_result = cache_instance.get(cache_key)
            if cached_result is not None:
                return cached_result
            result = func(*args, **kwargs)
            cache_instance.set(cache_key, result)
            return result
        return wrapper
    return decorator


def performance_monitor(func: Callable) -> Callable:
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            elapsed = time.time() - start_time
            if elapsed > 1.0:
                logger.warning(f"性能警告: {func.__name__} 执行耗时 {elapsed:.2f}秒")
            return result
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"执行失败: {func.__name__} 耗时 {elapsed:.2f}秒, 错误: {e}")
            raise
    return wrapper


_SANITIZE_DROP = object()
_SANITIZE_KEY_MAP = {
    'cache_used': _SANITIZE_DROP,
    'no_cached_snapshot': _SANITIZE_DROP,
    'refresh_attempted': _SANITIZE_DROP,
    'refresh_result': _SANITIZE_DROP,
    'skipped': _SANITIZE_DROP,
    'snapshot_count': _SANITIZE_DROP,
    'universe_returned': _SANITIZE_DROP,
    'universe_total': _SANITIZE_DROP,
    'criteria': _SANITIZE_DROP,
    'realtime_used': _SANITIZE_DROP,
    'realtime_error': _SANITIZE_DROP,
    'realtime_api': _SANITIZE_DROP,
    'realtime_fetched_at': _SANITIZE_DROP,
    'effective_price_source': _SANITIZE_DROP,
    'missing_fields': _SANITIZE_DROP,
    'data_quality': _SANITIZE_DROP,
    'data_source': _SANITIZE_DROP,
    'realtime_skipped': _SANITIZE_DROP,
    'time_context': _SANITIZE_DROP,
    'kline_updated': _SANITIZE_DROP,
    'valuation_updated': _SANITIZE_DROP,
    'metadata': _SANITIZE_DROP,
    'provider': _SANITIZE_DROP,
    'fallback_used': _SANITIZE_DROP,
    'fallback_chain': _SANITIZE_DROP,
    'created_at': _SANITIZE_DROP,
    'updated_at': _SANITIZE_DROP,
    'finished_at': _SANITIZE_DROP,
}
_SANITIZE_VALUE_MAP = {
    'cache': 'historical_close',
}


def _sanitize_for_agent(value):
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            public_key = _SANITIZE_KEY_MAP.get(key, key)
            if public_key is _SANITIZE_DROP:
                continue
            sanitized[public_key] = _sanitize_for_agent(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_for_agent(item) for item in value]
    if isinstance(value, str):
        return _SANITIZE_VALUE_MAP.get(value, value)
    return value


DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'stock_pool.db')
SHANGHAI_TZ = timezone(timedelta(hours=8), name='Asia/Shanghai')
logger = Logger()

_time_cache = LRUCache(max_size=10, ttl=60)
_stock_info_cache = LRUCache(max_size=1000, ttl=300)
_valuation_cache = LRUCache(max_size=500, ttl=300)


class StockPoolServer:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.db_path = self.config.get('db_path', DB_PATH)
        self._sqlite_uri = False
        self._memory_keeper = None

        if self.db_path == ':memory:':
            self.db_path = f"file:stock_pool_memory_{id(self)}?mode=memory&cache=shared"
            self._sqlite_uri = True
            self._memory_keeper = sqlite3.connect(self.db_path, uri=True)

        self._init_db()
        self.provider_manager = ProviderManager(self.config.get('providers', {}))
        self._screener_cache = {}
        self._screener_cache_time = {}
        logger.info("StockPoolServer 初始化完成")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, uri=self._sqlite_uri)

    @contextmanager
    def _get_connection(self):
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        conn = self._connect()
        init_database_schema(conn)
        conn.close()

    @staticmethod
    @cached(_time_cache, lambda now=None: f"time_info:{now.isoformat() if now else 'current'}")
    def get_current_time_info(now: Optional[datetime] = None) -> Dict[str, Any]:
        if now is None:
            now = datetime.now(SHANGHAI_TZ)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=SHANGHAI_TZ)
        else:
            now = now.astimezone(SHANGHAI_TZ)

        minutes = now.hour * 60 + now.minute
        is_trading_day = now.weekday() < 5
        is_trading_time = is_trading_day and (
            (9 * 60 + 30 <= minutes <= 11 * 60 + 30) or
            (13 * 60 <= minutes <= 15 * 60)
        )

        if not is_trading_day:
            trading_session = 'non_trading_day'
        elif minutes < 9 * 60 + 30:
            trading_session = 'pre_market'
        elif 9 * 60 + 30 <= minutes <= 11 * 60 + 30:
            trading_session = 'morning_trading'
        elif minutes < 13 * 60:
            trading_session = 'lunch_break'
        elif 13 * 60 <= minutes <= 15 * 60:
            trading_session = 'afternoon_trading'
        else:
            trading_session = 'after_market'

        return {
            'timezone': 'Asia/Shanghai',
            'utc_offset': '+08:00',
            'datetime': now.isoformat(timespec='seconds'),
            'date': now.date().isoformat(),
            'time': now.time().isoformat(timespec='seconds'),
            'timestamp': int(now.timestamp()),
            'is_trading_day': is_trading_day,
            'is_trading_time': is_trading_time,
            'trading_session': trading_session,
        }

    def _request_includes_today(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> bool:
        today = self.get_current_time_info()['date']
        if start_date and start_date > today:
            return False
        if end_date and end_date < today:
            return False
        return True

    def _merge_realtime_snapshot(self, item: Dict[str, Any], realtime: Optional[Dict[str, Any]], time_info: Dict[str, Any]) -> Dict[str, Any]:
        if not realtime or not realtime.get('success'):
            item.update({
                'realtime_used': False,
                'realtime_error': realtime.get('message') if realtime else '实时行情 API 未返回数据',
                'time_context': time_info,
            })
            return item

        realtime_price = realtime.get('price')
        item.update({
            'realtime_used': True,
            'realtime_price': realtime_price,
            'effective_close': realtime_price if realtime_price is not None else item.get('close'),
            'effective_price_source': 'realtime' if realtime_price is not None else 'cache',
            'realtime_api': realtime.get('api_name') or realtime.get('data_source'),
            'realtime_fetched_at': realtime.get('fetched_at'),
            'time_context': time_info,
        })

        for key in ['pe_ttm', 'pe_lyr', 'pb', 'market_cap', 'circ_market_cap', 'data_quality', 'missing_fields']:
            if realtime.get(key) is not None:
                item[key] = realtime.get(key)

        if realtime.get('name') and not item.get('name'):
            item['name'] = realtime.get('name')
        return item

    @staticmethod
    def _normalize_limit(limit: Optional[int]) -> Optional[int]:
        if limit is None:
            return None
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise ValidationError('limit 必须是正整数', field='limit', value=limit)
        if limit <= 0 or limit > 10000:
            raise ValidationError('limit 必须在 1 到 10000 之间', field='limit', value=limit)
        return limit

    @staticmethod
    def _normalize_offset(offset: Optional[int]) -> int:
        if offset is None:
            return 0
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            raise ValidationError('offset 必须是非负整数', field='offset', value=offset)
        if offset < 0 or offset > 1000000:
            raise ValidationError('offset 必须在 0 到 1000000 之间', field='offset', value=offset)
        return offset

    @staticmethod
    def _normalize_positive_int(value: Optional[int], default: int, maximum: int) -> int:
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = default
        return max(0, min(value, maximum))

    @staticmethod
    def _to_number(value: Any) -> Optional[float]:
        if value is None or value == '':
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _passes_range(value: Optional[float], min_value: Optional[float] = None, 
                      max_value: Optional[float] = None) -> bool:
        if min_value is None and max_value is None:
            return True
        if value is None:
            return False
        if min_value is not None and value < min_value:
            return False
        if max_value is not None and value > max_value:
            return False
        return True

    @staticmethod
    def _unique_codes(codes):
        seen = set()
        result = []
        for code in codes or []:
            code = str(code).strip()
            if not code or code in seen:
                continue
            seen.add(code)
            result.append(code)
        return result

    @staticmethod
    def _chunked(items, size):
        size = max(1, int(size or 1))
        for i in range(0, len(items), size):
            yield items[i:i + size]

    def check_data_freshness(self, code, data_type='daily', klt=None):
        with self._get_connection() as conn:
            return storage_check_data_freshness(conn, code, data_type, klt)

    def _should_auto_refresh(self, code, data_type='daily'):
        freshness = self.check_data_freshness(code, data_type)
        if not freshness.get('has_data'):
            return True
        if freshness.get('is_today'):
            return False
        try:
            latest = datetime.strptime(freshness['latest_date'], '%Y-%m-%d').date()
            gap = (datetime.now().date() - latest).days
            return gap > 3
        except (KeyError, TypeError, ValueError):
            return True

    @staticmethod
    def _calculate_daily_fetch_days(freshness, requested_days=250, force=False, today=None):
        try:
            requested_days = int(requested_days)
        except (TypeError, ValueError):
            requested_days = 250
        requested_days = max(1, requested_days)

        if force or not freshness.get('has_data'):
            return requested_days

        row_count = freshness.get('row_count') or 0
        if row_count < requested_days:
            return requested_days

        if freshness.get('is_today'):
            return 0

        today = today or datetime.now().strftime('%Y-%m-%d')
        try:
            latest = datetime.strptime(freshness['latest_date'], '%Y-%m-%d').date()
            current = datetime.strptime(today, '%Y-%m-%d').date()
        except (KeyError, TypeError, ValueError):
            return min(requested_days, 30)

        gap_days = (current - latest).days
        if gap_days <= 0:
            return 0

        return min(requested_days, max(5, gap_days * 2 + 5))

    def _fetch_and_save_realtime(self, code: str) -> Dict[str, Any]:
        result = self.provider_manager.fetch_realtime(code)
        if not result.success:
            return {'success': False, 'code': code, 'message': result.error.message}

        realtime = dict(result.data)
        realtime.update({
            'success': True,
            'code': code,
            'api_name': result.provider_name,
            'cache_used': False,
            'fetched_at': self.get_current_time_info()['datetime'],
        })
        return realtime

    def _fetch_and_save_kline(self, code: str, days: int = 250, force: bool = False) -> Optional[List[str]]:
        freshness = self.check_data_freshness(code, 'daily')
        fetch_days = self._calculate_daily_fetch_days(freshness, days, force)
        if fetch_days == 0:
            _log(f"  数据已是最新（{freshness['latest_date']}），跳过更新")
            return None

        result = self.provider_manager.fetch_daily_kline(code, fetch_days)
        if not result.success:
            _log(f"  K线获取失败: {result.error.message}")
            return None

        klines = result.data
        if klines:
            with self._get_connection() as conn:
                storage_save_daily_data(conn, code, klines)
            _log(f"  日K线: {len(klines)} 条 [来源: {result.provider_name}]")
        return klines

    def _fetch_and_save_valuation(self, code: str) -> Optional[Dict[str, Any]]:
        result = self.provider_manager.fetch_valuation(code)
        if not result.success:
            return None

        valuation = result.data
        if valuation:
            valuation['name'] = valuation.get('name', '')
            valuation['market'] = 'SH' if code.startswith('6') else 'SZ'
            with self._get_connection() as conn:
                storage_save_stock_info(conn, code, valuation)
                storage_save_valuation_data(conn, code, valuation)
            _log(f"  估值: PE={valuation.get('pe_ttm', 'N/A')} [来源: {result.provider_name}]")
        return valuation

    def _calculate_and_save_technical(self, code: str) -> None:
        with self._get_connection() as conn:
            rows = get_daily_data_for_technical(conn, code)
            if not rows:
                return
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            technical_items = calculate_technical_indicators(rows, now)
            storage_save_technical_data(conn, code, technical_items)
        _log(f"  技术指标: 计算完成")

    def _fetch_and_save_fund_flow(self, code: str, days: int = 100) -> Optional[List]:
        result = self.provider_manager.fetch_fund_flow(code, days)
        if not result.success:
            return None
        fund_flow_items = result.data
        if not fund_flow_items:
            return None
        with self._get_connection() as conn:
            saved = storage_save_fund_flow_data(conn, code, fund_flow_items)
        _log(f"  资金流向: {saved} 条")
        return fund_flow_items

    def _fetch_and_save_minute_data(self, code: str, klt: int = 5, days: int = 5, force: bool = False,
                                     start_time: Optional[str] = None, end_time: Optional[str] = None) -> Dict[str, Any]:
        _log(f"更新 {code} {klt}分钟K线...")

        requested_range = None
        if start_time or end_time:
            requested_range = {'start_time': start_time, 'end_time': end_time}
            days = max(days, minute_fetch_days_for_range(start_time, end_time, days))

        if not force and not requested_range:
            freshness = self.check_data_freshness(code, 'minute', klt=klt)
            if freshness['has_data']:
                latest_time_str = freshness['latest_time']
                today = self.get_current_time_info()['date']
                if latest_time_str.startswith(today):
                    now = datetime.now(SHANGHAI_TZ).replace(tzinfo=None)
                    latest_time = datetime.strptime(latest_time_str, '%Y-%m-%d %H:%M')
                    minutes_diff = (now - latest_time).total_seconds() / 60
                    is_trading_time = self.get_current_time_info()['is_trading_time']
                    if not is_trading_time or minutes_diff < klt:
                        return {'success': True, 'updated': False, 'reason': 'local_data_fresh', 'latest_time': latest_time_str}

        result = self.provider_manager.fetch_minute_kline(code, klt, days)
        fetched_start, fetched_end = minute_kline_range(result.data) if result.success else (None, None)

        count = 0
        if result.success and result.data:
            with self._get_connection() as conn:
                count = minute_save_minute_data(conn, code, result.data, klt)
            _log(f"  保存: {count} 条 [来源: {result.provider_name}]")

        target_count = None
        target_covered = None
        resolution = None
        if requested_range:
            with self._get_connection() as conn:
                target_count = len(minute_get_minute_data(conn, code, klt, start_time, end_time))
            target_covered = target_count > 0
            if not target_covered:
                action_required = 'retry_later_or_use_daily_data'
                reason = '外部分时接口更新后仍未返回请求区间数据'
                if fetched_start and end_time and end_time < fetched_start:
                    action_required = 'unavailable_from_provider'
                    reason = f'外部分时接口当前最早只返回到 {fetched_start}'
                elif fetched_end and start_time and start_time > fetched_end:
                    action_required = 'wait'
                    reason = f'外部分时接口当前最新只返回到 {fetched_end}'
                resolution = {
                    'action_required': action_required,
                    'reason': reason,
                    'retry_call': {
                        'tool': 'get_minute_data',
                        'arguments': {'code': code, 'klt': klt, 'start_time': start_time, 'end_time': end_time},
                    } if action_required != 'unavailable_from_provider' else None,
                    'do_not_retry_update': action_required == 'unavailable_from_provider',
                }

        return {
            'success': bool(result.success and result.data) and (target_covered is not False),
            'updated': bool(result.success and result.data),
            'code': code,
            'klt': klt,
            'days': days,
            'saved_count': count,
            'fetched_range': {'start_time': fetched_start, 'end_time': fetched_end},
            'requested_range': requested_range,
            'target_count': target_count,
            'target_covered': target_covered,
            'resolution': resolution,
        }

    @performance_monitor
    def update_stock(self, code: str, days: int = 250, delay: float = 1.5, force: bool = False) -> Dict[str, Any]:
        _log(f"更新 {code}...")

        klines = self._fetch_and_save_kline(code, days, force)
        valuation = self._fetch_and_save_valuation(code)

        if klines:
            self._calculate_and_save_technical(code)

        if delay:
            time.sleep(delay)

        return {
            'success': True,
            'code': code,
            'kline_updated': klines is not None,
            'valuation_updated': valuation is not None,
        }

    def get_realtime_price(self, code: str) -> Dict[str, Any]:
        return self._fetch_and_save_realtime(code)

    def get_realtime_prices(self, codes: List[str], delay: float = 0.2) -> List[Dict[str, Any]]:
        results = []
        for code in codes:
            results.append(self.get_realtime_price(code))
            if delay:
                time.sleep(delay)
        return results

    def get_stock_info(self, code: str, auto_refresh: bool = False) -> Optional[Dict]:
        with self._get_connection() as conn:
            data = storage_get_stock_info(conn, code)

        if auto_refresh and not data:
            try:
                self.update_stock(code, days=250, delay=0, force=True)
                with self._get_connection() as conn:
                    data = storage_get_stock_info(conn, code)
            except (ValidationError, ProviderError) as e:
                logger.warning(f"自动刷新股票信息失败 {code}: {e.message}", code=code)
            except (ConnectionError, TimeoutError) as e:
                logger.warning(f"网络错误，使用缓存数据 {code}: {e}", code=code)
            except Exception as e:
                logger.error(f"未预期的错误 {code}: {e}", exc_info=True, code=code)

        return data

    def get_daily_data(self, code, start_date=None, end_date=None, limit=None, offset=0, include_realtime=True, auto_refresh=True):
        limit = self._normalize_limit(limit)
        offset = self._normalize_offset(offset)
        with self._get_connection() as conn:
            data = storage_get_daily_data(conn, code, start_date, end_date, limit, offset)

        if auto_refresh and offset == 0 and (not data or self._should_auto_refresh(code, 'daily')):
            try:
                self.update_stock(code, days=250, delay=0, force=not data)
                with self._get_connection() as conn:
                    data = storage_get_daily_data(conn, code, start_date, end_date, limit, offset)
            except (ValidationError, ProviderError) as e:
                logger.warning(f"自动刷新日K数据失败 {code}: {e.message}", code=code)
            except (ConnectionError, TimeoutError) as e:
                logger.warning(f"网络错误，使用缓存数据 {code}: {e}", code=code)
            except Exception as e:
                logger.error(f"未预期的错误 {code}: {e}", exc_info=True, code=code)

        if offset == 0 and include_realtime and self._request_includes_today(start_date, end_date):
            time_info = self.get_current_time_info()
            realtime = self.get_realtime_price(code)
            if data:
                data[0] = self._merge_realtime_snapshot(data[0], realtime, time_info)
            else:
                data.append(self._merge_realtime_snapshot({
                    'code': code, 'date': time_info['date'],
                    'open': None, 'high': None, 'low': None, 'close': None,
                    'volume': None, 'amount': None,
                }, realtime, time_info))
        return data

    def get_valuation_data(self, code, start_date=None, end_date=None, limit=None, offset=0, auto_refresh=True):
        limit = self._normalize_limit(limit)
        offset = self._normalize_offset(offset)
        with self._get_connection() as conn:
            data = storage_get_valuation_data(conn, code, start_date, end_date, limit, offset)

        if auto_refresh and offset == 0 and (not data or self._should_auto_refresh(code, 'daily')):
            try:
                self.update_stock(code, days=250, delay=0, force=not data)
                with self._get_connection() as conn:
                    data = storage_get_valuation_data(conn, code, start_date, end_date, limit, offset)
            except (ValidationError, ProviderError) as e:
                logger.warning(f"自动刷新估值数据失败 {code}: {e.message}", code=code)
            except (ConnectionError, TimeoutError) as e:
                logger.warning(f"网络错误，使用缓存数据 {code}: {e}", code=code)
            except Exception as e:
                logger.error(f"未预期的错误 {code}: {e}", exc_info=True, code=code)

        return data

    def get_technical_data(self, code, start_date=None, end_date=None, limit=None, offset=0, auto_refresh=True):
        limit = self._normalize_limit(limit)
        offset = self._normalize_offset(offset)
        with self._get_connection() as conn:
            data = storage_get_technical_data(conn, code, start_date, end_date, limit, offset)

        if auto_refresh and offset == 0 and (not data or self._should_auto_refresh(code, 'daily')):
            try:
                self.update_stock(code, days=250, delay=0, force=not data)
                with self._get_connection() as conn:
                    data = storage_get_technical_data(conn, code, start_date, end_date, limit, offset)
            except (ValidationError, ProviderError) as e:
                logger.warning(f"自动刷新技术指标失败 {code}: {e.message}", code=code)
            except (ConnectionError, TimeoutError) as e:
                logger.warning(f"网络错误，使用缓存数据 {code}: {e}", code=code)
            except Exception as e:
                logger.error(f"未预期的错误 {code}: {e}", exc_info=True, code=code)

        return data

    def get_fund_flow(self, code, start_date=None, end_date=None, limit=None, offset=0, auto_refresh=True):
        limit = self._normalize_limit(limit)
        offset = self._normalize_offset(offset)
        with self._get_connection() as conn:
            data = storage_get_fund_flow_data(conn, code, start_date, end_date, limit, offset)

        if auto_refresh and offset == 0 and (not data or self._should_auto_refresh(code, 'fund_flow')):
            try:
                self._fetch_and_save_fund_flow(code, 100)
                with self._get_connection() as conn:
                    data = storage_get_fund_flow_data(conn, code, start_date, end_date, limit, offset)
            except (ValidationError, ProviderError) as e:
                logger.warning(f"自动刷新资金流向失败 {code}: {e.message}", code=code)
            except (ConnectionError, TimeoutError) as e:
                logger.warning(f"网络错误，使用缓存数据 {code}: {e}", code=code)
            except Exception as e:
                logger.error(f"未预期的错误 {code}: {e}", exc_info=True, code=code)

        return data

    def get_minute_data(self, code, klt=5, start_time=None, end_time=None, limit=None, offset=0, auto_refresh=True):
        with self._get_connection() as conn:
            data = minute_get_minute_data(conn, code, klt, start_time, end_time, limit, offset,
                                          self._normalize_limit, self._normalize_offset)

        if auto_refresh and not data:
            time_context = self.get_current_time_info()
            is_trading_time = time_context.get('is_trading_time', False)
            is_trading_day = time_context.get('is_trading_day', False)

            if is_trading_day and is_trading_time:
                try:
                    days = minute_fetch_days_for_range(start_time, end_time, 2)
                    self._fetch_and_save_minute_data(code, klt=klt, days=days, force=True, start_time=start_time, end_time=end_time)
                    with self._get_connection() as conn:
                        data = minute_get_minute_data(conn, code, klt, start_time, end_time, limit, offset,
                                                      self._normalize_limit, self._normalize_offset)
                except Exception:
                    pass

        return data

    def get_latest_data(self, codes, include_realtime=True, realtime_limit=None, batch_size=200):
        codes = self._unique_codes(codes)
        if not codes:
            return []

        try:
            batch_size = max(1, min(int(batch_size), 500))
        except (TypeError, ValueError):
            batch_size = 200

        if realtime_limit is not None:
            try:
                realtime_limit = max(0, int(realtime_limit))
            except (TypeError, ValueError):
                realtime_limit = None

        with self._get_connection() as conn:
            cursor = conn.cursor()
            results = []
            for chunk in self._chunked(codes, batch_size):
                placeholders = ','.join('?' for _ in chunk)
                cursor.execute('''
                    WITH latest_daily AS (
                        SELECT d.*
                        FROM stock_daily d
                        JOIN (
                            SELECT code, MAX(data_date) AS data_date
                            FROM stock_daily
                            WHERE code IN ({placeholders})
                            GROUP BY code
                        ) latest ON d.code = latest.code AND d.data_date = latest.data_date
                    ),
                    latest_valuation AS (
                        SELECT v.*
                        FROM stock_valuation v
                        JOIN (
                            SELECT code, MAX(data_date) AS data_date
                            FROM stock_valuation
                            WHERE code IN ({placeholders})
                            GROUP BY code
                        ) latest ON v.code = latest.code AND v.data_date = latest.data_date
                    )
                    SELECT
                        i.code, i.name, i.market,
                        d.data_date, d.close,
                        t.position_pct, t.high_52w, t.low_52w,
                        v.pe_ttm, v.pb, v.market_cap, v.data_source, v.data_quality, v.missing_fields
                    FROM stock_info i
                    LEFT JOIN latest_daily d ON i.code = d.code
                    LEFT JOIN stock_technical t ON i.code = t.code AND d.data_date = t.data_date
                    LEFT JOIN latest_valuation v ON i.code = v.code
                    WHERE i.code IN ({placeholders})
                '''.format(placeholders=placeholders), chunk + chunk + chunk)

                rows_by_code = {row[0]: row for row in cursor.fetchall()}
                for code in chunk:
                    row = rows_by_code.get(code)
                    if not row:
                        continue
                    results.append({
                        'code': row[0], 'name': row[1], 'market': row[2],
                        'date': row[3], 'close': row[4],
                        'position_pct': row[5], 'high_52w': row[6], 'low_52w': row[7],
                        'pe_ttm': row[8], 'pb': row[9], 'market_cap': row[10],
                        'data_source': row[11], 'data_quality': row[12],
                        'missing_fields': json.loads(row[13]) if row[13] else [],
                    })

        if include_realtime:
            time_info = self.get_current_time_info()
            realtime_count = 0
            for item in results:
                if realtime_limit is not None and realtime_count >= realtime_limit:
                    item.update({'realtime_used': False, 'realtime_skipped': True, 'time_context': time_info})
                    continue
                realtime = self.get_realtime_price(item['code'])
                self._merge_realtime_snapshot(item, realtime, time_info)
                realtime_count += 1

        return results

    def analyze_position(self, codes):
        data = self.get_latest_data(codes, include_realtime=False)
        result = {'low': [], 'mid': [], 'mid_high': [], 'high': []}

        for row in data:
            position = row.get('position_pct')
            if position is None:
                continue
            item = {
                'code': row['code'], 'name': row['name'],
                'position_pct': position, 'close': row.get('close'),
                'high_52w': row.get('high_52w'), 'low_52w': row.get('low_52w'),
            }
            if position < 30:
                result['low'].append(item)
            elif position < 70:
                result['mid'].append(item)
            elif position < 90:
                result['mid_high'].append(item)
            else:
                result['high'].append(item)

        return result

    def analyze_main_force(self, code, days=10):
        fund_flow_data = self.get_fund_flow(code, limit=days)
        if not fund_flow_data:
            return {'code': code, 'success': False, 'error': '无资金流向数据'}

        main_inflows = [item['main_net_inflow'] for item in fund_flow_data if item.get('main_net_inflow')]
        main_inflow_pcts = [item['main_net_inflow_pct'] for item in fund_flow_data if item.get('main_net_inflow_pct')]

        if not main_inflows:
            return {'code': code, 'success': False, 'error': '无有效主力资金数据'}

        total_main_inflow = sum(main_inflows)
        avg_main_inflow = total_main_inflow / len(main_inflows)
        avg_main_inflow_pct = sum(main_inflow_pcts) / len(main_inflow_pcts) if main_inflow_pcts else 0

        positive_days = sum(1 for inflow in main_inflows if inflow > 0)
        negative_days = len(main_inflows) - positive_days

        consecutive_inflow = 0
        consecutive_outflow = 0
        current_streak = 0
        for inflow in main_inflows:
            if inflow > 0:
                current_streak = current_streak + 1 if current_streak > 0 else 1
                consecutive_inflow = max(consecutive_inflow, current_streak)
            else:
                current_streak = current_streak - 1 if current_streak < 0 else -1
                consecutive_outflow = max(consecutive_outflow, abs(current_streak))

        latest = fund_flow_data[0] if fund_flow_data else None

        return {
            'code': code, 'success': True, 'days': len(main_inflows),
            'total_main_inflow': total_main_inflow,
            'avg_main_inflow': avg_main_inflow,
            'avg_main_inflow_pct': avg_main_inflow_pct,
            'positive_days': positive_days, 'negative_days': negative_days,
            'consecutive_inflow': consecutive_inflow,
            'consecutive_outflow': consecutive_outflow,
            'latest_date': latest.get('data_date') if latest else None,
            'latest_main_inflow': latest.get('main_net_inflow') if latest else None,
            'latest_main_inflow_pct': latest.get('main_net_inflow_pct') if latest else None,
            'trend': 'inflow' if total_main_inflow > 0 else 'outflow',
            'strength': 'strong' if abs(avg_main_inflow_pct) > 5 else 'medium' if abs(avg_main_inflow_pct) > 2 else 'weak',
        }

    def analyze_intraday(self, code, date=None):
        time_context = self.get_current_time_info()
        if not date:
            date = time_context['date']

        is_trading_time = time_context.get('is_trading_time', False)
        is_trading_day = time_context.get('is_trading_day', False)
        current_date = time_context['date']
        requested_is_today = (date == current_date)

        data_5min = self.get_minute_data(code, klt=5, start_time=f'{date} 09:30', end_time=f'{date} 15:00')
        daily_data = self.get_daily_data(code, limit=2)
        technical_data = self.get_technical_data(code, start_date=date)

        if not data_5min:
            if requested_is_today and not is_trading_day:
                return {
                    'success': False,
                    'error': {
                        'code': 'NON_TRADING_DAY',
                        'message': f'{date} 不是交易日，无法获取分时数据',
                        'severity': 'info',
                        'recoverable': False,
                    },
                    'code': code,
                    'requested_date': date,
                    'is_trading_day': is_trading_day,
                }

            if requested_is_today and not is_trading_time:
                trading_session = time_context.get('trading_session', 'unknown')
                return {
                    'success': False,
                    'error': {
                        'code': 'OUTSIDE_TRADING_HOURS',
                        'message': f'当前非交易时间（{trading_session}），分钟数据可能不完整。请在交易时间重试。',
                        'severity': 'warning',
                        'recoverable': True,
                        'suggested_action': '请在交易时间（9:30-11:30, 13:00-15:00）重试',
                    },
                    'code': code,
                    'requested_date': date,
                    'is_trading_time': is_trading_time,
                    'trading_session': trading_session,
                }

            return {
                'success': False,
                'error': {
                    'code': 'DATA_NOT_FOUND',
                    'message': f'缺少分钟数据，无法进行日内分析。未获取到 {date} 的5分钟分时数据',
                    'severity': 'error',
                    'recoverable': True,
                    'suggested_action': '请在交易时间重试，系统会自动获取分钟数据',
                },
                'code': code,
                'requested_date': date,
                'current_date': current_date,
            }

        if not daily_data:
            return {
                'success': False,
                'error': {
                    'code': 'DAILY_DATA_MISSING',
                    'message': f'缺少日K数据，无法进行日内分析',
                    'severity': 'error',
                    'recoverable': True,
                },
                'code': code,
                'requested_date': date,
            }

        data_5min.reverse()
        morning_data = [d for d in data_5min if '09:' in d['data_time'] or '10:' in d['data_time'] or '11:' in d['data_time']]
        afternoon_data = [d for d in data_5min if '13:' in d['data_time'] or '14:' in d['data_time'] or '15:' in d['data_time']]

        if not morning_data:
            return {
                'success': False,
                'error': {
                    'code': 'MORNING_DATA_MISSING',
                    'message': f'未获取到 {date} 的上午分时数据，可能非交易日或数据不完整',
                    'severity': 'warning',
                    'recoverable': True,
                },
                'code': code,
                'requested_date': date,
            }

        open_price = morning_data[0]['open']
        prev_close = daily_data[1]['close'] if len(daily_data) > 1 else daily_data[0]['close']
        gap_pct = (open_price - prev_close) / prev_close * 100 if prev_close else 0

        high_price = max([d['high'] for d in morning_data])
        high_time = [d for d in morning_data if d['high'] == high_price][0]['data_time']
        low_price = min([d['low'] for d in morning_data])
        low_time = [d for d in morning_data if d['low'] == low_price][0]['data_time']
        pullback_pct = (high_price - low_price) / high_price * 100

        close_price = morning_data[-1]['close']
        close_position = (close_price - low_price) / (high_price - low_price) * 100 if high_price != low_price else 50

        total_volume = sum([d['volume'] for d in morning_data])
        first_30min_vol = sum([d['volume'] for d in morning_data[:6]])
        last_30min_vol = sum([d['volume'] for d in morning_data[-6:]])

        factors = {'技术面': 0, '量能': 0, '位置': 0, '形态': 0}

        if technical_data:
            latest_tech = technical_data[0]
            ma5 = latest_tech.get('ma5') or 0
            ma10 = latest_tech.get('ma10') or 0
            ma20 = latest_tech.get('ma20') or 0
            ma60 = latest_tech.get('ma60') or 0
            if close_price > ma5: factors['技术面'] += 25
            if close_price > ma10: factors['技术面'] += 25
            if close_price > ma20: factors['技术面'] += 25
            if close_price < ma60: factors['技术面'] -= 20

        if first_30min_vol > last_30min_vol * 1.5:
            factors['量能'] = 20
        elif first_30min_vol > last_30min_vol:
            factors['量能'] = 40
        else:
            factors['量能'] = 50

        if close_position > 70: factors['位置'] = 60
        elif close_position > 50: factors['位置'] = 50
        elif close_position > 30: factors['位置'] = 40
        else: factors['位置'] = 30

        if pullback_pct < 1.5: factors['形态'] = 70
        elif pullback_pct < 3: factors['形态'] = 50
        else: factors['形态'] = 30

        total_score = sum(factors.values()) / 4
        up_prob = min(80, max(20, total_score * 0.8))
        down_prob = min(80, max(20, (100 - total_score) * 0.8))
        range_prob = 100 - up_prob - down_prob

        return {
            'success': True, 'code': code, 'date': date, 'current_date': time_context['date'],
            'morning_review': {
                'open_price': round(open_price, 2), 'prev_close': round(prev_close, 2),
                'gap_pct': round(gap_pct, 2), 'high_price': round(high_price, 2),
                'high_time': high_time.split()[1] if ' ' in high_time else high_time,
                'low_price': round(low_price, 2),
                'low_time': low_time.split()[1] if ' ' in low_time else low_time,
                'close_price': round(close_price, 2), 'pullback_pct': round(pullback_pct, 2),
                'close_position': round(close_position, 1),
                'total_volume': round(total_volume / 10000, 0),
                'first_30min_vol_pct': round(first_30min_vol / total_volume * 100, 1) if total_volume else 0,
                'last_30min_vol_pct': round(last_30min_vol / total_volume * 100, 1) if total_volume else 0,
            },
            'afternoon_prediction': {
                'factors': factors, 'total_score': round(total_score, 1),
                'up_prob': round(up_prob, 1), 'range_prob': round(range_prob, 1),
                'down_prob': round(down_prob, 1),
            },
            'scenarios': [
                {'name': '震荡下行', 'prob': round(down_prob * 0.6, 1), 'condition': f'跌破{round(low_price * 1.01, 2)}元', 'target': f'{round(low_price * 0.985, 2)}-{round(low_price * 1.01, 2)}元'},
                {'name': '快速下跌', 'prob': round(down_prob * 0.4, 1), 'condition': f'放量跌破{round(low_price * 1.01, 2)}元', 'target': f'{round(low_price * 0.97, 2)}-{round(low_price * 0.985, 2)}元'},
                {'name': '窄幅震荡', 'prob': round(range_prob, 1), 'condition': '成交量萎缩', 'target': f'{round(low_price * 1.01, 2)}-{round(high_price * 0.99, 2)}元'},
                {'name': '震荡上行', 'prob': round(up_prob * 0.7, 1), 'condition': f'温和放量，突破{round(high_price * 0.99, 2)}元', 'target': f'{round(high_price * 0.99, 2)}-{round(high_price * 1.02, 2)}元'},
                {'name': '强势突破', 'prob': round(up_prob * 0.3, 1), 'condition': f'放量突破{round(high_price * 1.02, 2)}元', 'target': f'{round(high_price * 1.02, 2)}-{round(high_price * 1.05, 2)}元'},
            ],
        }

    @performance_monitor
    def _fetch_screener_data(self, board: str = 'a_share') -> List[Dict[str, Any]]:
        cache_key = f"screener_{board}"
        cache_ttl = 14400
        cached_time = self._screener_cache_time.get(cache_key, 0)
        if cache_key in self._screener_cache and (time.time() - cached_time) < cache_ttl:
            logger.info(f"筛选缓存命中: {board}, {len(self._screener_cache[cache_key])}只")
            return self._screener_cache[cache_key]

        board_map = {
            'a_share': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23',
            'main': 'm:1+t:2,m:0+t:6',
            'gem': 'm:0+t:80',
            'star': 'm:1+t:23',
            'sh_main': 'm:1+t:2',
            'sz_main': 'm:0+t:6',
            'bse': 'm:0+t:81,m:1+t:23',
            'hs_a': 'm:1+t:2,m:0+t:6,m:0+t:80,m:1+t:23',
        }
        market = board_map.get(board, board_map['a_share'])
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        fields = 'f12,f14,f2,f3,f9,f23,f20,f115'
        all_stocks = []
        page = 1
        while True:
            params = {
                'pn': str(page), 'pz': '200', 'po': '1', 'np': '1',
                'ut': 'bd1d9ddb04089700cf9c27f6f7426281', 'fltt': '2',
                'invt': '2', 'fid': 'f3', 'fs': market, 'fields': fields,
            }
            try:
                resp = requests.get(url, params=params,
                                    headers={'Referer': 'https://quote.eastmoney.com/',
                                             'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'},
                                    timeout=15)
                data = resp.json()
            except Exception as e:
                if page == 1:
                    data = None
                    for retry in range(3):
                        try:
                            time.sleep(2 * (retry + 1))
                            resp = requests.get(url, params=params,
                                                headers={'Referer': 'https://quote.eastmoney.com/',
                                                         'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'},
                                                timeout=15)
                            data = resp.json()
                            break
                        except Exception as e2:
                            logger.warning(f"筛选API请求重试{retry+1}失败 page={page}: {e2}")
                    if data is None:
                        break
                else:
                    logger.warning(f"筛选API请求失败 page={page}: {e}")
                    break

            diff = data.get('data', {}).get('diff', [])
            total = data.get('data', {}).get('total', 0)
            if not diff:
                break

            for item in diff:
                code = str(item.get('f12', ''))
                if not code or not code[0].isdigit():
                    continue
                close_raw = item.get('f2')
                close = None if close_raw == '-' or close_raw is None else float(close_raw)
                pe_dynamic_raw = item.get('f9')
                pe_dynamic = None if pe_dynamic_raw == '-' or pe_dynamic_raw is None else float(pe_dynamic_raw)
                pe_ttm_raw = item.get('f115')
                pe_ttm = None if pe_ttm_raw == '-' or pe_ttm_raw is None else float(pe_ttm_raw)
                pb_raw = item.get('f23')
                pb = None if pb_raw == '-' or pb_raw is None else float(pb_raw)
                mcap_raw = item.get('f20')
                market_cap_yi = None
                if mcap_raw not in ('-', None) and mcap_raw:
                    try:
                        market_cap_yi = round(float(mcap_raw) / 1e8, 2)
                    except (ValueError, TypeError):
                        pass

                all_stocks.append({
                    'code': code,
                    'name': item.get('f14'),
                    'market': 'SH' if code.startswith('6') else ('BJ' if code.startswith(('4', '8')) else 'SZ'),
                    'close': close,
                    'change_pct': item.get('f3'),
                    'pe_ttm': pe_ttm,
                    'pe_dynamic': pe_dynamic,
                    'pb': pb,
                    'market_cap': market_cap_yi,
                })

            if len(all_stocks) >= total:
                break
            page += 1
            if page > 60:
                break
            time.sleep(0.3)

        if all_stocks:
            self._screener_cache[cache_key] = all_stocks
            self._screener_cache_time[cache_key] = time.time()
            logger.info(f"筛选数据已缓存: {board}, {len(all_stocks)}只, TTL={cache_ttl}s")

        return all_stocks

    def screen_market(self, criteria: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        criteria = dict(criteria or {})
        board = criteria.get('board') or criteria.get('market') or 'a_share'
        limit = self._normalize_positive_int(criteria.get('limit'), 50, 200)
        offset = self._normalize_positive_int(criteria.get('offset'), 0, 100000)
        include_realtime = bool(criteria.get('include_realtime', False))

        filters = {
            'position_min': self._to_number(criteria.get('position_min')),
            'position_max': self._to_number(criteria.get('position_max')),
            'pe_ttm_min': self._to_number(criteria.get('pe_ttm_min')),
            'pe_ttm_max': self._to_number(criteria.get('pe_ttm_max')),
            'pb_min': self._to_number(criteria.get('pb_min')),
            'pb_max': self._to_number(criteria.get('pb_max')),
            'market_cap_min': self._to_number(criteria.get('market_cap_min')),
            'market_cap_max': self._to_number(criteria.get('market_cap_max')),
        }
        for key in ('position_min', 'position_max'):
            if filters[key] is not None and 0 < filters[key] <= 1:
                filters[key] *= 100
        has_filter = any(value is not None for value in filters.values())
        if not has_filter and not criteria.get('allow_no_filters', False):
            return {'success': False, 'error': '市场筛选必须提供至少一个筛选条件，例如 position_max、pe_ttm_max、pb_max 或 market_cap_min。'}

        all_stocks = self._fetch_screener_data(board)
        if not all_stocks:
            return {'success': False, 'error': '无法获取市场筛选数据，请稍后重试'}

        need_position = filters['position_min'] is not None or filters['position_max'] is not None
        position_map = {}
        if need_position:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        'SELECT code, position_pct, high_52w, low_52w FROM stock_technical '
                        'WHERE position_pct IS NOT NULL'
                    )
                    for row in cursor.fetchall():
                        position_map[row[0]] = {
                            'position_pct': row[1],
                            'high_52w': row[2],
                            'low_52w': row[3],
                        }
            except Exception as e:
                logger.warning(f"获取52周位置数据失败: {e}")

        matched = []
        for row in all_stocks:
            if need_position:
                pos_data = position_map.get(row['code'])
                if pos_data:
                    row['position_pct'] = pos_data['position_pct']
                    row['high_52w'] = pos_data['high_52w']
                    row['low_52w'] = pos_data['low_52w']
                else:
                    row['position_pct'] = None
                if not self._passes_range(row.get('position_pct'), filters['position_min'], filters['position_max']):
                    continue
            pe = row.get('pe_ttm')
            if filters['pe_ttm_min'] is not None or filters['pe_ttm_max'] is not None:
                if pe is None or pe < 0:
                    continue
                if not self._passes_range(pe, filters['pe_ttm_min'], filters['pe_ttm_max']):
                    continue
            if not self._passes_range(row.get('pb'), filters['pb_min'], filters['pb_max']):
                continue
            if not self._passes_range(row.get('market_cap'), filters['market_cap_min'], filters['market_cap_max']):
                continue
            matched.append(row)

        sort_by = criteria.get('sort_by', 'pe_ttm')
        allowed_sort = {'position_pct', 'pe_ttm', 'pb', 'market_cap', 'close', 'code', 'name'}
        if sort_by not in allowed_sort:
            sort_by = 'pe_ttm'
        reverse = criteria.get('sort_order', 'asc') == 'desc'

        non_null = [item for item in matched if item.get(sort_by) is not None]
        null_items = [item for item in matched if item.get(sort_by) is None]
        non_null.sort(key=lambda item: item.get(sort_by), reverse=reverse)
        matched = non_null + null_items
        page = matched[offset:offset + limit]

        if include_realtime and page:
            realtime_rows = self.get_latest_data(
                [item['code'] for item in page],
                include_realtime=True,
            )
            by_code = {item['code']: item for item in realtime_rows}
            page = [by_code.get(item['code'], item) for item in page]

        matched_count = len(matched)
        has_more = (offset + limit) < matched_count

        return {
            'success': True,
            'board': board,
            'matched_count': matched_count,
            'returned': len(page),
            'offset': offset, 'limit': limit, 'has_more': has_more,
            'page_info': {
                'current_offset': offset, 'current_limit': limit,
                'total_matched': matched_count, 'has_more': has_more,
                'next_offset': offset + limit if has_more else None,
            },
            'results': page,
        }

    def get_db_stats(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM stock_info')
            stock_count = cursor.fetchone()[0]
            cursor.execute('SELECT COUNT(*) FROM stock_daily')
            daily_count = cursor.fetchone()[0]
            cursor.execute('SELECT COUNT(*) FROM stock_valuation')
            valuation_count = cursor.fetchone()[0]
            cursor.execute('SELECT COUNT(*) FROM stock_technical')
            technical_count = cursor.fetchone()[0]
            cursor.execute('SELECT COUNT(*) FROM stock_minute')
            minute_count = cursor.fetchone()[0]
            cursor.execute('SELECT MIN(data_date), MAX(data_date) FROM stock_daily')
            date_range = cursor.fetchone()
        return {
            'stock_count': stock_count, 'daily_count': daily_count,
            'valuation_count': valuation_count, 'technical_count': technical_count,
            'minute_count': minute_count, 'date_range': date_range,
        }

    # ==================== MCP Tool Handlers ====================

    @staticmethod
    def _make_data_error(code, result, data_label='数据'):
        from providers.base import ErrorType
        err = result.error
        err_type = err.error_type if err else ErrorType.UNKNOWN
        err_msg = err.message if err else '未知错误'

        if err_type in (ErrorType.AUTH_ERROR, ErrorType.INVALID_PARAMS):
            return create_error_response(
                message=f"股票代码 {code} 无效或不存在，无法获取{data_label}",
                error_code='INVALID_CODE',
                recoverable=False,
                suggested_action=f"请检查股票代码 {code} 是否正确",
            )

        if err_type == ErrorType.RATE_LIMITED:
            return create_error_response(
                message=f"获取{data_label}时API限流，请5分钟后重试",
                error_code='RATE_LIMITED',
                recoverable=True,
                suggested_action="等待5分钟后重试",
            )

        if err_type in (ErrorType.CONNECTION_ERROR, ErrorType.TIMEOUT):
            return create_error_response(
                message=f"网络异常，无法获取{data_label}。请稍后重试",
                error_code='NETWORK_ERROR',
                recoverable=True,
                suggested_action="检查网络连接后重试",
            )

        return create_error_response(
            message=f"获取{data_label}失败: {err_msg}",
            error_code=err_type.value if err else 'UNKNOWN',
            recoverable=True,
            suggested_action="稍后重试，或尝试其他股票",
        )

    def _handle_get_current_time(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return create_success_response(self.get_current_time_info())

    def _handle_get_realtime_quote(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        result = self.provider_manager.fetch_realtime(code)
        if result.success:
            return create_success_response(result.data)
        else:
            return self._make_data_error(code, result, '实时行情')

    def _handle_get_realtime_quotes(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        codes = arguments.get('codes', [])
        if not codes:
            raise ValidationError("缺少股票代码列表", field='codes')
        if len(codes) > 20:
            raise ValidationError("单次最多20只股票", field='codes', value=len(codes))
        results = self.get_realtime_prices(codes, 0.2)
        return create_success_response(results)

    def _handle_get_daily_kline(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        days = arguments.get('days', 250)

        data = self.get_daily_data(code, start_date, end_date, limit=days)
        if not data:
            return create_error_response(
                message=f"未获取到 {code} 的日K线数据",
                error_code='DATA_NOT_FOUND',
                recoverable=True,
                suggested_action="请检查股票代码是否正确，或稍后重试",
            )
        return create_success_response(data)

    def _handle_get_minute_kline(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        klt = arguments.get('klt', 5)
        days = arguments.get('days', 5)

        time_info = self.get_current_time_info()
        today = time_info['date']
        from datetime import timedelta as _td
        start_date = (datetime.strptime(today, '%Y-%m-%d') - _td(days=days)).strftime('%Y-%m-%d')
        start_time = f'{start_date} 09:30'
        end_time = f'{today} 15:00'

        data = self.get_minute_data(code, klt, start_time=start_time, end_time=end_time)
        if not data:
            return create_error_response(
                message=f"未获取到 {code} 的分钟K线数据",
                error_code='DATA_NOT_FOUND',
                recoverable=True,
                suggested_action="非交易时段无分钟数据，请在交易时间重试",
            )
        return create_success_response(data)

    def _handle_get_valuation(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        limit = arguments.get('limit')

        data = self.get_valuation_data(code, start_date, end_date, limit)
        if not data:
            return create_error_response(
                message=f"未获取到 {code} 的估值数据",
                error_code='DATA_NOT_FOUND',
                recoverable=True,
                suggested_action="请检查股票代码是否正确，或稍后重试",
            )
        return create_success_response(data)

    def _handle_get_fund_flow(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        limit = arguments.get('limit')

        data = self.get_fund_flow(code, start_date, end_date, limit)
        if not data:
            return create_error_response(
                message=f"未获取到 {code} 的资金流向数据。该股票可能暂无资金流向记录",
                error_code='DATA_NOT_FOUND',
                recoverable=True,
                suggested_action="请检查股票代码是否正确。部分小盘股/新股可能无资金流向数据",
            )
        return create_success_response(data)

    def _handle_get_stock_list(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        board = arguments.get('board', 'a_share')
        page = arguments.get('page')
        page_size = arguments.get('page_size', 100)

        result = self.provider_manager.fetch_stock_list(board)
        if not result.success:
            return self._make_data_error(board, result, '股票列表')

        stocks = result.data
        codes = [s['code'] for s in stocks]

        if page:
            page = max(1, page)
            page_size = min(100, max(1, page_size))
            start = (page - 1) * page_size
            end = start + page_size
            page_stocks = stocks[start:end]
            page_codes = codes[start:end]
            return create_success_response({
                'stocks': page_stocks, 'codes': page_codes,
                'total': len(stocks), 'page': page,
                'page_size': page_size,
                'total_pages': (len(stocks) + page_size - 1) // page_size,
            })

        return create_success_response({
            'stocks': stocks, 'codes': codes, 'total': len(stocks),
        })

    def _handle_get_financial_data(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        report_type = arguments.get('report_type', 'income')
        result = self.provider_manager.fetch_financial(code, report_type)
        if result.success:
            return create_success_response(result.data)
        else:
            return self._make_data_error(code, result, '财务数据')

    def _handle_analyze_position(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        codes = arguments.get('codes', [])
        if not codes:
            raise ValidationError("缺少股票代码列表", field='codes')
        if len(codes) > 100:
            raise ValidationError("单次最多100只股票", field='codes', value=len(codes))
        result = self.analyze_position(codes)
        return create_success_response(result)

    def _handle_get_technical_indicators(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        limit = arguments.get('limit')

        data = self.get_technical_data(code, start_date, end_date, limit)
        if not data:
            return create_error_response(
                message=f"未获取到 {code} 的技术指标数据",
                error_code='DATA_NOT_FOUND',
                recoverable=True,
                suggested_action="请检查股票代码是否正确，或稍后重试",
            )
        return create_success_response(data[-50:] if len(data) > 50 else data)

    def _handle_analyze_stock(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        fund_flow_days = arguments.get('fund_flow_days', 10)

        indicators = self.get_technical_data(code)
        if not indicators:
            return create_error_response(
                message=f"未获取到 {code} 的技术指标数据，无法进行分析",
                error_code='DATA_NOT_FOUND',
                recoverable=True,
                suggested_action="请检查股票代码是否正确，或稍后重试",
            )

        kline_data = self.get_daily_data(code)
        if not kline_data:
            return create_error_response(
                message=f"未获取到 {code} 的K线数据，无法进行分析",
                error_code='DATA_NOT_FOUND',
                recoverable=True,
                suggested_action="请检查股票代码是否正确，或稍后重试",
            )

        kline_sorted = sorted(kline_data, key=lambda x: x.get('date', ''))
        closes = [float(r['close']) for r in kline_sorted if r.get('close')]
        highs = [float(r['high']) for r in kline_sorted if r.get('high')]
        lows = [float(r['low']) for r in kline_sorted if r.get('low')]
        volumes = [float(r.get('volume') or 0) for r in kline_sorted]

        tech_signals = generate_technical_signals(indicators)
        returns_analysis = calculate_returns(closes)
        volume_analysis = calculate_volume_analysis(volumes, closes)
        support_resistance = calculate_support_resistance(highs, lows, closes)

        fund_flow_result = self.analyze_main_force(code, days=fund_flow_days)
        fund_flow_summary = None
        if fund_flow_result.get('success'):
            fund_flow_summary = {
                'trend': fund_flow_result.get('trend'),
                'strength': fund_flow_result.get('strength'),
                'total_main_inflow': fund_flow_result.get('total_main_inflow'),
                'consecutive_inflow': fund_flow_result.get('consecutive_inflow'),
                'consecutive_outflow': fund_flow_result.get('consecutive_outflow'),
                'latest_main_inflow_pct': fund_flow_result.get('latest_main_inflow_pct'),
            }

        valuation_data = self.get_valuation_data(code)
        valuation_summary = None
        if valuation_data:
            latest_val = valuation_data[-1] if valuation_data else {}
            pe_ttm = latest_val.get('pe_ttm')
            pb = latest_val.get('pb')
            market_cap = latest_val.get('market_cap')
            valuation_level = 'unknown'
            if pe_ttm is not None:
                if pe_ttm < 0:
                    valuation_level = 'loss'
                elif pe_ttm < 15:
                    valuation_level = 'undervalued'
                elif pe_ttm < 30:
                    valuation_level = 'fair'
                elif pe_ttm < 60:
                    valuation_level = 'overvalued'
                else:
                    valuation_level = 'expensive'
            valuation_summary = {
                'pe_ttm': pe_ttm,
                'pb': pb,
                'market_cap_yi': round(market_cap / 100000000, 2) if market_cap else None,
                'valuation_level': valuation_level,
            }

        result = {
            'code': code,
            'technical_signals': tech_signals,
            'risk_metrics': returns_analysis,
            'volume_analysis': volume_analysis,
            'support_resistance': support_resistance,
            'fund_flow': fund_flow_summary,
            'valuation': valuation_summary,
        }

        return create_success_response(result)

    def _handle_get_latest_data(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        codes = arguments.get('codes', [])
        if not codes:
            raise ValidationError("缺少股票代码列表", field='codes')
        if len(codes) > 30:
            raise ValidationError("单次最多30只股票", field='codes', value=len(codes))
        include_realtime = arguments.get('include_realtime', False)
        results = self.get_latest_data(codes, include_realtime=include_realtime)
        if not results:
            return create_error_response(
                message="未获取到任何股票数据，请检查股票代码是否正确",
                error_code='DATA_NOT_FOUND',
                recoverable=True,
                suggested_action="请检查股票代码是否正确",
            )
        return create_success_response(results)

    def _handle_get_stock_detail(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        include_realtime = arguments.get('include_realtime', True)
        fund_flow_days = arguments.get('fund_flow_days', 10)

        info = self.get_stock_info(code, auto_refresh=True)
        if not info:
            return create_error_response(
                message=f"未找到股票 {code} 的信息，请检查股票代码是否正确",
                error_code='INVALID_CODE',
                recoverable=False,
                suggested_action=f"请确认股票代码 {code} 是否正确",
            )

        latest_list = self.get_latest_data([code], include_realtime=include_realtime)
        latest = latest_list[0] if latest_list else None
        fund_flow = self.analyze_main_force(code, days=fund_flow_days)

        result = {
            'code': code,
            'info': info,
            'latest': latest,
        }

        if fund_flow.get('success'):
            result['fund_flow'] = {
                'trend': fund_flow.get('trend'),
                'strength': fund_flow.get('strength'),
                'total_main_inflow': fund_flow.get('total_main_inflow'),
                'avg_main_inflow_pct': fund_flow.get('avg_main_inflow_pct'),
                'positive_days': fund_flow.get('positive_days'),
                'negative_days': fund_flow.get('negative_days'),
                'consecutive_inflow': fund_flow.get('consecutive_inflow'),
                'consecutive_outflow': fund_flow.get('consecutive_outflow'),
                'latest_date': fund_flow.get('latest_date'),
                'latest_main_inflow': fund_flow.get('latest_main_inflow'),
                'latest_main_inflow_pct': fund_flow.get('latest_main_inflow_pct'),
            }

        return create_success_response(result)

    def _handle_analyze_intraday(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        date = arguments.get('date')
        result = self.analyze_intraday(code, date)
        if result.get('success'):
            return create_success_response(result)
        else:
            error = result.get('error', {})
            error_code = error.get('code', 'ANALYSIS_FAILED')
            message = error.get('message', '日内分析失败')
            severity = error.get('severity', 'error')
            recoverable = error.get('recoverable', True)
            suggested_action = error.get('suggested_action')

            return create_error_response(
                message=message,
                error_code=error_code,
                recoverable=recoverable,
                suggested_action=suggested_action,
            )

    def _handle_analyze_main_force(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        days = arguments.get('days', 10)
        result = self.analyze_main_force(code, days)
        if result.get('success'):
            return create_success_response(result)
        else:
            return create_error_response(
                message=f"无法分析 {code} 的主力资金动向: {result.get('error', '无资金流向数据')}",
                error_code='DATA_NOT_FOUND',
                recoverable=True,
                suggested_action="部分小盘股/新股可能无资金流向数据，请检查股票代码",
            )

    def _handle_screen_market(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return self.screen_market(arguments)

    handle_tool_call_handlers = None

    def handle_tool_call(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        handlers = {
            'get_current_time': self._handle_get_current_time,
            'get_realtime_quote': self._handle_get_realtime_quote,
            'get_realtime_quotes': self._handle_get_realtime_quotes,
            'get_daily_kline': self._handle_get_daily_kline,
            'get_minute_kline': self._handle_get_minute_kline,
            'get_valuation': self._handle_get_valuation,
            'get_fund_flow': self._handle_get_fund_flow,
            'get_stock_list': self._handle_get_stock_list,
            'get_financial_data': self._handle_get_financial_data,
            'analyze_position': self._handle_analyze_position,
            'get_technical_indicators': self._handle_get_technical_indicators,
            'analyze_stock': self._handle_analyze_stock,
            'get_latest_data': self._handle_get_latest_data,
            'get_stock_detail': self._handle_get_stock_detail,
            'analyze_intraday': self._handle_analyze_intraday,
            'analyze_main_force': self._handle_analyze_main_force,
            'screen_market': self._handle_screen_market,
        }

        handler = handlers.get(name)
        if not handler:
            return create_error_response(
                message=f"未知工具: {name}",
                error_code='UNKNOWN_TOOL',
                recoverable=False,
                suggested_action="请检查工具名称是否正确",
            )

        try:
            return _sanitize_for_agent(handler(arguments or {}))
        except ValidationError as e:
            return e.to_dict()
        except DataNotFoundError as e:
            return e.to_dict()
        except Exception as e:
            return handle_error(e, {'tool': name, 'arguments': arguments})


server = StockPoolServer()


async def handle_request(request):
    method = request.get("method")
    request_id = request.get("id")
    is_notification = "id" not in request

    if is_notification:
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "stock-pool-v2", "version": "2.0.0"},
            }
        }
    elif method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}
    elif method == "tools/call":
        params = request.get("params", {})
        name = params.get("name")
        arguments = params.get("arguments", {})
        result = server.handle_tool_call(name, arguments)
        return {
            "jsonrpc": "2.0", "id": request_id,
            "result": {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}]},
        }
    else:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}


async def main():
    while True:
        request_id = None
        try:
            line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
            if not line:
                break
            request = json.loads(line.strip())
            request_id = request.get("id") if isinstance(request, dict) else None
            response = await handle_request(request)
            if response is not None:
                print(json.dumps(response), flush=True)
        except json.JSONDecodeError:
            continue
        except Exception as e:
            if request_id is not None:
                error_response = {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32603, "message": str(e)}}
                print(json.dumps(error_response), flush=True)
            else:
                print(f"MCP server error: {e}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
