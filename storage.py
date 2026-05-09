import json
import sqlite3
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional


def ensure_column(cursor: Any, table: str, column: str, column_type: str) -> None:
    cursor.execute(f"PRAGMA table_info({table})")
    columns = {row[1] for row in cursor.fetchall()}
    if column not in columns:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def init_database_schema(conn: sqlite3.Connection) -> None:
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
    
    ensure_column(cursor, 'stock_technical', 'atr', 'REAL')
    ensure_column(cursor, 'stock_technical', 'obv', 'REAL')
    
    conn.commit()


def save_stock_info(conn: sqlite3.Connection, code: str, info: Dict[str, str]) -> None:
    cursor = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    cursor.execute('''
        INSERT OR REPLACE INTO stock_info 
        (code, name, market, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
    ''', (code, info.get('name', ''), info.get('market', ''), now, now))
    
    conn.commit()


def save_daily_data(conn: sqlite3.Connection, code: str, klines: List[str]) -> int:
    if not klines:
        return 0
    
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


def save_valuation_data(conn: sqlite3.Connection, code: str, valuation: Dict[str, Any]) -> None:
    cursor = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    today = datetime.now().strftime('%Y-%m-%d')
    
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


def save_technical_data(conn: sqlite3.Connection, code: str, technical_items: List[Dict[str, Any]]) -> None:
    cursor = conn.cursor()
    
    for item in technical_items:
        try:
            cursor.execute('''
                INSERT OR REPLACE INTO stock_technical
                (code, data_date, ma5, ma10, ma20, ma60, ema12, ema26, macd, macd_signal, macd_hist,
                 rsi_6, rsi_12, rsi_24, kdj_k, kdj_d, kdj_j, boll_upper, boll_mid, boll_lower,
                 atr, obv, high_52w, low_52w, position_pct, year_change_pct, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                code,
                item['data_date'],
                item['ma5'],
                item['ma10'],
                item['ma20'],
                item['ma60'],
                item['ema12'],
                item['ema26'],
                item['macd'],
                item['macd_signal'],
                item['macd_hist'],
                item['rsi_6'],
                item['rsi_12'],
                item['rsi_24'],
                item['kdj_k'],
                item['kdj_d'],
                item['kdj_j'],
                item['boll_upper'],
                item['boll_mid'],
                item['boll_lower'],
                item['atr'],
                item['obv'],
                item['high_52w'],
                item['low_52w'],
                item['position_pct'],
                item['year_change_pct'],
                item['created_at'],
            ))
        except Exception as e:
            print(f"  保存技术指标失败 {code} {item['data_date']}: {e}")
    
    conn.commit()


def get_stock_info(conn: sqlite3.Connection, code: str) -> Optional[Dict[str, Any]]:
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM stock_info WHERE code = ?', (code,))
    row = cursor.fetchone()
    
    if row:
        return {
            'code': row[0],
            'name': row[1],
            'market': row[2],
            'sector': row[3],
            'industry': row[4],
        }
    return None


def get_daily_data(
    conn: sqlite3.Connection,
    code: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0
) -> List[Dict[str, Any]]:
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
        if offset:
            sql += ' OFFSET ?'
            params.append(offset)
    elif offset:
        sql += ' LIMIT -1 OFFSET ?'
        params.append(offset)
    
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    
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


def get_valuation_data(
    conn: sqlite3.Connection,
    code: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0
) -> List[Dict[str, Any]]:
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

    if limit:
        sql += ' LIMIT ?'
        params.append(limit)
        if offset:
            sql += ' OFFSET ?'
            params.append(offset)
    elif offset:
        sql += ' LIMIT -1 OFFSET ?'
        params.append(offset)
    
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    
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


def get_technical_data(
    conn: sqlite3.Connection,
    code: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0
) -> List[Dict[str, Any]]:
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
        if offset:
            sql += ' OFFSET ?'
            params.append(offset)
    elif offset:
        sql += ' LIMIT -1 OFFSET ?'
        params.append(offset)
    
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    
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
        'atr': r['atr'],
        'obv': r['obv'],
        'high_52w': r['high_52w'],
        'low_52w': r['low_52w'],
        'position_pct': r['position_pct'],
        'year_change_pct': r['year_change_pct'],
    } for r in rows]


def get_daily_data_for_technical(conn: sqlite3.Connection, code: str) -> List[tuple]:
    cursor = conn.cursor()
    cursor.execute('''
        SELECT data_date, close, high, low, volume
        FROM stock_daily
        WHERE code = ?
        ORDER BY data_date
    ''', (code,))
    return cursor.fetchall()


def check_data_freshness(conn: sqlite3.Connection, code: str, data_type: str = 'daily', klt: Optional[int] = None) -> Dict[str, Any]:
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
            is_today = latest_date == today
            
            now = datetime.now()
            hour = now.hour
            minute = now.minute
            is_weekday = now.weekday() < 5
            is_trading_time = is_weekday and (
                (9 <= hour < 12) or (hour == 9 and minute >= 30) or
                (13 <= hour < 15) or (hour == 15 and minute == 0)
            )
            is_after_close = is_weekday and (hour > 15 or (hour == 15 and minute > 0))
            
            should_refresh = False
            if not is_today:
                should_refresh = True
            elif is_trading_time:
                should_refresh = False
            elif is_after_close and is_today:
                should_refresh = False
            
            return {
                'has_data': True,
                'earliest_date': earliest_date,
                'latest_date': latest_date,
                'row_count': row_count,
                'is_today': is_today,
                'is_trading_time': is_trading_time,
                'is_after_close': is_after_close,
                'should_refresh': should_refresh,
                'data_type': 'daily',
            }
    
    elif data_type == 'minute':
        if klt is None:
            cursor.execute('''
                SELECT MAX(data_time) FROM stock_minute WHERE code = ?
            ''', (code,))
        else:
            cursor.execute('''
                SELECT MAX(data_time) FROM stock_minute WHERE code = ? AND klt = ?
            ''', (code, klt))
        result = cursor.fetchone()
        if result and result[0]:
            latest_time = result[0]
            today = datetime.now().strftime('%Y-%m-%d')
            is_today = latest_time.startswith(today)
            
            now = datetime.now()
            hour = now.hour
            minute = now.minute
            is_weekday = now.weekday() < 5
            is_trading_time = is_weekday and (
                (9 <= hour < 12) or (hour == 9 and minute >= 30) or
                (13 <= hour < 15) or (hour == 15 and minute == 0)
            )
            
            should_refresh = False
            if not is_today:
                should_refresh = True
            elif is_trading_time:
                try:
                    latest_dt = datetime.strptime(latest_time, '%Y-%m-%d %H:%M')
                    age_minutes = (now - latest_dt).total_seconds() / 60
                    should_refresh = age_minutes > 5
                except:
                    should_refresh = True
            
            return {
                'has_data': True,
                'latest_time': latest_time,
                'is_today': is_today,
                'is_trading_time': is_trading_time,
                'should_refresh': should_refresh,
                'data_type': 'minute',
                'klt': klt,
            }
    
    elif data_type == 'fund_flow':
        cursor.execute('''
            SELECT MIN(data_date), MAX(data_date), COUNT(*) FROM stock_fund_flow WHERE code = ?
        ''', (code,))
        result = cursor.fetchone()
        if result and result[1]:
            earliest_date = result[0]
            latest_date = result[1]
            row_count = result[2]
            today = datetime.now().strftime('%Y-%m-%d')
            is_today = latest_date == today
            
            now = datetime.now()
            hour = now.hour
            is_weekday = now.weekday() < 5
            is_after_close = is_weekday and hour >= 16
            
            should_refresh = False
            if not is_today:
                should_refresh = True
            elif is_after_close and is_today:
                should_refresh = False
            
            return {
                'has_data': True,
                'earliest_date': earliest_date,
                'latest_date': latest_date,
                'row_count': row_count,
                'is_today': is_today,
                'is_after_close': is_after_close,
                'should_refresh': should_refresh,
                'data_type': 'fund_flow',
            }
    
    return {'has_data': False}


def save_fund_flow_data(conn: sqlite3.Connection, code: str, fund_flow_items: List[str]) -> int:
    cursor = conn.cursor()
    saved_count = 0
    
    for item in fund_flow_items:
        try:
            parts = item.split(',')
            if len(parts) < 13:
                continue
            
            data_date = parts[0]
            main_net_inflow = float(parts[1]) if parts[1] and parts[1] != '-' else None
            small_net_inflow = float(parts[2]) if parts[2] and parts[2] != '-' else None
            mid_net_inflow = float(parts[3]) if parts[3] and parts[3] != '-' else None
            big_net_inflow = float(parts[4]) if parts[4] and parts[4] != '-' else None
            super_net_inflow = float(parts[5]) if parts[5] and parts[5] != '-' else None
            main_net_inflow_pct = float(parts[6]) if parts[6] and parts[6] != '-' else None
            small_net_inflow_pct = float(parts[7]) if parts[7] and parts[7] != '-' else None
            mid_net_inflow_pct = float(parts[8]) if parts[8] and parts[8] != '-' else None
            big_net_inflow_pct = float(parts[9]) if parts[9] and parts[9] != '-' else None
            super_net_inflow_pct = float(parts[10]) if parts[10] and parts[10] != '-' else None
            
            cursor.execute('''
                INSERT OR REPLACE INTO stock_fund_flow 
                (code, data_date, main_net_inflow, main_net_inflow_pct, 
                 super_net_inflow, big_net_inflow, mid_net_inflow, small_net_inflow,
                 created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                code, data_date, main_net_inflow, main_net_inflow_pct,
                super_net_inflow, big_net_inflow, mid_net_inflow, small_net_inflow,
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            ))
            saved_count += 1
        except Exception as e:
            print(f"保存资金流向数据失败 {code} {item}: {e}")
            continue
    
    conn.commit()
    return saved_count


