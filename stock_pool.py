import sqlite3
import time
from datetime import datetime, timedelta, timezone
import os
import sys
import builtins
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError):
        pass


def print(*args, **kwargs):
    """项目日志统一输出到 stderr，避免 MCP stdout JSON-RPC 通道被污染。"""
    kwargs.setdefault('file', sys.stderr)
    return builtins.print(*args, **kwargs)

try:
    from .provider_manager import ProviderManager
    from .indicators import calculate_ma, calculate_technical_indicators, ema, rsi
    from .sync_jobs import json_dumps, json_loads
    from .storage import (
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
        save_sync_job as storage_save_sync_job,
        get_sync_job as storage_get_sync_job,
        mark_running_sync_jobs_interrupted as storage_mark_running_sync_jobs_interrupted,
    )
    from .minute_data import (
        save_minute_data as minute_save_minute_data,
        get_minute_data as minute_get_minute_data,
        minute_fetch_days_for_range,
        minute_kline_range,
    )
    from .errors import logger, ValidationError, ProviderError
except ImportError:
    from provider_manager import ProviderManager
    from indicators import calculate_ma, calculate_technical_indicators, ema, rsi
    from sync_jobs import json_dumps, json_loads
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
        save_sync_job as storage_save_sync_job,
        get_sync_job as storage_get_sync_job,
        mark_running_sync_jobs_interrupted as storage_mark_running_sync_jobs_interrupted,
    )
    from minute_data import (
        save_minute_data as minute_save_minute_data,
        get_minute_data as minute_get_minute_data,
        minute_fetch_days_for_range,
        minute_kline_range,
    )
    from errors import logger, ValidationError, ProviderError
    from indicators import calculate_ma, calculate_technical_indicators, ema, rsi
    from sync_jobs import json_dumps, json_loads
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
        save_sync_job as storage_save_sync_job,
        get_sync_job as storage_get_sync_job,
        mark_running_sync_jobs_interrupted as storage_mark_running_sync_jobs_interrupted,
    )
    from minute_data import (
        save_minute_data as minute_save_minute_data,
        get_minute_data as minute_get_minute_data,
        minute_fetch_days_for_range,
        minute_kline_range,
    )

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'stock_pool.db')
SHANGHAI_TZ = timezone(timedelta(hours=8), name='Asia/Shanghai')

