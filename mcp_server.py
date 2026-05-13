import asyncio
import json
import sys
import os
import time
import builtins
import sqlite3
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

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
    ValidationError, DataNotFoundError, Logger,
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
    seconds_until_intraday_data,
    intraday_resolution,
)
from indicators import calculate_ma, calculate_technical_indicators, ema, rsi
from sync_jobs import SyncJobStore, json_dumps, json_loads, sync_job_from_row


def _log(*args, **kwargs):
    kwargs.setdefault('file', sys.stderr)
    return builtins.print(*args, **kwargs)


_SANITIZE_DROP = object()
_SANITIZE_KEY_MAP = {
    'cache_used': _SANITIZE_DROP,
    'no_cached_snapshot': 'missing_data',
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
        self.sync_jobs = SyncJobStore(self._connect, self._normalize_positive_int, self.get_current_time_info)
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
    def _normalize_limit(limit):
        if limit is None:
            return None
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise ValueError('limit 必须是正整数')
        if limit <= 0 or limit > 10000:
            raise ValueError('limit 必须在 1 到 10000 之间')
        return limit

    @staticmethod
    def _normalize_offset(offset):
        if offset is None:
            return 0
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            raise ValueError('offset 必须是非负整数')
        if offset < 0 or offset > 1000000:
            raise ValueError('offset 必须在 0 到 1000000 之间')
        return offset

    @staticmethod
    def _normalize_positive_int(value, default, maximum):
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = default
        return max(0, min(value, maximum))

    @staticmethod
    def _to_number(value):
        if value is None or value == '':
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _passes_range(value, min_value=None, max_value=None):
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

    @staticmethod
    def _needs_daily_refresh(freshness, refresh, today):
        if refresh == 'force':
            return True
        if refresh == 'missing' and not freshness.get('has_data'):
            return True
        if refresh == 'stale':
            if not freshness.get('has_data'):
                return True
            if freshness.get('should_refresh') is not None:
                return freshness.get('should_refresh')
            return freshness.get('latest_date') != today
        return False

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
        if fund_flow_items:
            with self._get_connection() as conn:
                saved = storage_save_fund_flow_data(conn, code, fund_flow_items)
            _log(f"  资金流向: {saved} 条 [来源: {result.provider_name}]")
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
            except Exception:
                pass

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
            except Exception:
                pass

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
            except Exception:
                pass

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
            except Exception:
                pass

        return data

    def get_fund_flow(self, code, start_date=None, end_date=None, limit=None, offset=0):
        limit = self._normalize_limit(limit)
        offset = self._normalize_offset(offset)
        with self._get_connection() as conn:
            return storage_get_fund_flow_data(conn, code, start_date, end_date, limit, offset)

    def get_minute_data(self, code, klt=5, start_time=None, end_time=None, limit=None, offset=0):
        with self._get_connection() as conn:
            return minute_get_minute_data(conn, code, klt, start_time, end_time, limit, offset,
                                          self._normalize_limit, self._normalize_offset)

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

        data_5min = self.get_minute_data(code, klt=5, start_time=f'{date} 09:30', end_time=f'{date} 15:00')
        daily_data = self.get_daily_data(code, limit=2)
        technical_data = self.get_technical_data(code, start_date=date)

        if not data_5min:
            minute_freshness = self.check_data_freshness(code, 'minute', klt=5)
            daily_freshness = self.check_data_freshness(code, 'daily')
            return {
                'success': False, 'status': 'missing_minute_data',
                'code': code, 'requested_date': date, 'current_date': time_context['date'],
                'message': f'未获取到 {date} 的5分钟分时数据',
                'latest_minute_time': minute_freshness.get('latest_time'),
                'latest_daily_date': daily_freshness.get('latest_date'),
                'next_actions': ['update_minute_data', 'update_stock'],
                'resolution': intraday_resolution(code, date, time_context, [
                    {'tool': 'update_minute_data', 'arguments': {'code': code, 'klt': 5, 'days': 2, 'force': True, 'start_time': f'{date} 09:30', 'end_time': f'{date} 15:00'}},
                    {'tool': 'update_stock', 'arguments': {'code': code, 'days': 10, 'force': True}},
                ], '本地缺少请求日期的5分钟分时数据', seconds_until_intraday_data),
                'do_not_analyze_other_date': True,
            }

        if not daily_data:
            daily_freshness = self.check_data_freshness(code, 'daily')
            return {
                'success': False, 'status': 'missing_daily_data',
                'code': code, 'requested_date': date, 'current_date': time_context['date'],
                'message': f'未获取到 {date} 可用的日K数据',
                'latest_daily_date': daily_freshness.get('latest_date'),
                'next_actions': ['update_stock'],
                'resolution': intraday_resolution(code, date, time_context, [
                    {'tool': 'update_stock', 'arguments': {'code': code, 'days': 10, 'force': True}},
                ], '本地缺少请求日期可用的日K数据', seconds_until_intraday_data),
                'do_not_analyze_other_date': True,
            }

        data_5min.reverse()
        morning_data = [d for d in data_5min if '09:' in d['data_time'] or '10:' in d['data_time'] or '11:' in d['data_time']]
        afternoon_data = [d for d in data_5min if '13:' in d['data_time'] or '14:' in d['data_time'] or '15:' in d['data_time']]

        if not morning_data:
            return {
                'success': False, 'status': 'missing_morning_data',
                'code': code, 'requested_date': date, 'current_date': time_context['date'],
                'message': f'未获取到 {date} 的上午分时数据',
                'next_actions': ['update_minute_data'],
                'resolution': intraday_resolution(code, date, time_context, [
                    {'tool': 'update_minute_data', 'arguments': {'code': code, 'klt': 5, 'days': 2, 'force': True, 'start_time': f'{date} 09:30', 'end_time': f'{date} 15:00'}},
                ], '本地缺少请求日期的上午分时数据', seconds_until_intraday_data),
                'do_not_analyze_other_date': True,
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

    def screen_market(self, criteria=None):
        criteria = dict(criteria or {})
        board = criteria.get('board') or criteria.get('market') or 'a_share'
        limit = self._normalize_positive_int(criteria.get('limit'), 50, 200)
        offset = self._normalize_positive_int(criteria.get('offset'), 0, 100000)
        universe_limit = criteria.get('universe_limit')
        if universe_limit is not None:
            universe_limit = self._normalize_positive_int(universe_limit, 0, 5000)
        batch_size = self._normalize_positive_int(criteria.get('batch_size'), 200, 500) or 200
        include_realtime = bool(criteria.get('include_realtime', False))
        realtime_limit = self._normalize_positive_int(criteria.get('realtime_limit'), 20, 50)
        refresh = criteria.get('refresh', 'none')
        if refresh not in ('none', 'missing', 'stale', 'force'):
            refresh = 'none'
        default_max_refresh = 200 if refresh != 'none' else 0
        max_refresh = self._normalize_positive_int(criteria.get('max_refresh'), default_max_refresh, 200)
        days = self._normalize_positive_int(criteria.get('days'), 250, 500) or 250
        delay = self._to_number(criteria.get('delay'))
        if delay is None:
            delay = 0.2

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

        stock_list_result = self.provider_manager.fetch_stock_list(board)
        if not stock_list_result.success:
            return {'success': False, 'error': f'获取股票列表失败: {stock_list_result.error.message}'}
        stocks = stock_list_result.data
        codes = [s['code'] for s in stocks]

        refreshed = {'attempted': 0, 'success': 0, 'failed': 0, 'mode': refresh}
        if refresh != 'none' and max_refresh > 0:
            today = self.get_current_time_info()['date']
            for code in codes:
                if refreshed['attempted'] >= max_refresh:
                    break
                freshness = self.check_data_freshness(code, 'daily')
                if not self._needs_daily_refresh(freshness, refresh, today):
                    continue
                refreshed['attempted'] += 1
                try:
                    self.update_stock(code, days=days, delay=delay, force=(refresh == 'force'))
                    refreshed['success'] += 1
                except Exception as e:
                    _log(f"  筛选刷新失败 {code}: {e}")
                    refreshed['failed'] += 1

        snapshots = self.get_latest_data(codes, include_realtime=False, batch_size=batch_size)
        matched = []
        skipped_no_snapshot = max(0, len(codes) - len(snapshots))

        for row in snapshots:
            if not self._passes_range(row.get('position_pct'), filters['position_min'], filters['position_max']):
                continue
            if not self._passes_range(row.get('pe_ttm'), filters['pe_ttm_min'], filters['pe_ttm_max']):
                continue
            if not self._passes_range(row.get('pb'), filters['pb_min'], filters['pb_max']):
                continue
            if not self._passes_range(row.get('market_cap'), filters['market_cap_min'], filters['market_cap_max']):
                continue
            matched.append(row)

        sort_by = criteria.get('sort_by', 'position_pct')
        allowed_sort = {'position_pct', 'pe_ttm', 'pb', 'market_cap', 'close', 'code', 'date'}
        if sort_by not in allowed_sort:
            sort_by = 'position_pct'
        reverse = criteria.get('sort_order', 'asc') == 'desc'

        non_null = [item for item in matched if item.get(sort_by) is not None]
        null_items = [item for item in matched if item.get(sort_by) is None]
        non_null.sort(key=lambda item: item.get(sort_by), reverse=reverse)
        matched = non_null + null_items
        page = matched[offset:offset + limit]

        if include_realtime and page:
            realtime_rows = self.get_latest_data(
                [item['code'] for item in page],
                include_realtime=True, realtime_limit=realtime_limit, batch_size=batch_size,
            )
            by_code = {item['code']: item for item in realtime_rows}
            page = [by_code.get(item['code'], item) for item in page]

        matched_count = len(matched)
        has_more = (offset + limit) < matched_count

        return {
            'success': True,
            'board': board,
            'criteria': {k: v for k, v in criteria.items() if v is not None},
            'universe_total': len(codes),
            'universe_returned': len(codes),
            'snapshot_count': len(snapshots),
            'matched_count': matched_count,
            'returned': len(page),
            'offset': offset, 'limit': limit, 'has_more': has_more,
            'page_info': {
                'current_offset': offset, 'current_limit': limit,
                'total_matched': matched_count, 'has_more': has_more,
                'next_offset': offset + limit if has_more else None,
            },
            'refresh': refreshed,
            'skipped': {'no_cached_snapshot': skipped_no_snapshot},
            'results': page,
            'time_context': self.get_current_time_info(),
        }

    def sync_market(self, board='a_share', refresh='stale', max_codes=None, days=250, delay=0.2):
        if refresh not in ('missing', 'stale', 'force'):
            refresh = 'stale'
        if max_codes is not None:
            max_codes = self._normalize_positive_int(max_codes, 0, 100000)
        days = self._normalize_positive_int(days, 250, 500) or 250
        delay = self._to_number(delay)
        if delay is None:
            delay = 0.2

        stock_list_result = self.provider_manager.fetch_stock_list(board)
        if not stock_list_result.success:
            return {'success': False, 'error': f'获取股票列表失败: {stock_list_result.error.message}'}
        codes = [s['code'] for s in stock_list_result.data]
        if max_codes:
            codes = codes[:max_codes]

        today = self.get_current_time_info()['date']
        summary = {
            'success': True, 'board': board, 'refresh': refresh,
            'total': len(codes), 'scanned': 0, 'refreshed': 0,
            'skipped_fresh': 0, 'failed': 0, 'stopped': False,
            'current_code': None, 'failures': [],
        }

        for code in codes:
            summary['current_code'] = code
            summary['scanned'] += 1
            try:
                freshness = self.check_data_freshness(code, 'daily')
                if not self._needs_daily_refresh(freshness, refresh, today):
                    summary['skipped_fresh'] += 1
                else:
                    self.update_stock(code, days=days, delay=delay, force=(refresh == 'force'))
                    summary['refreshed'] += 1
            except Exception as e:
                summary['failed'] += 1
                if len(summary['failures']) < 20:
                    summary['failures'].append({'code': code, 'error': str(e)})
                _log(f"  市场同步失败 {code}: {e}")

        summary['current_code'] = None
        return summary

    def check_missing_data(self, codes, start_date, end_date):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            missing = {}
            for code in codes:
                cursor.execute('SELECT COUNT(*) FROM stock_daily WHERE code = ? AND data_date BETWEEN ? AND ?',
                             (code, start_date, end_date))
                count = cursor.fetchone()[0]
                if count == 0:
                    missing[code] = 'no_data'
        return missing

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

    def _handle_get_current_time(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return create_success_response(self.get_current_time_info())

    def _handle_get_provider_status(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return create_success_response(self.provider_manager.get_status())

    def _handle_get_realtime_quote(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        providers = arguments.get('providers')
        result = self.provider_manager.fetch_realtime(code, providers)
        if result.success:
            return create_success_response(result.data, metadata={
                'provider': result.provider_name,
                'fallback_used': result.fallback_used,
                'fallback_chain': result.fallback_chain,
            })
        else:
            return create_error_response(
                message=result.error.message, error_code=result.error.error_type.value,
                details={'provider': result.provider_name, 'fallback_chain': result.fallback_chain},
                suggested_action="尝试其他数据源或稍后重试",
            )

    def _handle_get_realtime_quotes(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        codes = arguments.get('codes', [])
        if not codes:
            raise ValidationError("缺少股票代码列表", field='codes')
        if len(codes) > 20:
            raise ValidationError("单次最多20只股票", field='codes', value=len(codes))
        delay = arguments.get('delay', 0.2)
        results = self.get_realtime_prices(codes, delay)
        return create_success_response(results)

    def _handle_get_daily_kline(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        limit = arguments.get('limit')
        offset = arguments.get('offset', 0)
        include_realtime = arguments.get('include_realtime', True)

        data = self.get_daily_data(code, start_date, end_date, limit, offset, include_realtime)
        return create_success_response(data, metadata={'count': len(data)})

    def _handle_get_minute_kline(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        klt = arguments.get('klt', 5)
        start_time = arguments.get('start_time')
        end_time = arguments.get('end_time')
        limit = arguments.get('limit')
        offset = arguments.get('offset', 0)

        data = self.get_minute_data(code, klt, start_time, end_time, limit, offset)
        return create_success_response(data, metadata={'klt': klt, 'count': len(data)})

    def _handle_get_valuation(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        limit = arguments.get('limit')
        offset = arguments.get('offset', 0)

        data = self.get_valuation_data(code, start_date, end_date, limit, offset)
        return create_success_response(data, metadata={'count': len(data)})

    def _handle_get_fund_flow(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        limit = arguments.get('limit')
        offset = arguments.get('offset', 0)

        data = self.get_fund_flow(code, start_date, end_date, limit, offset)
        return create_success_response(data, metadata={'count': len(data)})

    def _handle_get_stock_list(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        board = arguments.get('board', 'a_share')
        providers = arguments.get('providers')
        result = self.provider_manager.fetch_stock_list(board, providers)
        if result.success:
            stocks = result.data
            codes = [s['code'] for s in stocks]
            return create_success_response(
                {'stocks': stocks, 'codes': codes, 'total': len(stocks)},
                metadata={'provider': result.provider_name, 'board': board},
            )
        else:
            return create_error_response(message=result.error.message, error_code=result.error.error_type.value)

    def _handle_get_stock_universe(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        board = arguments.get('board', 'a_share')
        page = arguments.get('page')
        page_size = arguments.get('page_size', 100)
        limit = arguments.get('limit')

        result = self.provider_manager.fetch_stock_list(board)
        if not result.success:
            return create_error_response(message=result.error.message, error_code=result.error.error_type.value)

        stocks = result.data
        if limit and not page:
            stocks = stocks[:limit]
            return create_success_response({
                'stocks': stocks, 'total': len(stocks), 'board': board,
            }, metadata={'provider': result.provider_name})

        if page:
            page = max(1, page)
            page_size = min(100, max(1, page_size))
            start = (page - 1) * page_size
            end = start + page_size
            page_stocks = stocks[start:end]
            return create_success_response({
                'stocks': page_stocks,
                'total': len(stocks),
                'board': board,
                'page': page,
                'page_size': page_size,
                'total_pages': (len(stocks) + page_size - 1) // page_size,
            }, metadata={'provider': result.provider_name})

        return create_success_response({
            'stocks': stocks, 'total': len(stocks), 'board': board,
        }, metadata={'provider': result.provider_name})

    def _handle_get_all_stocks(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        board = arguments.get('board', 'a_share')
        result = self.provider_manager.fetch_stock_list(board)
        if not result.success:
            return create_error_response(message=result.error.message, error_code=result.error.error_type.value)
        stocks = result.data
        return create_success_response({
            'stocks': stocks, 'total': len(stocks), 'board': board,
        }, metadata={'provider': result.provider_name})

    def _handle_get_financial_data(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        report_type = arguments.get('report_type', 'income')
        providers = arguments.get('providers')
        result = self.provider_manager.fetch_financial(code, report_type, providers)
        if result.success:
            return create_success_response(result.data, metadata={'provider': result.provider_name, 'report_type': report_type})
        else:
            return create_error_response(message=result.error.message, error_code=result.error.error_type.value, suggested_action="TuShare需要配置Token，或使用AkShare")

    def _handle_update_stock(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        days = arguments.get('days', 250)
        force = arguments.get('force', False)
        result = self.update_stock(code, days, delay=0, force=force)
        return create_success_response(result, message=f"已更新 {code}")

    def _handle_update_stocks(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        codes = arguments.get('codes', [])
        if not codes:
            raise ValidationError("缺少股票代码列表", field='codes')
        if len(codes) > 50:
            raise ValidationError("单次最多50只股票", field='codes', value=len(codes))
        days = arguments.get('days', 250)
        force = arguments.get('force', False)

        if len(codes) > 10:
            job_id = f"update_{int(time.time())}"
            now_text = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            job = {
                'job_id': job_id, 'status': 'running',
                'args': {'codes': codes, 'days': days, 'force': force},
                'progress': {'completed': 0, 'total': len(codes)},
                'result': None, 'error': None,
                'created_at': now_text, 'updated_at': now_text,
            }
            self.sync_jobs.save(job)

            def _run_batch():
                results = {}
                for code in codes:
                    try:
                        r = self.update_stock(code, days, delay=0.5, force=force)
                        results[code] = 'success' if r.get('success') else 'failed'
                    except Exception as e:
                        results[code] = str(e)
                    self.sync_jobs.update(job_id,
                        progress={'completed': len(results), 'total': len(codes)},
                        updated_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    )
                self.sync_jobs.update(job_id,
                    status='completed',
                    result=results,
                    finished_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                )

            worker = threading.Thread(target=_run_batch, daemon=True)
            worker.start()
            return create_success_response({
                'job_id': job_id,
                'status': 'running',
                'message': f'批量更新已启动({len(codes)}只)，使用 get_sync_status(job_id="{job_id}") 查询进度',
            })

        results = {}
        for code in codes:
            try:
                r = self.update_stock(code, days, delay=0.5, force=force)
                results[code] = 'success' if r.get('success') else 'failed'
            except Exception as e:
                results[code] = str(e)
        return create_success_response({'results': results})

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
            return create_error_response(message="无技术指标数据，请先调用 update_stock", error_code="DATA_NOT_FOUND", suggested_action="调用 update_stock 更新数据")
        return create_success_response(data[-50:] if len(data) > 50 else data)

    def _handle_get_latest_data(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        codes = arguments.get('codes', [])
        if not codes:
            raise ValidationError("缺少股票代码列表", field='codes')
        if len(codes) > 30:
            raise ValidationError("单次最多30只股票", field='codes', value=len(codes))
        include_realtime = arguments.get('include_realtime', False)
        realtime_limit = arguments.get('realtime_limit')
        batch_size = arguments.get('batch_size', 200)
        results = self.get_latest_data(codes, include_realtime, realtime_limit, batch_size)
        return create_success_response(results)

    def _handle_get_stock_info(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        info = self.get_stock_info(code)
        if info:
            return create_success_response(info)
        else:
            return create_error_response(message=f"未找到股票 {code} 的信息", error_code="DATA_NOT_FOUND", suggested_action="调用 update_stock 更新数据")

    def _handle_get_stock_detail(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        include_realtime = arguments.get('include_realtime', True)
        fund_flow_days = arguments.get('fund_flow_days', 10)

        info = self.get_stock_info(code, auto_refresh=True)
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
            return create_error_response(
                message=result.get('message', '日内分析失败'),
                error_code=result.get('status', 'ANALYSIS_FAILED'),
                details=result,
                suggested_action="先更新分钟数据和日K数据",
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
            return create_error_response(message=result.get('error', '主力分析失败'), error_code="DATA_NOT_FOUND", suggested_action="先更新资金流向数据")

    def _handle_screen_market(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return self.screen_market(arguments)

    def _handle_screen_all_market(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        criteria = dict(arguments)
        criteria['limit'] = 999999
        criteria['offset'] = 0
        return self.screen_market(criteria)

    def _handle_screen_main_board(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        criteria = dict(arguments)
        criteria.setdefault('board', 'main')
        return self.screen_market(criteria)

    def _handle_start_market_sync(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        board = arguments.get('board', 'a_share')
        refresh = arguments.get('refresh', 'stale')
        days = arguments.get('days', 250)
        max_codes = arguments.get('max_codes')
        delay = arguments.get('delay', 0.2)

        job_id = f"sync_{int(time.time())}_{board}"
        now_text = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        job = {
            'job_id': job_id, 'status': 'running',
            'args': {'board': board, 'refresh': refresh, 'days': days, 'max_codes': max_codes},
            'progress': {'scanned': 0, 'refreshed': 0, 'failed': 0},
            'result': None, 'error': None,
            'created_at': now_text, 'updated_at': now_text,
        }
        self.sync_jobs.save(job)

        def _run_sync():
            try:
                summary = self.sync_market(board, refresh, max_codes, days, delay)
                self.sync_jobs.update(job_id,
                    status='completed',
                    progress=summary,
                    result=summary,
                    finished_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                )
            except Exception as e:
                self.sync_jobs.update(job_id,
                    status='failed',
                    error=str(e),
                    finished_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                )

        worker = threading.Thread(target=_run_sync, daemon=True)
        worker.start()

        return create_success_response({
            'job_id': job_id,
            'status': 'running',
            'message': f'同步任务已启动，使用 get_sync_status(job_id="{job_id}") 查询进度',
        })

    def _handle_get_sync_status(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        job_id = arguments.get('job_id')
        limit = arguments.get('limit', 20)
        offset = arguments.get('offset', 0)
        if job_id:
            job = self.sync_jobs.get(job_id)
            if job:
                return create_success_response(job)
            else:
                return create_error_response(message=f"未找到任务 {job_id}", error_code="NOT_FOUND")
        else:
            jobs = self.sync_jobs.list(limit, offset)
            return create_success_response(jobs)

    def _handle_cancel_sync(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        job_id = arguments.get('job_id')
        if not job_id:
            raise ValidationError("缺少任务ID", field='job_id')
        job = self.sync_jobs.get(job_id)
        if not job:
            return create_error_response(message=f"未找到任务 {job_id}", error_code="NOT_FOUND")
        if job.get('status') not in ('running', 'pending'):
            return create_error_response(message=f"任务 {job_id} 状态为 {job.get('status')}，无法取消", error_code="INVALID_STATE")
        self.sync_jobs.update(job_id, status='cancelled', finished_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        return create_success_response({'job_id': job_id, 'status': 'cancelled'})

    def _handle_update_minute_data(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        klt = arguments.get('klt', 5)
        days = arguments.get('days', 5)
        force = arguments.get('force', False)
        start_time = arguments.get('start_time')
        end_time = arguments.get('end_time')
        result = self._fetch_and_save_minute_data(code, klt, days, force, start_time, end_time)
        return create_success_response(result)

    def _handle_check_missing_data(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        codes = arguments.get('codes', [])
        if not codes:
            raise ValidationError("缺少股票代码列表", field='codes')
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        if not start_date or not end_date:
            raise ValidationError("缺少日期范围", field='start_date/end_date')
        result = self.check_missing_data(codes, start_date, end_date)
        return create_success_response(result)

    def _handle_get_db_stats(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return create_success_response(self.get_db_stats())

    def _handle_update_fund_flow(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        days = arguments.get('days', 100)
        force = arguments.get('force', False)

        freshness = self.check_data_freshness(code, 'fund_flow')
        if not force and freshness.get('has_data'):
            latest_date = freshness.get('latest_date')
            today = datetime.now().strftime('%Y-%m-%d')
            if latest_date == today:
                return create_success_response({'code': code, 'skipped': True, 'reason': '数据已是最新'})

        fund_flow_items = self._fetch_and_save_fund_flow(code, days)
        if not fund_flow_items:
            return create_error_response(message="未获取到资金流向数据", error_code="DATA_NOT_FOUND")
        return create_success_response({'code': code, 'saved': len(fund_flow_items)})

    handle_tool_call_handlers = None

    def handle_tool_call(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        handlers = {
            'get_current_time': self._handle_get_current_time,
            'get_provider_status': self._handle_get_provider_status,
            'get_realtime_quote': self._handle_get_realtime_quote,
            'get_realtime_quotes': self._handle_get_realtime_quotes,
            'get_daily_kline': self._handle_get_daily_kline,
            'get_minute_kline': self._handle_get_minute_kline,
            'get_valuation': self._handle_get_valuation,
            'get_fund_flow': self._handle_get_fund_flow,
            'get_stock_list': self._handle_get_stock_list,
            'get_stock_universe': self._handle_get_stock_universe,
            'get_all_stocks': self._handle_get_all_stocks,
            'get_financial_data': self._handle_get_financial_data,
            'update_stock': self._handle_update_stock,
            'update_stocks': self._handle_update_stocks,
            'update_minute_data': self._handle_update_minute_data,
            'update_fund_flow': self._handle_update_fund_flow,
            'analyze_position': self._handle_analyze_position,
            'get_technical_indicators': self._handle_get_technical_indicators,
            'get_latest_data': self._handle_get_latest_data,
            'get_stock_info': self._handle_get_stock_info,
            'get_stock_detail': self._handle_get_stock_detail,
            'analyze_intraday': self._handle_analyze_intraday,
            'analyze_main_force': self._handle_analyze_main_force,
            'screen_market': self._handle_screen_market,
            'screen_all_market': self._handle_screen_all_market,
            'screen_main_board': self._handle_screen_main_board,
            'start_market_sync': self._handle_start_market_sync,
            'get_sync_status': self._handle_get_sync_status,
            'cancel_sync': self._handle_cancel_sync,
            'check_missing_data': self._handle_check_missing_data,
            'get_db_stats': self._handle_get_db_stats,
        }

        handler = handlers.get(name)
        if not handler:
            return create_error_response(message=f"未知工具: {name}", error_code="UNKNOWN_TOOL")

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
