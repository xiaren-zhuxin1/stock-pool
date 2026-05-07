import sqlite3
import time
from datetime import datetime, timedelta, timezone
import os
import sys
import math
import builtins


def print(*args, **kwargs):
    """项目日志统一输出到 stderr，避免 MCP stdout JSON-RPC 通道被污染。"""
    kwargs.setdefault('file', sys.stderr)
    return builtins.print(*args, **kwargs)

try:
    from .api_provider import StockAPIProvider
except ImportError:
    from api_provider import StockAPIProvider

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'stock_pool.db')
SHANGHAI_TZ = timezone(timedelta(hours=8), name='Asia/Shanghai')

class StockDataPool:
    
    def __init__(self, db_path=None):
        self._sqlite_uri = False
        self._memory_keeper = None
        if db_path == ':memory:':
            self.db_path = f"file:stock_pool_memory_{id(self)}?mode=memory&cache=shared"
            self._sqlite_uri = True
            self._memory_keeper = sqlite3.connect(self.db_path, uri=True)
        else:
            self.db_path = db_path or DB_PATH
        self.api = StockAPIProvider()
        self._init_db()
    
    def _connect(self):
        return sqlite3.connect(self.db_path, uri=self._sqlite_uri)

    @staticmethod
    def get_current_time_info(now=None):
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
            'agent_rule': '每次股票分析任务开始前必须先调用 get_current_time，并以 date 作为默认分析截止日期；涉及当日数据时需结合 is_trading_time/trading_session 判断是否需要实时行情。'
        }

    def _request_includes_today(self, start_date=None, end_date=None):
        today = self.get_current_time_info()['date']
        if start_date and start_date > today:
            return False
        if end_date and end_date < today:
            return False
        return True

    def _merge_realtime_snapshot(self, item, realtime, time_info):
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
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS stock_info (
                code TEXT PRIMARY KEY,
                name TEXT,
                market TEXT,
                sector TEXT,
                industry TEXT,
                list_date TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS stock_daily (
                id INTEGER PRIMARY KEY,
                code TEXT NOT NULL,
                data_date TEXT NOT NULL,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                amount REAL,
                turnover REAL,
                change_pct REAL,
                amplitude REAL,
                created_at TEXT,
                UNIQUE(code, data_date)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS stock_valuation (
                id INTEGER PRIMARY KEY,
                code TEXT NOT NULL,
                data_date TEXT NOT NULL,
                pe_ttm REAL,
                pe_lyr REAL,
                pb REAL,
                ps_ttm REAL,
                market_cap REAL,
                circ_market_cap REAL,
                total_share REAL,
                circ_share REAL,
                data_source TEXT,
                data_quality TEXT,
                missing_fields TEXT,
                created_at TEXT,
                UNIQUE(code, data_date)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS stock_finance (
                id INTEGER PRIMARY KEY,
                code TEXT NOT NULL,
                report_date TEXT NOT NULL,
                revenue REAL,
                revenue_yoy REAL,
                net_profit REAL,
                net_profit_yoy REAL,
                gross_margin REAL,
                net_margin REAL,
                roe REAL,
                roa REAL,
                debt_ratio REAL,
                current_ratio REAL,
                created_at TEXT,
                UNIQUE(code, report_date)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS stock_fund_flow (
                id INTEGER PRIMARY KEY,
                code TEXT NOT NULL,
                data_date TEXT NOT NULL,
                main_net_inflow REAL,
                main_net_inflow_pct REAL,
                super_net_inflow REAL,
                big_net_inflow REAL,
                mid_net_inflow REAL,
                small_net_inflow REAL,
                created_at TEXT,
                UNIQUE(code, data_date)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS stock_technical (
                id INTEGER PRIMARY KEY,
                code TEXT NOT NULL,
                data_date TEXT NOT NULL,
                ma5 REAL,
                ma10 REAL,
                ma20 REAL,
                ma60 REAL,
                ema12 REAL,
                ema26 REAL,
                macd REAL,
                macd_signal REAL,
                macd_hist REAL,
                rsi_6 REAL,
                rsi_12 REAL,
                rsi_24 REAL,
                kdj_k REAL,
                kdj_d REAL,
                kdj_j REAL,
                boll_upper REAL,
                boll_mid REAL,
                boll_lower REAL,
                atr REAL,
                obv REAL,
                high_52w REAL,
                low_52w REAL,
                position_pct REAL,
                year_change_pct REAL,
                created_at TEXT,
                UNIQUE(code, data_date)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS stock_minute (
                id INTEGER PRIMARY KEY,
                code TEXT NOT NULL,
                data_time TEXT NOT NULL,
                klt INTEGER NOT NULL,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                amount REAL,
                created_at TEXT,
                UNIQUE(code, data_time, klt)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS service_sync_jobs (
                job_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                args_json TEXT,
                progress_json TEXT,
                result_json TEXT,
                error TEXT,
                created_at TEXT,
                updated_at TEXT,
                finished_at TEXT
            )
        ''')
        
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_daily_code_date ON stock_daily(code, data_date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_daily_date ON stock_daily(data_date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_valuation_code_date ON stock_valuation(code, data_date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_fund_flow_code_date ON stock_fund_flow(code, data_date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_technical_code_date ON stock_technical(code, data_date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_minute_code_time ON stock_minute(code, data_time)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_minute_time ON stock_minute(data_time)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_sync_jobs_updated ON service_sync_jobs(updated_at)')
        self._ensure_column(cursor, 'stock_technical', 'atr', 'REAL')
        self._ensure_column(cursor, 'stock_technical', 'obv', 'REAL')
        
        conn.commit()
        conn.close()
        print("服务缓存初始化完成")

    @staticmethod
    def _json_dumps(value):
        import json
        return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)

    @staticmethod
    def _json_loads(value, default=None):
        import json
        if not value:
            return {} if default is None else default
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return {} if default is None else default

    @staticmethod
    def _sync_job_from_row(row):
        if not row:
            return None
        return {
            'job_id': row[0],
            'status': row[1],
            'args': StockDataPool._json_loads(row[2]),
            'progress': StockDataPool._json_loads(row[3]),
            'result': StockDataPool._json_loads(row[4], None) if row[4] else None,
            'error': row[5],
            'created_at': row[6],
            'updated_at': row[7],
            'finished_at': row[8],
        }

    def save_sync_job(self, job):
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO service_sync_jobs
                (job_id, status, args_json, progress_json, result_json, error, created_at, updated_at, finished_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                job.get('job_id'),
                job.get('status'),
                self._json_dumps(job.get('args')),
                self._json_dumps(job.get('progress')),
                self._json_dumps(job.get('result')) if job.get('result') is not None else None,
                job.get('error'),
                job.get('created_at'),
                job.get('updated_at'),
                job.get('finished_at'),
            ))
            conn.commit()
        finally:
            conn.close()

    def update_sync_job(self, job_id, **fields):
        if not fields:
            return
        allowed = {
            'status': 'status',
            'args': 'args_json',
            'progress': 'progress_json',
            'result': 'result_json',
            'error': 'error',
            'created_at': 'created_at',
            'updated_at': 'updated_at',
            'finished_at': 'finished_at',
        }
        sets = []
        params = []
        for key, value in fields.items():
            column = allowed.get(key)
            if not column:
                continue
            sets.append(f'{column} = ?')
            if key in ('args', 'progress', 'result'):
                params.append(self._json_dumps(value) if value is not None else None)
            else:
                params.append(value)
        if not sets:
            return
        params.append(job_id)
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(f'''
                UPDATE service_sync_jobs
                SET {', '.join(sets)}
                WHERE job_id = ?
            ''', params)
            conn.commit()
        finally:
            conn.close()

    def get_sync_job(self, job_id):
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT job_id, status, args_json, progress_json, result_json, error, created_at, updated_at, finished_at
                FROM service_sync_jobs
                WHERE job_id = ?
            ''', (job_id,))
            return self._sync_job_from_row(cursor.fetchone())
        finally:
            conn.close()

    def list_sync_jobs(self, limit=20):
        limit = self._normalize_positive_int(limit, 20, 100)
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT job_id, status, args_json, progress_json, result_json, error, created_at, updated_at, finished_at
                FROM service_sync_jobs
                ORDER BY updated_at DESC
                LIMIT ?
            ''', (limit,))
            return [self._sync_job_from_row(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def mark_running_sync_jobs_interrupted(self, timestamp=None):
        timestamp = timestamp or self.get_current_time_info()['datetime']
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE service_sync_jobs
                SET status = ?, error = ?, updated_at = ?, finished_at = ?
                WHERE status IN (?, ?)
            ''', ('interrupted', '服务重启，后台同步任务已中断', timestamp, timestamp, 'running', 'cancelling'))
            conn.commit()
        finally:
            conn.close()
    
    @staticmethod
    def _ensure_column(cursor, table, column, column_type):
        cursor.execute(f"PRAGMA table_info({table})")
        columns = {row[1] for row in cursor.fetchall()}
        if column not in columns:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")
    
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
    
    def fetch_kline_data(self, code, days=250):
        klines, api_name = self.api.fetch_kline(code, days)
        if klines:
            print(f"  [API: {api_name}] 获取K线成功")
            return klines
        return None
    
    def fetch_stock_info(self, code):
        realtime, api_name = self.api.fetch_realtime(code)
        if realtime:
            return {
                'name': realtime.get('name', ''),
                'market': 'SH' if code.startswith('6') else 'SZ',
            }
        return None
    
    def fetch_valuation_data(self, code):
        realtime, api_name = self.api.fetch_realtime(code)
        if realtime:
            return realtime
        return None
    
    def get_realtime_price(self, code):
        """直接从外部行情 API 获取实时价格，不读取或写入服务缓存。"""
        realtime, api_name = self.api.fetch_realtime(code)
        if not realtime:
            return {
                'success': False,
                'code': code,
                'cache_used': False,
                'message': '实时行情 API 未返回数据'
            }
        
        realtime = dict(realtime)
        realtime.update({
            'success': True,
            'code': code,
            'api_name': api_name,
            'cache_used': False,
            'fetched_at': self.get_current_time_info()['datetime'],
        })
        return realtime
    
    def get_realtime_prices(self, codes, delay=0.2):
        """批量直接从外部行情 API 获取实时价格，不读取或写入服务缓存。"""
        results = []
        for code in codes:
            results.append(self.get_realtime_price(code))
            if delay:
                time.sleep(delay)
        return results
    
    def fetch_fund_flow(self, code):
        return None
    
    def save_stock_info(self, code, info):
        conn = self._connect()
        cursor = conn.cursor()
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        cursor.execute('''
            INSERT OR REPLACE INTO stock_info 
            (code, name, market, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (code, info.get('name', ''), info.get('market', ''), now, now))
        
        conn.commit()
        conn.close()
    
    def save_daily_data(self, code, klines):
        if not klines:
            return 0
        
        conn = self._connect()
        try:
            cursor = conn.cursor()
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            count = 0
            for kline in klines:
                data_date = 'UNKNOWN'
                try:
                    parts = kline.split(',') if isinstance(kline, str) else list(kline)
                    if len(parts) < 7:
                        raise ValueError(f'字段不足: {kline}')
                    data_date = parts[0]
                    open_price = float(parts[1])
                    close_price = float(parts[2])
                    high = float(parts[3])
                    low = float(parts[4])
                    volume = float(parts[5])
                    amount = float(parts[6])
                    
                    cursor.execute('''
                        INSERT OR REPLACE INTO stock_daily 
                        (code, data_date, open, high, low, close, volume, amount, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (code, data_date, open_price, high, low, close_price, volume, amount, now))
                    count += 1
                except (TypeError, ValueError, sqlite3.Error) as e:
                    print(f"  保存日K失败 {code} {data_date}: {e}")
            
            conn.commit()
            return count
        finally:
            conn.close()
    
    @staticmethod
    def _ema(previous, value, period):
        alpha = 2 / (period + 1)
        return value if previous is None else value * alpha + previous * (1 - alpha)
    
    @staticmethod
    def _rsi(values, period):
        if len(values) <= period:
            return None
        gains, losses = [], []
        for i in range(1, len(values)):
            diff = values[i] - values[i - 1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))
        recent_gains = gains[-period:]
        recent_losses = losses[-period:]
        avg_gain = sum(recent_gains) / period
        avg_loss = sum(recent_losses) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - 100 / (1 + rs)
    
    def calculate_technical(self, code):
        conn = self._connect()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT data_date, close, high, low, volume 
            FROM stock_daily 
            WHERE code = ? 
            ORDER BY data_date
        ''', (code,))
        
        rows = cursor.fetchall()
        
        if not rows:
            conn.close()
            return
        
        closes = [float(r[1]) for r in rows]
        highs = [float(r[2]) for r in rows]
        lows = [float(r[3]) for r in rows]
        volumes = [float(r[4] or 0) for r in rows]
        dates = [r[0] for r in rows]
        
        first_close = closes[0] if closes else None
        last_close = closes[-1] if closes else None
        year_change = (last_close - first_close) / first_close * 100 if first_close and last_close else None
        
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ema12 = None
        ema26 = None
        dea = None
        kdj_k = 50.0
        kdj_d = 50.0
        obv = 0.0
        
        for i, date in enumerate(dates):
            close = closes[i]
            high = highs[i]
            low = lows[i]
            
            if i >= 4:
                ma5 = sum(closes[max(0,i-4):i+1]) / min(5, i+1)
            else:
                ma5 = None
            
            if i >= 9:
                ma10 = sum(closes[max(0,i-9):i+1]) / min(10, i+1)
            else:
                ma10 = None
            
            if i >= 19:
                ma20 = sum(closes[max(0,i-19):i+1]) / min(20, i+1)
            else:
                ma20 = None
            
            if i >= 59:
                ma60 = sum(closes[max(0,i-59):i+1]) / min(60, i+1)
            else:
                ma60 = None
            
            window_start_52w = max(0, i - 249)
            high_52w = max(highs[window_start_52w:i+1])
            low_52w = min(lows[window_start_52w:i+1])
            position = (close - low_52w) / (high_52w - low_52w) * 100 if high_52w and low_52w and high_52w != low_52w else None
            
            ema12 = self._ema(ema12, close, 12)
            ema26 = self._ema(ema26, close, 26)
            dif = ema12 - ema26 if ema12 is not None and ema26 is not None else None
            dea = self._ema(dea, dif, 9) if dif is not None else None
            macd_hist = (dif - dea) * 2 if dif is not None and dea is not None else None
            
            rsi_6 = self._rsi(closes[:i+1], 6)
            rsi_12 = self._rsi(closes[:i+1], 12)
            rsi_24 = self._rsi(closes[:i+1], 24)
            
            kdj_start = max(0, i - 8)
            period_high = max(highs[kdj_start:i+1])
            period_low = min(lows[kdj_start:i+1])
            rsv = (close - period_low) / (period_high - period_low) * 100 if period_high != period_low else 50
            kdj_k = kdj_k * 2 / 3 + rsv / 3
            kdj_d = kdj_d * 2 / 3 + kdj_k / 3
            kdj_j = 3 * kdj_k - 2 * kdj_d
            
            boll_mid = ma20
            if i >= 19:
                boll_window = closes[i-19:i+1]
                variance = sum((x - boll_mid) ** 2 for x in boll_window) / 20
                boll_std = math.sqrt(variance)
                boll_upper = boll_mid + 2 * boll_std
                boll_lower = boll_mid - 2 * boll_std
            else:
                boll_upper = boll_lower = None
            
            tr_values = []
            atr_start = max(0, i - 13)
            for j in range(atr_start, i + 1):
                prev_close = closes[j - 1] if j > 0 else closes[j]
                tr_values.append(max(highs[j] - lows[j], abs(highs[j] - prev_close), abs(lows[j] - prev_close)))
            atr = sum(tr_values) / len(tr_values) if len(tr_values) >= 14 else None
            
            if i > 0:
                if close > closes[i - 1]:
                    obv += volumes[i]
                elif close < closes[i - 1]:
                    obv -= volumes[i]
            
            try:
                cursor.execute('''
                    INSERT OR REPLACE INTO stock_technical 
                    (code, data_date, ma5, ma10, ma20, ma60, ema12, ema26, macd, macd_signal, macd_hist,
                     rsi_6, rsi_12, rsi_24, kdj_k, kdj_d, kdj_j, boll_upper, boll_mid, boll_lower,
                     atr, obv, high_52w, low_52w, position_pct, year_change_pct, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (code, date, ma5, ma10, ma20, ma60, ema12, ema26, dif, dea, macd_hist,
                      rsi_6, rsi_12, rsi_24, kdj_k, kdj_d, kdj_j, boll_upper, boll_mid, boll_lower,
                      atr, obv, high_52w, low_52w, position, year_change, now))
            except Exception as e:
                print(f"  保存技术指标失败 {code} {date}: {e}")
        
        conn.commit()
        conn.close()
    
    def check_data_freshness(self, code, data_type='daily'):
        conn = self._connect()
        cursor = conn.cursor()
        
        if data_type == 'daily':
            cursor.execute('''
                SELECT MIN(data_date), MAX(data_date), COUNT(*) FROM stock_daily WHERE code = ?
            ''', (code,))
            result = cursor.fetchone()
            if result and result[1]:
                earliest_date = result[0]
                latest_date = result[1]
                row_count = result[2]
                today = datetime.now().strftime('%Y-%m-%d')
                conn.close()
                return {
                    'has_data': True,
                    'earliest_date': earliest_date,
                    'latest_date': latest_date,
                    'row_count': row_count,
                    'is_today': latest_date == today
                }
        
        elif data_type == 'minute':
            cursor.execute('''
                SELECT MAX(data_time) FROM stock_minute WHERE code = ?
            ''', (code,))
            result = cursor.fetchone()
            if result and result[0]:
                latest_time = result[0]
                today = datetime.now().strftime('%Y-%m-%d')
                conn.close()
                return {
                    'has_data': True,
                    'latest_time': latest_time,
                    'is_today': latest_time.startswith(today)
                }
        
        conn.close()
        return {'has_data': False}

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
    
    def update_stock(self, code, days=250, delay=1.5, force=False):
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
        cursor = conn.cursor()
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        today = datetime.now().strftime('%Y-%m-%d')
        
        import json
        missing_fields_json = json.dumps(valuation.get('missing_fields', []), ensure_ascii=False)
        
        cursor.execute('''
            INSERT OR REPLACE INTO stock_valuation 
            (code, data_date, pe_ttm, pe_lyr, pb, market_cap, circ_market_cap, 
             data_source, data_quality, missing_fields, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (code, today, valuation.get('pe_ttm'), valuation.get('pe_lyr'), 
              valuation.get('pb'), valuation.get('market_cap'), valuation.get('circ_market_cap'),
              valuation.get('data_source'), valuation.get('data_quality'), missing_fields_json, now))
        
        conn.commit()
        conn.close()
    
    def update_stocks(self, codes, days=250, delay=1.5):
        results = {}
        for code in codes:
            try:
                self.update_stock(code, days, delay)
                results[code] = 'success'
            except Exception as e:
                print(f"  更新失败: {e}")
                results[code] = str(e)
        return results
    
    def get_stock_info(self, code):
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM stock_info WHERE code = ?', (code,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                'code': row[0],
                'name': row[1],
                'market': row[2],
                'sector': row[3],
                'industry': row[4],
            }
        return None
    
    def get_daily_data(self, code, start_date=None, end_date=None, limit=None, include_realtime=True):
        limit = self._normalize_limit(limit)
        conn = self._connect()
        cursor = conn.cursor()
        
        sql = 'SELECT * FROM stock_daily WHERE code = ?'
        params = [code]
        
        if start_date:
            sql += ' AND data_date >= ?'
            params.append(start_date)
        if end_date:
            sql += ' AND data_date <= ?'
            params.append(end_date)
        
        sql += ' ORDER BY data_date DESC'
        
        if limit:
            sql += ' LIMIT ?'
            params.append(limit)
        
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        conn.close()
        
        data = [{
            'code': r[1],
            'date': r[2],
            'open': r[3],
            'high': r[4],
            'low': r[5],
            'close': r[6],
            'volume': r[7],
            'amount': r[8],
        } for r in rows]

        if include_realtime and self._request_includes_today(start_date, end_date):
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
    
    def get_valuation_data(self, code, start_date=None, end_date=None):
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        sql = 'SELECT * FROM stock_valuation WHERE code = ?'
        params = [code]
        
        if start_date:
            sql += ' AND data_date >= ?'
            params.append(start_date)
        if end_date:
            sql += ' AND data_date <= ?'
            params.append(end_date)
        
        sql += ' ORDER BY data_date DESC'
        
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        conn.close()
        
        import json
        return [{
            'code': r['code'],
            'date': r['data_date'],
            'pe_ttm': r['pe_ttm'],
            'pe_lyr': r['pe_lyr'],
            'pb': r['pb'],
            'ps_ttm': r['ps_ttm'],
            'market_cap': r['market_cap'],
            'circ_market_cap': r['circ_market_cap'],
            'data_source': r['data_source'],
            'data_quality': r['data_quality'],
            'missing_fields': json.loads(r['missing_fields']) if r['missing_fields'] else [],
        } for r in rows]
    
    def get_technical_data(self, code, start_date=None, end_date=None, limit=None):
        limit = self._normalize_limit(limit)
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        sql = 'SELECT * FROM stock_technical WHERE code = ?'
        params = [code]
        
        if start_date:
            sql += ' AND data_date >= ?'
            params.append(start_date)
        if end_date:
            sql += ' AND data_date <= ?'
            params.append(end_date)
        
        sql += ' ORDER BY data_date DESC'
        
        if limit:
            sql += ' LIMIT ?'
            params.append(limit)
        
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        conn.close()
        
        return [{
            'code': r['code'],
            'date': r['data_date'],
            'ma5': r['ma5'],
            'ma10': r['ma10'],
            'ma20': r['ma20'],
            'ma60': r['ma60'],
            'ema12': r['ema12'],
            'ema26': r['ema26'],
            'macd': r['macd'],
            'macd_signal': r['macd_signal'],
            'macd_hist': r['macd_hist'],
            'rsi_6': r['rsi_6'],
            'rsi_12': r['rsi_12'],
            'rsi_24': r['rsi_24'],
            'kdj_k': r['kdj_k'],
            'kdj_d': r['kdj_d'],
            'kdj_j': r['kdj_j'],
            'boll_upper': r['boll_upper'],
            'boll_mid': r['boll_mid'],
            'boll_lower': r['boll_lower'],
            'atr': r['atr'] if 'atr' in r.keys() else None,
            'obv': r['obv'] if 'obv' in r.keys() else None,
            'high_52w': r['high_52w'],
            'low_52w': r['low_52w'],
            'position_pct': r['position_pct'],
        } for r in rows]
    
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
        return (
            refresh == 'force'
            or (refresh == 'missing' and not freshness.get('has_data'))
            or (refresh == 'stale' and (not freshness.get('has_data') or freshness.get('latest_date') != today))
        )

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

        universe = self.api.fetch_stock_universe(board=board, limit=max_codes, page_size=100)
        codes = universe.get('codes', [])
        today = self.get_current_time_info()['date']
        summary = {
            'success': True,
            'board': board,
            'refresh': refresh,
            'universe_total': universe.get('total'),
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
            except Exception as e:
                summary['failed'] += 1
                if len(summary['failures']) < 20:
                    summary['failures'].append({'code': code, 'error': str(e)})
                print(f"  市场同步失败 {code}: {e}")

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
        has_filter = any(value is not None for value in filters.values())
        if not has_filter and not criteria.get('allow_no_filters', False):
            return {
                'success': False,
                'error': '市场筛选必须提供至少一个筛选条件，例如 position_max、pe_ttm_max、pb_max 或 market_cap_min。',
            }

        universe = self.api.fetch_stock_universe(board=board, limit=universe_limit, page_size=100)
        codes = universe.get('codes', [])

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
                    print(f"  筛选刷新失败 {code}: {e}")
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
                include_realtime=True,
                realtime_limit=realtime_limit,
                batch_size=batch_size
            )
            by_code = {item['code']: item for item in realtime_rows}
            page = [by_code.get(item['code'], item) for item in page]

        return {
            'success': True,
            'board': board,
            'criteria': {k: v for k, v in criteria.items() if v is not None},
            'universe_total': universe.get('total'),
            'universe_returned': len(codes),
            'snapshot_count': len(snapshots),
            'matched_count': len(matched),
            'returned': len(page),
            'offset': offset,
            'limit': limit,
            'refresh': refreshed,
            'skipped': {
                'no_cached_snapshot': skipped_no_snapshot,
            },
            'results': page,
            'time_context': self.get_current_time_info(),
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
    
    def check_missing_data(self, codes, start_date, end_date):
        conn = self._connect()
        cursor = conn.cursor()
        
        missing = {}
        for code in codes:
            cursor.execute('''
                SELECT COUNT(*) FROM stock_daily 
                WHERE code = ? AND data_date BETWEEN ? AND ?
            ''', (code, start_date, end_date))
            
            count = cursor.fetchone()[0]
            if count == 0:
                missing[code] = 'no_data'
        
        conn.close()
        return missing
    
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
        klines, api_name = self.api.fetch_minute_kline(code, klt, days)
        if klines:
            print(f"  [API: {api_name}] 获取{klt}分钟K线成功")
            return klines
        return None
    
    def save_minute_data(self, code, klines, klt=5):
        if not klines:
            return 0
        
        conn = self._connect()
        try:
            cursor = conn.cursor()
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            count = 0
            for kline in klines:
                data_time = 'UNKNOWN'
                try:
                    parts = kline.split(',') if isinstance(kline, str) else list(kline)
                    if len(parts) < 7:
                        raise ValueError(f'字段不足: {kline}')
                    data_time = parts[0]
                    open_price = float(parts[1])
                    close_price = float(parts[2])
                    high = float(parts[3])
                    low = float(parts[4])
                    volume = float(parts[5])
                    amount = float(parts[6])
                    
                    cursor.execute('''
                        INSERT OR REPLACE INTO stock_minute 
                        (code, data_time, klt, open, high, low, close, volume, amount, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (code, data_time, klt, open_price, high, low, close_price, volume, amount, now))
                    count += 1
                except (TypeError, ValueError, sqlite3.Error) as e:
                    print(f"  保存分钟K失败 {code} {data_time}: {e}")
            
            conn.commit()
            return count
        finally:
            conn.close()
    
    def update_minute_data(self, code, klt=5, days=5, delay=1.5, force=False):
        print(f"更新 {code} {klt}分钟K线...")
        
        if not force:
            freshness = self.check_data_freshness(code, 'minute')
            if freshness['has_data']:
                latest_time_str = freshness['latest_time']
                today = datetime.now().strftime('%Y-%m-%d')
                
                if not latest_time_str.startswith(today):
                    print(f"  数据已是历史数据（{latest_time_str}），跳过更新")
                    return
                
                now = datetime.now(SHANGHAI_TZ).replace(tzinfo=None)
                latest_time = datetime.strptime(latest_time_str, '%Y-%m-%d %H:%M')
                minutes_diff = (now - latest_time).total_seconds() / 60

                is_trading_time = self.get_current_time_info()['is_trading_time']
                
                if not is_trading_time:
                    print(f"  当前非交易时间，数据已是最新（{latest_time_str}），跳过更新")
                    return
                
                if minutes_diff < 5:
                    print(f"  数据已是最新（{latest_time_str}），跳过更新")
                    return
        
        klines = self.fetch_minute_data(code, klt, days)
        if klines:
            count = self.save_minute_data(code, klines, klt)
            print(f"  保存: {count} 条")
        
        time.sleep(delay)
    
    def get_minute_data(self, code, klt=5, start_time=None, end_time=None, limit=None):
        limit = self._normalize_limit(limit)
        conn = self._connect()
        cursor = conn.cursor()
        
        sql = 'SELECT * FROM stock_minute WHERE code = ? AND klt = ?'
        params = [code, klt]
        
        if start_time:
            sql += ' AND data_time >= ?'
            params.append(start_time)
        if end_time:
            sql += ' AND data_time <= ?'
            params.append(end_time)
        
        sql += ' ORDER BY data_time DESC'
        
        if limit:
            sql += ' LIMIT ?'
            params.append(limit)
        
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        conn.close()
        
        return [{
            'code': r[1],
            'data_time': r[2],
            'klt': r[3],
            'open': r[4],
            'high': r[5],
            'low': r[6],
            'close': r[7],
            'volume': r[8],
            'amount': r[9],
        } for r in rows]
    
    def analyze_intraday(self, code, date=None):
        if not date:
            date = datetime.now().strftime('%Y-%m-%d')
        
        data_5min = self.get_minute_data(code, klt=5, start_time=f'{date} 09:30', end_time=f'{date} 15:00')
        daily_data = self.get_daily_data(code, limit=2)
        technical_data = self.get_technical_data(code, start_date=date)
        
        if not data_5min:
            return {'success': False, 'message': '未获取到分时数据'}
        if not daily_data:
            return {'success': False, 'message': '未获取到日K数据'}
        
        data_5min.reverse()
        
        morning_data = [d for d in data_5min if '09:' in d['data_time'] or '10:' in d['data_time'] or '11:' in d['data_time']]
        afternoon_data = [d for d in data_5min if '13:' in d['data_time'] or '14:' in d['data_time'] or '15:' in d['data_time']]
        
        if not morning_data:
            return {'success': False, 'message': '未获取到上午数据'}
        
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