class StockDataPool:
    
    def __init__(self, db_path: Optional[str] = None) -> None:
        self._sqlite_uri: bool = False
        self._memory_keeper: Optional[sqlite3.Connection] = None
        if db_path == ':memory:':
            self.db_path: str = f"file:stock_pool_memory_{id(self)}?mode=memory&cache=shared"
            self._sqlite_uri = True
            self._memory_keeper = sqlite3.connect(self.db_path, uri=True)
        else:
            self.db_path = db_path or DB_PATH
        self.api = ProviderManager()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, uri=self._sqlite_uri)

    @contextmanager
    def _get_connection(self) -> Any:
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    @staticmethod
    def get_current_time_info(now: Optional[datetime] = None) -> Dict[str, Any]:
        """返回 Agent 分析前必须使用的北京时间与 A 股交易时段状态。"""
        if now is None:
            now = datetime.now(SHANGHAI_TZ)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=SHANGHAI_TZ)
        else:
            now = now.astimezone(SHANGHAI_TZ)

        minutes = now.hour * 60 + now.minute
        is_trading_day = now.weekday() < 5
        is_trading_time = is_trading_day and ((9 * 60 + 30 <= minutes <= 11 * 60 + 30) or (13 * 60 <= minutes <= 15 * 60))

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
    
    def _init_db(self):
        conn = self._connect()
        init_database_schema(conn)
        conn.close()

    @staticmethod
    def _json_dumps(value):
        return json_dumps(value)

    @staticmethod
    def _json_loads(value, default=None):
        return json_loads(value, default)

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
    
    def fetch_kline_data(self, code: str, days: int = 250) -> Optional[List[str]]:
        result = self.api.fetch_daily_kline(code, days)
        if result.success and result.data:
            print(f"  [API: {result.provider_name}] 获取K线成功")
            return result.data
        return None
    
    def fetch_stock_info(self, code: str) -> Optional[Dict[str, str]]:
        result = self.api.fetch_realtime(code)
        if result.success and result.data:
            return {
                'name': result.data.get('name', ''),
                'market': 'SH' if code.startswith('6') else 'SZ',
            }
        return None
    
    def fetch_valuation_data(self, code: str) -> Optional[Dict[str, Any]]:
        result = self.api.fetch_realtime(code)
        if result.success and result.data:
            return result.data
        return None
    
    def get_realtime_price(self, code: str) -> Dict[str, Any]:
        """直接从外部行情 API 获取实时价格，不读取或写入服务缓存。"""
        result = self.api.fetch_realtime(code)
        if not result.success or not result.data:
            return {
                'success': False,
                'code': code,
                'cache_used': False,
                'message': '实时行情 API 未返回数据'
            }
        
        realtime = dict(result.data)
        realtime.update({
            'success': True,
            'code': code,
            'api_name': result.provider_name,
            'cache_used': False,
            'fetched_at': self.get_current_time_info()['datetime'],
        })
        return realtime
    
    def get_realtime_prices(self, codes: List[str], delay: float = 0.2) -> List[Dict[str, Any]]:
        """批量直接从外部行情 API 获取实时价格，不读取或写入服务缓存。"""
        results = []
        for code in codes:
            results.append(self.get_realtime_price(code))
            if delay:
                time.sleep(delay)
        return results
    
    def fetch_fund_flow(self, code, days=100):
        result = self.api.fetch_fund_flow(code, days)
        if result.success and result.data:
            return result.data
        return None
    
    def save_fund_flow_data(self, code, fund_flow_items):
        if not fund_flow_items:
            return 0
        
        conn = self._connect()
        try:
            saved = storage_save_fund_flow_data(conn, code, fund_flow_items)
            print(f"  保存资金流向: {saved} 条")
            return saved
        finally:
            conn.close()
    
    def update_fund_flow(self, code, days=100, delay=1.5, force=False):
        freshness = self.check_data_freshness(code, 'fund_flow')
        
        if not force and freshness.get('has_data'):
            latest_date = freshness.get('latest_date')
            today = datetime.now().strftime('%Y-%m-%d')
            if latest_date == today:
                print(f"  资金流向数据已是最新（{latest_date}），跳过更新")
                return {'success': True, 'code': code, 'skipped': True, 'reason': '数据已是最新'}
        
        print(f"更新 {code} 资金流向...")
        fund_flow_items = self.fetch_fund_flow(code, days)
        
        if not fund_flow_items:
            print(f"  警告：未获取到资金流向数据")
            return {'success': False, 'code': code, 'error': 'API未返回数据'}
        
        saved = self.save_fund_flow_data(code, fund_flow_items)
        
        if delay:
            time.sleep(delay)
        
        return {'success': True, 'code': code, 'saved': saved}
    
    def get_fund_flow(self, code, start_date=None, end_date=None, limit=None, offset=0):
        conn = self._connect()
        try:
            return storage_get_fund_flow_data(conn, code, start_date, end_date, limit, offset)
        finally:
            conn.close()
    
    def analyze_main_force(self, code, days=10):
        fund_flow_data = self.get_fund_flow(code, limit=days)
        
        if not fund_flow_data:
            return {
                'code': code,
                'success': False,
                'error': '无资金流向数据'
            }
        
        main_inflows = [item['main_net_inflow'] for item in fund_flow_data if item.get('main_net_inflow')]
        main_inflow_pcts = [item['main_net_inflow_pct'] for item in fund_flow_data if item.get('main_net_inflow_pct')]
        
        if not main_inflows:
            return {
                'code': code,
                'success': False,
                'error': '无有效主力资金数据'
            }
        
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
            'code': code,
            'success': True,
            'days': len(main_inflows),
            'total_main_inflow': total_main_inflow,
            'avg_main_inflow': avg_main_inflow,
            'avg_main_inflow_pct': avg_main_inflow_pct,
            'positive_days': positive_days,
            'negative_days': negative_days,
            'consecutive_inflow': consecutive_inflow,
            'consecutive_outflow': consecutive_outflow,
            'latest_date': latest.get('data_date') if latest else None,
            'latest_main_inflow': latest.get('main_net_inflow') if latest else None,
            'latest_main_inflow_pct': latest.get('main_net_inflow_pct') if latest else None,
            'trend': 'inflow' if total_main_inflow > 0 else 'outflow',
            'strength': 'strong' if abs(avg_main_inflow_pct) > 5 else 'medium' if abs(avg_main_inflow_pct) > 2 else 'weak'
        }
    
    def save_stock_info(self, code: str, info: Dict[str, str]) -> None:
        conn = self._connect()
        try:
            storage_save_stock_info(conn, code, info)
        finally:
            conn.close()
    
    def save_daily_data(self, code: str, klines: List[str]) -> int:
        if not klines:
            return 0
        
        conn = self._connect()
        try:
            return storage_save_daily_data(conn, code, klines)
        finally:
            conn.close()
    
    @staticmethod
    def _ema(previous, value, period):
        return ema(previous, value, period)
    
    @staticmethod
    def _calculate_ma(values: List[float], window: int) -> List[Optional[float]]:
        return calculate_ma(values, window)

    @staticmethod
    def _rsi(values: List[float], period: int) -> Optional[float]:
        return rsi(values, period)
    
    def calculate_technical(self, code: str) -> None:
        conn = self._connect()
        try:
            rows = get_daily_data_for_technical(conn, code)
            if not rows:
                return

            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            technical_items = calculate_technical_indicators(rows, now)
            storage_save_technical_data(conn, code, technical_items)
        finally:
            conn.close()
    
    def check_data_freshness(self, code, data_type='daily', klt=None):
        conn = self._connect()
        try:
            return storage_check_data_freshness(conn, code, data_type, klt)
        finally:
            conn.close()

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
    
    def update_stock(self, code: str, days: int = 250, delay: float = 1.5, force: bool = False) -> None:
        print(f"更新 {code}...")

        freshness = self.check_data_freshness(code, 'daily')
        fetch_days = self._calculate_daily_fetch_days(freshness, days, force)
        if fetch_days == 0:
            print(f"  数据已是最新（{freshness['latest_date']}），跳过更新")
            return
        
        info = self.fetch_stock_info(code)
        if info:
            self.save_stock_info(code, info)
            print(f"  名称: {info.get('name', '')}")
        
        if freshness.get('has_data') and fetch_days < days:
            print(f"  使用增量刷新：缓存最新至 {freshness.get('latest_date')}，本次拉取最近 {fetch_days} 天")
        klines = self.fetch_kline_data(code, fetch_days)
        if klines:
            count = self.save_daily_data(code, klines)
            print(f"  日K线: {count} 条")
            
            self.calculate_technical(code)
            print(f"  技术指标: 计算完成")
        
        valuation = self.fetch_valuation_data(code)
        if valuation:
            self.save_valuation_data(code, valuation)
            print(f"  估值: PE={valuation.get('pe_ttm', 'N/A')}")
        
        time.sleep(delay)
    
    def save_valuation_data(self, code, valuation):
        conn = self._connect()
        try:
            storage_save_valuation_data(conn, code, valuation)
        finally:
            conn.close()
    
    def update_stocks(self, codes: List[str], days: int = 250, delay: float = 1.5) -> Dict[str, str]:
        results = {}
        for code in codes:
            try:
                self.update_stock(code, days, delay)
                results[code] = 'success'
            except (ValidationError, ProviderError) as e:
                logger.warning(f"更新股票失败 {code}: {e.message}", code=code, error_code=e.error_code)
                results[code] = e.message
            except (ConnectionError, TimeoutError) as e:
                logger.warning(f"网络错误 {code}: {e}", code=code)
                results[code] = f"网络错误: {e}"
            except Exception as e:
                logger.error(f"更新股票未预期的错误 {code}: {e}", exc_info=True, code=code)
                results[code] = str(e)
        return results
    
    def get_stock_info(self, code):
        conn = self._connect()
        try:
            return storage_get_stock_info(conn, code)
        finally:
            conn.close()
    
    def get_daily_data(self, code, start_date=None, end_date=None, limit=None, offset=0, include_realtime=True):
        limit = self._normalize_limit(limit)
        offset = self._normalize_offset(offset)
        conn = self._connect()
        try:
            data = storage_get_daily_data(conn, code, start_date, end_date, limit, offset)
        finally:
            conn.close()

        if offset == 0 and include_realtime and self._request_includes_today(start_date, end_date):
            time_info = self.get_current_time_info()
            realtime = self.get_realtime_price(code)
            if data:
                data[0] = self._merge_realtime_snapshot(data[0], realtime, time_info)
            else:
                data.append(self._merge_realtime_snapshot({
                    'code': code,
                    'date': time_info['date'],
                    'open': None,
                    'high': None,
                    'low': None,
                    'close': None,
                    'volume': None,
                    'amount': None,
                }, realtime, time_info))

        return data
    
    def get_valuation_data(self, code, start_date=None, end_date=None, limit=None, offset=0):
        limit = self._normalize_limit(limit)
        offset = self._normalize_offset(offset)
        conn = self._connect()
        try:
            return storage_get_valuation_data(conn, code, start_date, end_date, limit, offset)
        finally:
            conn.close()
    
    def get_technical_data(self, code, start_date=None, end_date=None, limit=None, offset=0):
        limit = self._normalize_limit(limit)
        offset = self._normalize_offset(offset)
        conn = self._connect()
        try:
            return storage_get_technical_data(conn, code, start_date, end_date, limit, offset)
        finally:
            conn.close()
    
    @staticmethod
    def _chunked(items, size):
        size = max(1, int(size or 1))
        for i in range(0, len(items), size):
            yield items[i:i + size]

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

        conn = self._connect()
        cursor = conn.cursor()
        
        import json
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
                    ) latest
                      ON d.code = latest.code AND d.data_date = latest.data_date
                ),
                latest_valuation AS (
                    SELECT v.*
                    FROM stock_valuation v
                    JOIN (
                        SELECT code, MAX(data_date) AS data_date
                        FROM stock_valuation
                        WHERE code IN ({placeholders})
                        GROUP BY code
                    ) latest
                      ON v.code = latest.code AND v.data_date = latest.data_date
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
                    'code': row[0],
                    'name': row[1],
                    'market': row[2],
                    'date': row[3],
                    'close': row[4],
                    'position_pct': row[5],
                    'high_52w': row[6],
                    'low_52w': row[7],
                    'pe_ttm': row[8],
                    'pb': row[9],
                    'market_cap': row[10],
                    'data_source': row[11],
                    'data_quality': row[12],
                    'missing_fields': json.loads(row[13]) if row[13] else [],
                })
        
        conn.close()

        if include_realtime:
            time_info = self.get_current_time_info()
            realtime_count = 0
            for item in results:
                if realtime_limit is not None and realtime_count >= realtime_limit:
                    item.update({
                        'realtime_used': False,
                        'realtime_skipped': True,
                        'time_context': time_info,
                    })
                    continue
                realtime = self.get_realtime_price(item['code'])
                self._merge_realtime_snapshot(item, realtime, time_info)
                realtime_count += 1

        return results

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
    def _to_number(value):
        if value is None or value == '':
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_positive_int(value, default, maximum):
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = default
        return max(0, min(value, maximum))

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

    def sync_market(self, board='a_share', refresh='stale', max_codes=None, days=250, delay=0.2,
                    progress_callback=None, should_stop=None):
        if refresh not in ('missing', 'stale', 'force'):
            refresh = 'stale'

        if max_codes is not None:
            max_codes = self._normalize_positive_int(max_codes, 0, 100000)
        days = self._normalize_positive_int(days, 250, 500) or 250
        delay = self._to_number(delay)
        if delay is None:
            delay = 0.2

        universe_result = self.api.fetch_stock_list(board=board)
        if universe_result.success and universe_result.data:
            codes = [s['code'] for s in universe_result.data]
            universe_total = len(codes)
        else:
            codes = []
            universe_total = 0
        today = self.get_current_time_info()['date']
        summary = {
            'success': True,
            'board': board,
            'refresh': refresh,
            'universe_total': universe_total,
            'total': len(codes),
            'scanned': 0,
            'refreshed': 0,
            'skipped_fresh': 0,
            'failed': 0,
            'stopped': False,
            'current_code': None,
            'failures': [],
        }

        if progress_callback:
            progress_callback(dict(summary))

        for code in codes:
            if should_stop and should_stop():
                summary['stopped'] = True
                break

            summary['current_code'] = code
            summary['scanned'] += 1
            try:
                freshness = self.check_data_freshness(code, 'daily')
                if not self._needs_daily_refresh(freshness, refresh, today):
                    summary['skipped_fresh'] += 1
                else:
                    self.update_stock(code, days=days, delay=delay, force=(refresh == 'force'))
                    summary['refreshed'] += 1
            except (ValidationError, ProviderError) as e:
                summary['failed'] += 1
                if len(summary['failures']) < 20:
                    summary['failures'].append({'code': code, 'error': e.message, 'error_code': e.error_code})
                logger.warning(f"市场同步失败 {code}: {e.message}", code=code, error_code=e.error_code)
            except (ConnectionError, TimeoutError) as e:
                summary['failed'] += 1
                if len(summary['failures']) < 20:
                    summary['failures'].append({'code': code, 'error': str(e), 'error_type': 'network'})
                logger.warning(f"网络错误 {code}: {e}", code=code)
            except Exception as e:
                summary['failed'] += 1
                if len(summary['failures']) < 20:
                    summary['failures'].append({'code': code, 'error': str(e), 'error_type': 'unexpected'})
                logger.error(f"市场同步未预期的错误 {code}: {e}", exc_info=True, code=code)

            if progress_callback:
                progress_callback(dict(summary))

        summary['current_code'] = None
        if progress_callback:
            progress_callback(dict(summary))
        return summary

    def screen_market(self, criteria=None):
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
            return {
                'success': False,
                'error': '市场筛选必须提供至少一个筛选条件，例如 position_max、pe_ttm_max、pb_max 或 market_cap_min。',
            }

        universe_result = self.api.fetch_stock_list(board=board)
        if universe_result.success and universe_result.data:
            codes = [s['code'] for s in universe_result.data]
        else:
            codes = []

        snapshots = self.get_latest_data(codes, include_realtime=False)
        matched = []

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
            'offset': offset,
            'limit': limit,
            'has_more': has_more,
            'page_info': {
                'current_offset': offset,
                'current_limit': limit,
                'total_matched': matched_count,
                'has_more': has_more,
                'next_offset': offset + limit if has_more else None,
            },
            'results': page,
        }

    def screen_main_board(self, criteria=None):
        criteria = dict(criteria or {})
        criteria.setdefault('board', 'main')
        return self.screen_market(criteria)
    
    def analyze_position(self, codes):
        data = self.get_latest_data(codes, include_realtime=False)
        
        result = {
            'low': [],
            'mid': [],
            'mid_high': [],
            'high': []
        }
        
        for row in data:
            position = row.get('position_pct')
            if position is None:
                continue
            
            item = {
                'code': row['code'],
                'name': row['name'],
                'position_pct': position,
                'close': row.get('close'),
                'high_52w': row.get('high_52w'),
                'low_52w': row.get('low_52w'),
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
    
    def get_db_stats(self):
        conn = self._connect()
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
        
        conn.close()
        
        return {
            'stock_count': stock_count,
            'daily_count': daily_count,
            'valuation_count': valuation_count,
            'technical_count': technical_count,
            'minute_count': minute_count,
            'date_range': date_range,
        }
    
    def fetch_minute_data(self, code, klt=5, days=5):
        result = self.api.fetch_minute_kline(code, klt, days)
        if result.success and result.data:
            print(f"  [API: {result.provider_name}] 获取{klt}分钟K线成功")
            return result.data
        return None

    @staticmethod
    def _minute_fetch_days_for_range(start_time=None, end_time=None, default=5):
        return minute_fetch_days_for_range(start_time, end_time, default)

    @staticmethod
    def _minute_kline_range(klines):
        return minute_kline_range(klines)
    
    def save_minute_data(self, code, klines, klt=5):
        if not klines:
            return 0
        
        conn = self._connect()
        try:
            return minute_save_minute_data(conn, code, klines, klt)
        finally:
            conn.close()
    
    def update_minute_data(self, code, klt=5, days=5, delay=1.5, force=False, start_time=None, end_time=None):
        print(f"更新 {code} {klt}分钟K线...")

        requested_range = None
        if start_time or end_time:
            requested_range = {
                'start_time': start_time,
                'end_time': end_time,
            }
            days = max(days, self._minute_fetch_days_for_range(start_time, end_time, days))
        
        if not force and not requested_range:
            freshness = self.check_data_freshness(code, 'minute', klt=klt)
            if freshness['has_data']:
                latest_time_str = freshness['latest_time']
                today = self.get_current_time_info()['date']
                
                if not latest_time_str.startswith(today):
                    print(f"  本地分钟数据停留在 {latest_time_str}，继续更新")
                else:
                    now = datetime.now(SHANGHAI_TZ).replace(tzinfo=None)
                    latest_time = datetime.strptime(latest_time_str, '%Y-%m-%d %H:%M')
                    minutes_diff = (now - latest_time).total_seconds() / 60

                    is_trading_time = self.get_current_time_info()['is_trading_time']

                    if not is_trading_time:
                        print(f"  当前非交易时间，数据已是最新（{latest_time_str}），跳过更新")
                        return

                    if minutes_diff < klt:
                        print(f"  数据已是最新（{latest_time_str}），跳过更新")
                        return {
                            'success': True,
                            'updated': False,
                            'reason': 'local_data_fresh',
                            'latest_time': latest_time_str,
                        }

        klines = self.fetch_minute_data(code, klt, days)
        fetched_start, fetched_end = self._minute_kline_range(klines)
        if klines:
            count = self.save_minute_data(code, klines, klt)
            print(f"  保存: {count} 条")
        else:
            count = 0
        
        time.sleep(delay)

        target_count = None
        target_covered = None
        resolution = None
        if requested_range:
            target_count = len(self.get_minute_data(code, klt, start_time, end_time))
            target_covered = target_count > 0
            if not target_covered:
                action_required = 'retry_later_or_use_daily_data'
                reason = '外部分时接口更新后仍未返回请求区间数据'
                if fetched_start and end_time and end_time < fetched_start:
                    action_required = 'unavailable_from_provider'
                    reason = f'外部分时接口当前最早只返回到 {fetched_start}，请求区间早于可用范围'
                elif fetched_end and start_time and start_time > fetched_end:
                    action_required = 'wait'
                    reason = f'外部分时接口当前最新只返回到 {fetched_end}，请求区间尚未可用'
                resolution = {
                    'action_required': action_required,
                    'reason': reason,
                    'retry_call': {
                        'tool': 'get_minute_data',
                        'arguments': {
                            'code': code,
                            'klt': klt,
                            'start_time': start_time,
                            'end_time': end_time,
                        },
                    } if action_required != 'unavailable_from_provider' else None,
                    'do_not_retry_update': action_required == 'unavailable_from_provider',
                }

        return {
            'success': bool(klines) and (target_covered is not False),
            'updated': bool(klines),
            'code': code,
            'klt': klt,
            'days': days,
            'saved_count': count,
            'fetched_range': {
                'start_time': fetched_start,
                'end_time': fetched_end,
            },
            'requested_range': requested_range,
            'target_count': target_count,
            'target_covered': target_covered,
            'resolution': resolution,
        }
    
    def get_minute_data(self, code, klt=5, start_time=None, end_time=None, limit=None, offset=0, auto_refresh=True):
        conn = self._connect()
        try:
            data = minute_get_minute_data(
                conn, code, klt, start_time, end_time, limit, offset,
                self._normalize_limit, self._normalize_offset
            )
        finally:
            conn.close()

        if auto_refresh and not data:
            time_context = self.get_current_time_info()
            is_trading_time = time_context.get('is_trading_time', False)
            is_trading_day = time_context.get('is_trading_day', False)

            if is_trading_day and is_trading_time:
                try:
                    days = self._minute_fetch_days_for_range(start_time, end_time, 2)
                    self.update_minute_data(code, klt=klt, days=days, delay=0, force=True, start_time=start_time, end_time=end_time)
                    conn = self._connect()
                    try:
                        data = minute_get_minute_data(
                            conn, code, klt, start_time, end_time, limit, offset,
                            self._normalize_limit, self._normalize_offset
                        )
                    finally:
                        conn.close()
                except Exception:
                    pass

        return data

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
        high_volume = sum([d['volume'] for d in morning_data[:morning_data.index([d for d in morning_data if d['high'] == high_price][0])+1]])
        
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
            
            if close_price > ma5:
                factors['技术面'] += 25
            if close_price > ma10:
                factors['技术面'] += 25
            if close_price > ma20:
                factors['技术面'] += 25
            if close_price < ma60:
                factors['技术面'] -= 20
        
        if first_30min_vol > last_30min_vol * 1.5:
            factors['量能'] = 20
        elif first_30min_vol > last_30min_vol:
            factors['量能'] = 40
        else:
            factors['量能'] = 50
        
        if close_position > 70:
            factors['位置'] = 60
        elif close_position > 50:
            factors['位置'] = 50
        elif close_position > 30:
            factors['位置'] = 40
        else:
            factors['位置'] = 30
        
        if pullback_pct < 1.5:
            factors['形态'] = 70
        elif pullback_pct < 3:
            factors['形态'] = 50
        else:
            factors['形态'] = 30
        
        total_score = sum(factors.values()) / 4
        up_prob = min(80, max(20, total_score * 0.8))
        down_prob = min(80, max(20, (100 - total_score) * 0.8))
        range_prob = 100 - up_prob - down_prob
        
        return {
            'success': True,
            'code': code,
            'date': date,
            'current_date': time_context['date'],
            'morning_review': {
                'open_price': round(open_price, 2),
                'prev_close': round(prev_close, 2),
                'gap_pct': round(gap_pct, 2),
                'high_price': round(high_price, 2),
                'high_time': high_time.split()[1] if ' ' in high_time else high_time,
                'low_price': round(low_price, 2),
                'low_time': low_time.split()[1] if ' ' in low_time else low_time,
                'close_price': round(close_price, 2),
                'pullback_pct': round(pullback_pct, 2),
                'close_position': round(close_position, 1),
                'total_volume': round(total_volume / 10000, 0),
                'first_30min_vol_pct': round(first_30min_vol / total_volume * 100, 1) if total_volume else 0,
                'last_30min_vol_pct': round(last_30min_vol / total_volume * 100, 1) if total_volume else 0
            },
            'afternoon_prediction': {
                'factors': factors,
                'total_score': round(total_score, 1),
                'up_prob': round(up_prob, 1),
                'range_prob': round(range_prob, 1),
                'down_prob': round(down_prob, 1)
            },
            'scenarios': [
                {
                    'name': '震荡下行',
                    'prob': round(down_prob * 0.6, 1),
                    'condition': '跌破19.60元',
                    'target': '19.37-19.60元'
                },
                {
                    'name': '快速下跌',
                    'prob': round(down_prob * 0.4, 1),
                    'condition': '放量跌破19.60元',
                    'target': '19.20-19.37元'
                },
                {
                    'name': '窄幅震荡',
                    'prob': round(range_prob, 1),
                    'condition': '成交量萎缩',
                    'target': '19.60-20.00元'
                },
                {
                    'name': '震荡上行',
                    'prob': round(up_prob * 0.7, 1),
                    'condition': '温和放量，突破20.00元',
                    'target': '20.00-20.35元'
                },
                {
                    'name': '强势突破',
                    'prob': round(up_prob * 0.3, 1),
                    'condition': '放量突破20.35元',
                    'target': '20.50-20.65元'
                }
            ]
        }
    
    def get_api_status(self):
        return self.api.get_api_status()

    def save_sync_job(self, job: Dict[str, Any]) -> None:
        with self._get_connection() as conn:
            storage_save_sync_job(conn, job)

    def get_sync_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            return storage_get_sync_job(conn, job_id)

    def mark_running_sync_jobs_interrupted(self, timestamp: str) -> int:
        with self._get_connection() as conn:
            return storage_mark_running_sync_jobs_interrupted(conn, timestamp)


if __name__ == '__main__':
    pool = StockDataPool()
    
    print("\n缓存统计:")
    stats = pool.get_db_stats()
    print(f"  股票数量: {stats['stock_count']}")
    print(f"  日K线记录: {stats['daily_count']}")
    print(f"  估值记录: {stats['valuation_count']}")
    print(f"  技术指标记录: {stats['technical_count']}")
    print(f"  日期范围: {stats['date_range']}")
    
    print("\nAPI状态:")
    for name, status in pool.get_api_status().items():
        print(f"  {name}: {'可用' if status['available'] else '不可用'}")
