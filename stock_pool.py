import sqlite3
import time
from datetime import datetime, timedelta
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
        
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_daily_code_date ON stock_daily(code, data_date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_daily_date ON stock_daily(data_date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_valuation_code_date ON stock_valuation(code, data_date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_fund_flow_code_date ON stock_fund_flow(code, data_date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_technical_code_date ON stock_technical(code, data_date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_minute_code_time ON stock_minute(code, data_time)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_minute_time ON stock_minute(data_time)')
        self._ensure_column(cursor, 'stock_technical', 'atr', 'REAL')
        self._ensure_column(cursor, 'stock_technical', 'obv', 'REAL')
        
        conn.commit()
        conn.close()
        print(f"数据库初始化完成: {self.db_path}")
    
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
                SELECT MAX(data_date) FROM stock_daily WHERE code = ?
            ''', (code,))
            result = cursor.fetchone()
            if result and result[0]:
                latest_date = result[0]
                today = datetime.now().strftime('%Y-%m-%d')
                conn.close()
                return {
                    'has_data': True,
                    'latest_date': latest_date,
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
    
    def update_stock(self, code, days=250, delay=1.5, force=False):
        print(f"更新 {code}...")
        
        if not force:
            freshness = self.check_data_freshness(code, 'daily')
            if freshness['has_data'] and freshness['is_today']:
                print(f"  数据已是最新（{freshness['latest_date']}），跳过更新")
                return
        
        info = self.fetch_stock_info(code)
        if info:
            self.save_stock_info(code, info)
            print(f"  名称: {info.get('name', '')}")
        
        klines = self.fetch_kline_data(code, days)
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
    
    def get_daily_data(self, code, start_date=None, end_date=None, limit=None):
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
        
        return [{
            'code': r[1],
            'date': r[2],
            'open': r[3],
            'high': r[4],
            'low': r[5],
            'close': r[6],
            'volume': r[7],
            'amount': r[8],
        } for r in rows]
    
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
    
    def get_latest_data(self, codes):
        conn = self._connect()
        cursor = conn.cursor()
        
        import json
        results = []
        for code in codes:
            cursor.execute('''
                SELECT 
                    i.code, i.name, i.market,
                    d.data_date, d.close,
                    t.position_pct, t.high_52w, t.low_52w
                FROM stock_info i
                LEFT JOIN stock_daily d ON i.code = d.code
                LEFT JOIN stock_technical t ON i.code = t.code AND d.data_date = t.data_date
                WHERE i.code = ?
                ORDER BY d.data_date DESC
                LIMIT 1
            ''', (code,))
            
            row = cursor.fetchone()
            if row:
                cursor.execute('''
                    SELECT pe_ttm, pb, market_cap, data_source, data_quality, missing_fields
                    FROM stock_valuation
                    WHERE code = ?
                    ORDER BY data_date DESC
                    LIMIT 1
                ''', (code,))
                
                valuation_row = cursor.fetchone()
                
                results.append({
                    'code': row[0],
                    'name': row[1],
                    'market': row[2],
                    'date': row[3],
                    'close': row[4],
                    'pe_ttm': valuation_row[0] if valuation_row else None,
                    'pb': valuation_row[1] if valuation_row else None,
                    'market_cap': valuation_row[2] if valuation_row else None,
                    'data_source': valuation_row[3] if valuation_row else None,
                    'data_quality': valuation_row[4] if valuation_row else None,
                    'missing_fields': json.loads(valuation_row[5]) if valuation_row and valuation_row[5] else [],
                    'position_pct': row[5],
                    'high_52w': row[6],
                    'low_52w': row[7],
                })
        
        conn.close()
        return results
    
    def analyze_position(self, codes):
        data = self.get_latest_data(codes)
        
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
                
                now = datetime.now()
                latest_time = datetime.strptime(latest_time_str, '%Y-%m-%d %H:%M')
                minutes_diff = (now - latest_time).total_seconds() / 60
                
                current_hour = now.hour
                current_minute = now.minute
                
                is_trading_time = (
                    (9 <= current_hour < 12) or 
                    (current_hour == 12 and current_minute <= 0) or
                    (13 <= current_hour < 15) or
                    (current_hour == 15 and current_minute == 0)
                )
                
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
    
    print("\n数据库统计:")
    stats = pool.get_db_stats()
    print(f"  股票数量: {stats['stock_count']}")
    print(f"  日K线记录: {stats['daily_count']}")
    print(f"  估值记录: {stats['valuation_count']}")
    print(f"  技术指标记录: {stats['technical_count']}")
    print(f"  日期范围: {stats['date_range']}")
    
    print("\nAPI状态:")
    for name, status in pool.get_api_status().items():
        print(f"  {name}: {'可用' if status['available'] else '不可用'}")