def get_fund_flow_data(
    conn: sqlite3.Connection,
    code: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0
) -> List[Dict[str, Any]]:
    cursor = conn.cursor()
    
    query = '''
        SELECT 
            code, data_date, main_net_inflow, main_net_inflow_pct,
            super_net_inflow, big_net_inflow, mid_net_inflow, small_net_inflow,
            created_at
        FROM stock_fund_flow
        WHERE code = ?
    '''
    params = [code]
    
    if start_date:
        query += ' AND data_date >= ?'
        params.append(start_date)
    
    if end_date:
        query += ' AND data_date <= ?'
        params.append(end_date)
    
    query += ' ORDER BY data_date DESC'
    
    if limit:
        query += f' LIMIT {limit} OFFSET {offset}'
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    
    results = []
    for row in rows:
        results.append({
            'code': row[0],
            'data_date': row[1],
            'main_net_inflow': row[2],
            'main_net_inflow_pct': row[3],
            'super_net_inflow': row[4],
            'big_net_inflow': row[5],
            'mid_net_inflow': row[6],
            'small_net_inflow': row[7],
            'created_at': row[8]
        })
    
    return results


def get_latest_fund_flow(conn: sqlite3.Connection, codes: List[str]) -> List[Dict[str, Any]]:
    if not codes:
        return []
    
    cursor = conn.cursor()
    placeholders = ','.join('?' * len(codes))
    
    query = f'''
        SELECT 
            s.code,
            s.name,
            f.data_date,
            f.main_net_inflow,
            f.main_net_inflow_pct,
            f.super_net_inflow,
            f.big_net_inflow,
            f.mid_net_inflow,
            f.small_net_inflow
        FROM stock_fund_flow f
        INNER JOIN (
            SELECT code, MAX(data_date) as max_date
            FROM stock_fund_flow
            WHERE code IN ({placeholders})
            GROUP BY code
        ) latest ON f.code = latest.code AND f.data_date = latest.max_date
        LEFT JOIN stock_info s ON f.code = s.code
        WHERE f.code IN ({placeholders})
    '''
    
    cursor.execute(query, codes + codes)
    rows = cursor.fetchall()
    
    results = []
    for row in rows:
        results.append({
            'code': row[0],
            'name': row[1],
            'data_date': row[2],
            'main_net_inflow': row[3],
            'main_net_inflow_pct': row[4],
            'super_net_inflow': row[5],
            'big_net_inflow': row[6],
            'mid_net_inflow': row[7],
            'small_net_inflow': row[8]
        })
    
    return results
