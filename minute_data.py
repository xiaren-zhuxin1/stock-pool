import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple


def save_minute_data(conn: sqlite3.Connection, code: str, klines: List[str], klt: int = 5) -> int:
    if not klines:
        return 0
    
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


def get_minute_data(
    conn: sqlite3.Connection,
    code: str,
    klt: int = 5,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
    normalize_limit: Optional[callable] = None,
    normalize_offset: Optional[callable] = None,
) -> List[Dict[str, Any]]:
    if normalize_limit:
        limit = normalize_limit(limit)
    if normalize_offset:
        offset = normalize_offset(offset)
    
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
        'data_time': r[2],
        'klt': r[3],
        'open': r[4],
        'high': r[5],
        'low': r[6],
        'close': r[7],
        'volume': r[8],
        'amount': r[9],
    } for r in rows]


def minute_fetch_days_for_range(start_time: Optional[str] = None, end_time: Optional[str] = None, default: int = 5) -> int:
    if not start_time and not end_time:
        return default
    try:
        from datetime import timezone
        start = datetime.strptime((start_time or end_time)[:10], '%Y-%m-%d').date()
        today = datetime.now(timezone(timedelta(hours=8))).date()
    except (TypeError, ValueError):
        return default
    calendar_days = max(default, (today - start).days + 3)
    return min(calendar_days, 120)


def minute_kline_range(klines: Optional[List[str]]) -> Tuple[Optional[str], Optional[str]]:
    if not klines:
        return None, None
    times = []
    for kline in klines:
        parts = kline.split(',') if isinstance(kline, str) else list(kline)
        if parts:
            times.append(parts[0])
    if not times:
        return None, None
    return min(times), max(times)


def seconds_until_intraday_data(time_context: Dict[str, Any]) -> Optional[int]:
    try:
        now = datetime.fromisoformat(time_context['datetime'])
    except (KeyError, TypeError, ValueError):
        return None
    target = now.replace(hour=9, minute=35, second=0, microsecond=0)
    return max(0, int((target - now).total_seconds()))


def intraday_resolution(
    code: str,
    date: str,
    time_context: Dict[str, Any],
    required_calls: List[Dict[str, Any]],
    reason: str,
    seconds_until_func: callable = seconds_until_intraday_data,
) -> Dict[str, Any]:
    action_required = 'call_tools'
    wait_seconds = 0
    if date > time_context['date']:
        action_required = 'wait'
        wait_seconds = None
        required_calls = []
        reason = '请求日期晚于当前日期，外部行情尚不可用'
    elif date == time_context['date'] and time_context['trading_session'] == 'pre_market':
        action_required = 'wait'
        wait_seconds = seconds_until_func(time_context)
        required_calls = []
        reason = '当前尚未产生当日5分钟分时数据'
    elif date == time_context['date'] and not time_context['is_trading_day']:
        action_required = 'no_data_expected'
        wait_seconds = None
        required_calls = []
        reason = '请求日期不是A股交易日，通常不会产生分时数据'

    return {
        'action_required': action_required,
        'reason': reason,
        'wait_seconds': wait_seconds,
        'required_calls': required_calls,
        'retry_after': 'after_required_calls_complete' if action_required == 'call_tools' else 'after_wait',
        'retry_call': {
            'tool': 'analyze_intraday',
            'arguments': {'code': code, 'date': date},
        },
    }
