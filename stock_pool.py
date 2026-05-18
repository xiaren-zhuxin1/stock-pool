"""
StockDataPool v3 - 实时优先 + 会话缓存 + 多源降级

核心原则：
1. 实时优先 - 每次会话重新获取，无脏数据
2. 按需历史 - 需要时才获取历史K线
3. 会话缓存 - 同一会话内避免重复请求
4. 多源降级 - 主数据源限流时自动切换
5. 部分成功 - 部分失败时返回可用结果
6. 限流控制 - 内置请求限流器
"""
import time
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Tuple
from collections import OrderedDict

from provider_manager import ProviderManager
from indicators import (
    calculate_ma, calculate_technical_indicators,
    calculate_returns, calculate_volume_analysis,
    generate_technical_signals, calculate_support_resistance
)
from errors import ValidationError, logger

SHANGHAI_TZ = timezone(timedelta(hours=8), name='Asia/Shanghai')


class RateLimiter:
    """请求限流器"""
    
    def __init__(self, max_requests: int = 30, window: int = 60):
        self.max_requests = max_requests
        self.window = window
        self.requests = []
        self._lock = threading.Lock()
    
    def acquire(self, wait: bool = True) -> Tuple[bool, float]:
        """获取请求许可，返回 (是否可以继续, 需要等待的秒数)"""
        with self._lock:
            now = time.time()
            self.requests = [t for t in self.requests if now - t < self.window]
            
            if len(self.requests) >= self.max_requests:
                wait_time = self.window - (now - self.requests[0]) + 0.1
                if wait:
                    time.sleep(wait_time)
                    self.requests = [t for t in self.requests if time.time() - t < self.window]
                else:
                    return False, wait_time
            
            self.requests.append(time.time())
            return True, 0


class SessionCache:
    """会话级LRU缓存 - 缓存持久存在，由agent决定何时清理"""
    
    def __init__(self, max_size: int = 500):
        self.max_size = max_size
        self._cache = OrderedDict()
        self._timestamps = {}
        self._lock = threading.Lock()
    
    def get(self, key: str, data_type: str = 'default') -> Optional[Any]:
        with self._lock:
            if key not in self._cache:
                return None
            
            self._cache.move_to_end(key)
            return self._cache[key]
    
    def set(self, key: str, value: Any, data_type: str = 'default'):
        with self._lock:
            if key in self._cache:
                del self._cache[key]
            
            self._cache[key] = value
            self._timestamps[key] = time.time()
            
            while len(self._cache) > self.max_size:
                oldest = next(iter(self._cache))
                del self._cache[oldest]
                if oldest in self._timestamps:
                    del self._timestamps[oldest]
    
    def clear(self, pattern: str = None):
        """清理缓存，可指定模式匹配"""
        with self._lock:
            if pattern is None:
                self._cache.clear()
                self._timestamps.clear()
            else:
                keys_to_delete = [k for k in self._cache if pattern in k]
                for k in keys_to_delete:
                    del self._cache[k]
                    if k in self._timestamps:
                        del self._timestamps[k]
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        with self._lock:
            return {
                'total_items': len(self._cache),
                'max_size': self.max_size,
                'keys': list(self._cache.keys())[:20],
            }


class StockDataPool:
    """实时优先的股票数据池，支持会话缓存和多源降级"""
    
    PROVIDER_PRIORITY = {
        'realtime': ['eastmoney', 'sina', 'tencent'],
        'kline': ['eastmoney'],
        'minute': ['eastmoney'],
        'fund_flow': ['eastmoney'],
        'financial': ['eastmoney'],
        'stock_list': ['eastmoney'],
    }
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.api = ProviderManager(self.config.get('providers', {}))
        self.cache = SessionCache()
        self.rate_limiter = RateLimiter(
            max_requests=self.config.get('rate_limit', 30),
            window=60
        )
        logger.info("StockDataPool v3 初始化完成（实时优先+会话缓存）")
    
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
    
    def _fetch_with_fallback(self, data_type: str, fetch_func, *args, **kwargs) -> Any:
        """多数据源降级获取"""
        providers = self.PROVIDER_PRIORITY.get(data_type, ['eastmoney'])
        last_error = None
        
        for provider_name in providers:
            try:
                result = fetch_func(provider_name, *args, **kwargs)
                if result and result.success:
                    return result
                if result and result.error:
                    last_error = result.error.message
            except Exception as e:
                last_error = str(e)
                logger.warning(f"{provider_name} 获取 {data_type} 失败: {e}")
        
        return None
    
    def _validate_kline(self, klines: List[Dict]) -> Tuple[bool, str]:
        """验证K线数据有效性"""
        if not klines:
            return False, "K线数据为空"
        
        if len(klines) < 10:
            return False, f"K线数据不足: 仅{len(klines)}条"
        
        for i, item in enumerate(klines[:5]):
            required = ['open', 'high', 'low', 'close']
            missing = [k for k in required if k not in item or item[k] is None]
            if missing:
                return False, f"第{i}条数据缺少字段: {missing}"
            
            try:
                high = float(item['high'])
                low = float(item['low'])
                if high < low:
                    return False, f"第{i}条数据异常: 最高价{high} < 最低价{low}"
            except (ValueError, TypeError):
                return False, f"第{i}条数据格式错误"
        
        return True, ""

    def _enrich_quote_data(self, code: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Fill missing valuation fields from providers that support valuation."""
        enriched = dict(data or {})
        valuation_fields = ('pe_ttm', 'pb', 'market_cap', 'circ_market_cap')
        if all(enriched.get(field) not in (None, '', '-') for field in valuation_fields):
            return enriched

        result = self.api.fetch_valuation(code)
        if not result.success or not result.data:
            return enriched

        for field in valuation_fields:
            if enriched.get(field) in (None, '', '-'):
                value = result.data.get(field)
                if value not in (None, '', '-'):
                    enriched[field] = value

        if result.provider_name:
            enriched['valuation_provider'] = result.provider_name

        return enriched

    def _calculate_52w_position(
        self,
        code: str,
        price: Optional[float] = None,
        klines: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Calculate 52-week high/low from daily K-line data."""
        if klines is None:
            kline_result = self.get_daily_kline(code, days=250)
            if not kline_result.get('success'):
                return {'high_52w': None, 'low_52w': None, 'position_pct': None}
            klines = kline_result.get('klines', [])

        rows = sorted(klines, key=lambda item: item.get('date', ''))[-250:]
        highs = []
        lows = []
        for row in rows:
            try:
                high = row.get('high')
                low = row.get('low')
                if high is not None:
                    highs.append(float(high))
                if low is not None:
                    lows.append(float(low))
            except (TypeError, ValueError):
                continue

        high_52w = max(highs) if highs else None
        low_52w = min(lows) if lows else None

        position_pct = None
        try:
            numeric_price = float(price) if price is not None else None
        except (TypeError, ValueError):
            numeric_price = None

        if high_52w and low_52w and numeric_price is not None and high_52w > low_52w:
            position_pct = round((numeric_price - low_52w) / (high_52w - low_52w) * 100, 2)

        return {
            'high_52w': high_52w,
            'low_52w': low_52w,
            'position_pct': position_pct,
        }

    def get_realtime_quotes(self, codes: List[str], delay: float = 0.2) -> Dict[str, Any]:
        """批量获取实时行情（部分成功机制）"""
        results = []
        failed = []
        
        for code in codes:
            cache_key = f"realtime_{code}"
            cached = self.cache.get(cache_key, 'realtime')
            
            if cached:
                results.append(cached)
                continue
            
            self.rate_limiter.acquire()
            result = self.api.fetch_realtime(code)
            
            if result.success and result.data:
                data = {
                    'code': code,
                    'success': True,
                    **result.data,
                    'provider': result.provider_name,
                }
                results.append(data)
            else:
                err_msg = result.error.message if result.error else '未知错误'
                failed.append({'code': code, 'error': err_msg})
            
            if delay > 0:
                time.sleep(delay)
        
        return {
            'success': len(results) > 0,
            'results': results,
            'failed': failed,
            'partial': len(failed) > 0 and len(results) > 0,
            'total': len(codes),
            'success_count': len(results),
            'failed_count': len(failed),
        }
    
    def get_daily_kline(self, code: str, days: int = 250,
                        start_date: Optional[str] = None,
                        end_date: Optional[str] = None) -> Dict[str, Any]:
        """获取日K线数据"""
        cache_key = f"kline_{code}_{days}"
        cached = self.cache.get(cache_key, 'kline')
        
        if cached:
            klines = cached
        else:
            self.rate_limiter.acquire()
            result = self.api.fetch_daily_kline(code, days)
            
            if not result.success or not result.data:
                return {
                    'success': False,
                    'code': code,
                    'error': result.error.message if result and result.error else '获取K线失败',
                }
            
            klines = []
            for line in result.data:
                if isinstance(line, str):
                    parts = line.split(',')
                    if len(parts) >= 7:
                        klines.append({
                            'date': parts[0],
                            'open': float(parts[1]) if parts[1] else None,
                            'close': float(parts[2]) if parts[2] else None,
                            'high': float(parts[3]) if parts[3] else None,
                            'low': float(parts[4]) if parts[4] else None,
                            'volume': float(parts[5]) if parts[5] else None,
                            'amount': float(parts[6]) if parts[6] else None,
                        })
                elif isinstance(line, dict):
                    klines.append(line)
            
            valid, msg = self._validate_kline(klines)
            if not valid:
                return {'success': False, 'code': code, 'error': f'K线数据无效: {msg}'}
            
            self.cache.set(cache_key, klines, 'kline')
        
        if start_date:
            klines = [k for k in klines if k.get('date', '') >= start_date]
        if end_date:
            klines = [k for k in klines if k.get('date', '') <= end_date]
        
        return {
            'success': True,
            'code': code,
            'count': len(klines),
            'klines': klines,
        }
    
    def get_minute_kline(self, code: str, klt: int = 5, days: int = 5) -> Dict[str, Any]:
        """获取分钟K线数据"""
        cache_key = f"minute_{code}_{klt}_{days}"
        cached = self.cache.get(cache_key, 'minute')
        
        if cached:
            return {'success': True, 'code': code, 'count': len(cached), 'klines': cached}
        
        self.rate_limiter.acquire()
        result = self.api.fetch_minute_kline(
            code, klt, days,
            providers=self.PROVIDER_PRIORITY.get('minute')
        )
        
        if not result.success or not result.data:
            return {
                'success': False,
                'code': code,
                'error': result.error.message if result and result.error else '获取分钟K线失败',
            }
        
        klines = []
        for line in result.data:
            if isinstance(line, str):
                parts = line.split(',')
                if len(parts) >= 7:
                    klines.append({
                        'datetime': parts[0],
                        'open': float(parts[1]) if parts[1] else None,
                        'close': float(parts[2]) if parts[2] else None,
                        'high': float(parts[3]) if parts[3] else None,
                        'low': float(parts[4]) if parts[4] else None,
                        'volume': float(parts[5]) if parts[5] else None,
                        'amount': float(parts[6]) if parts[6] else None,
                    })
            elif isinstance(line, dict):
                klines.append(line)
        
        self.cache.set(cache_key, klines, 'minute')
        
        return {'success': True, 'code': code, 'count': len(klines), 'klines': klines}
    
    def get_fund_flow(self, code: str, days: int = 10) -> Dict[str, Any]:
        """获取资金流向数据"""
        cache_key = f"fund_flow_{code}_{days}"
        cached = self.cache.get(cache_key, 'fund_flow')
        
        if cached:
            return {'success': True, 'code': code, 'count': len(cached), 'data': cached}
        
        self.rate_limiter.acquire()
        result = self.api.fetch_fund_flow(code, days)
        
        if not result.success or not result.data:
            return {
                'success': False,
                'code': code,
                'error': result.error.message if result and result.error else '获取资金流向失败',
            }
        
        self.cache.set(cache_key, result.data, 'fund_flow')
        
        return {'success': True, 'code': code, 'count': len(result.data), 'data': result.data}
    
    def analyze_main_force(self, code: str, days: int = 10) -> Dict[str, Any]:
        """分析主力资金"""
        fund_flow_result = self.get_fund_flow(code, days)
        
        if not fund_flow_result.get('success'):
            return {
                'code': code,
                'success': False,
                'error': fund_flow_result.get('error', '无资金流向数据')
            }
        
        fund_flow_data = fund_flow_result.get('data', [])
        
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
    
    def get_stock_list(self, board: str = 'a_share') -> Dict[str, Any]:
        """获取股票列表"""
        cache_key = f"stock_list_{board}"
        cached = self.cache.get(cache_key, 'stock_list')
        
        if cached:
            return {'success': True, 'board': board, 'count': len(cached), 'stocks': cached}
        
        self.rate_limiter.acquire()
        result = self.api.fetch_stock_list(board)
        
        if not result.success or not result.data:
            return {
                'success': False,
                'board': board,
                'error': result.error.message if result and result.error else '获取股票列表失败',
            }
        
        self.cache.set(cache_key, result.data, 'stock_list')
        
        return {'success': True, 'board': board, 'count': len(result.data), 'stocks': result.data}
    
    def get_financial_data(self, code: str, report_type: str = 'income') -> Dict[str, Any]:
        """获取财务数据"""
        cache_key = f"financial_{code}_{report_type}"
        cached = self.cache.get(cache_key, 'financial')
        
        if cached:
            return {'success': True, 'code': code, 'report_type': report_type, 'data': cached}
        
        self.rate_limiter.acquire()
        result = self.api.fetch_financial(code, report_type)
        
        if not result.success or not result.data:
            return {
                'success': False,
                'code': code,
                'error': result.error.message if result and result.error else '获取财务数据失败',
            }
        
        self.cache.set(cache_key, result.data, 'financial')
        
        return {'success': True, 'code': code, 'report_type': report_type, 'data': result.data}
    
    def analyze_position(self, codes: List[str]) -> Dict[str, Any]:
        """分析52周位置（部分成功机制）"""
        results = []
        failed = []
        
        for code in codes:
            cache_key = f"position_{code}"
            cached = self.cache.get(cache_key, 'position')
            
            if cached:
                results.append(cached)
                continue
            
            self.rate_limiter.acquire()
            result = self.api.fetch_realtime(code)
            
            if result.success and result.data:
                data = result.data
                price = data.get('price')
                position = self._calculate_52w_position(code, price)
                high_52w = position.get('high_52w') or data.get('high_52w')
                low_52w = position.get('low_52w') or data.get('low_52w')
                position_pct = position.get('position_pct')
                if position_pct is None and high_52w and low_52w and price and high_52w > low_52w:
                    position_pct = round((price - low_52w) / (high_52w - low_52w) * 100, 2)
                
                pos_data = {
                    'code': code,
                    'name': data.get('name'),
                    'price': price,
                    'high_52w': high_52w,
                    'low_52w': low_52w,
                    'position_pct': position_pct,
                }
                results.append(pos_data)
                self.cache.set(cache_key, pos_data, 'position')
            else:
                failed.append({
                    'code': code,
                    'error': result.error.message if result.error else '获取失败',
                })
        
        return {
            'success': len(results) > 0,
            'results': results,
            'failed': failed,
            'partial': len(failed) > 0 and len(results) > 0,
            'total': len(codes),
            'success_count': len(results),
            'failed_count': len(failed),
        }
    
    def analyze_intraday(self, code: str, date: Optional[str] = None) -> Dict[str, Any]:
        """日内走势分析"""
        time_info = self.get_current_time_info()
        
        if not time_info['is_trading_time']:
            return {
                'success': False,
                'error': {
                    'code': 'NON_TRADING_TIME',
                    'message': '当前非交易时间，无法进行日内分析',
                    'severity': 'warning',
                    'recoverable': True,
                    'suggested_action': '请在交易时间（9:30-11:30, 13:00-15:00）重试',
                }
            }
        
        minute_result = self.get_minute_kline(code, klt=1, days=1)
        if not minute_result.get('success'):
            return {
                'success': False,
                'error': {
                    'code': 'NO_MINUTE_DATA',
                    'message': minute_result.get('error', '未获取到分钟数据'),
                    'severity': 'error',
                    'recoverable': True,
                }
            }
        
        minute_data = minute_result.get('klines', [])
        prices = [m['close'] for m in minute_data if m.get('close')]
        volumes = [m['volume'] for m in minute_data if m.get('volume')]
        
        if not prices:
            return {
                'success': False,
                'error': {
                    'code': 'INVALID_DATA',
                    'message': '分钟数据无效',
                    'severity': 'error',
                    'recoverable': True,
                }
            }
        
        return {
            'success': True,
            'code': code,
            'date': date or time_info['date'],
            'open': prices[0],
            'high': max(prices),
            'low': min(prices),
            'close': prices[-1],
            'avg_price': sum(prices) / len(prices),
            'total_volume': sum(volumes),
            'bars_count': len(prices),
            'amplitude': round((max(prices) - min(prices)) / prices[0] * 100, 2) if prices[0] else None,
        }
    
    def analyze_stock(self, code: str, fund_flow_days: int = 10) -> Dict[str, Any]:
        """综合分析股票"""
        realtime_result = self.api.fetch_realtime(code)
        if not realtime_result.success or not realtime_result.data:
            return {'success': False, 'code': code, 'error': '无法获取股票数据'}
        
        realtime = self._enrich_quote_data(code, realtime_result.data)
        
        kline_result = self.get_daily_kline(code, days=250)
        if not kline_result.get('success'):
            return {'success': False, 'code': code, 'error': kline_result.get('error', '无法获取K线数据')}
        
        kline_data = kline_result.get('klines', [])
        if len(kline_data) < 100:
            return {'success': False, 'code': code, 'error': f'K线数据不足: 仅{len(kline_data)}条'}
        
        kline_sorted = sorted(kline_data, key=lambda x: x.get('date', ''))
        closes = [float(r['close']) for r in kline_sorted if r.get('close')]
        highs = [float(r['high']) for r in kline_sorted if r.get('high')]
        lows = [float(r['low']) for r in kline_sorted if r.get('low')]
        volumes = [float(r.get('volume') or 0) for r in kline_sorted]
        
        rows = [(k.get('date'), k.get('open'), k.get('high'), k.get('low'),
                 k.get('close'), k.get('volume')) for k in kline_sorted]
        technical_indicators = calculate_technical_indicators(rows, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        
        tech_signals = generate_technical_signals(technical_indicators) if technical_indicators else {'signals': [], 'overall': 'neutral', 'score': 50}
        
        returns_analysis = calculate_returns(closes)
        volume_analysis = calculate_volume_analysis(volumes, closes)
        support_resistance = calculate_support_resistance(highs, lows, closes)
        
        fund_flow_result = self.analyze_main_force(code, fund_flow_days)
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
        
        pe_ttm = realtime.get('pe_ttm')
        pb = realtime.get('pb')
        market_cap = realtime.get('market_cap')
        
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
        
        return {
            'success': True,
            'code': code,
            'name': realtime.get('name'),
            'price': realtime.get('price'),
            'technical_signals': tech_signals,
            'risk_metrics': returns_analysis,
            'volume_analysis': volume_analysis,
            'support_resistance': support_resistance,
            'fund_flow': fund_flow_summary,
            'valuation': {
                'pe_ttm': pe_ttm,
                'pb': pb,
                'market_cap_yi': round(market_cap / 100000000, 2) if market_cap else None,
                'valuation_level': valuation_level,
            },
        }
    
    def get_latest_data(self, codes: List[str]) -> Dict[str, Any]:
        """获取最新综合数据（部分成功机制）"""
        results = []
        failed = []
        
        for code in codes:
            self.rate_limiter.acquire()
            result = self.api.fetch_realtime(code)
            
            if result.success and result.data:
                data = self._enrich_quote_data(code, result.data)
                price = data.get('price')
                position = self._calculate_52w_position(code, price)
                high_52w = position.get('high_52w') or data.get('high_52w')
                low_52w = position.get('low_52w') or data.get('low_52w')
                position_pct = position.get('position_pct')
                if position_pct is None and high_52w and low_52w and price and high_52w > low_52w:
                    position_pct = round((price - low_52w) / (high_52w - low_52w) * 100, 2)
                
                results.append({
                    'code': code,
                    'name': data.get('name'),
                    'market': 'SH' if code.startswith('6') else 'BJ' if code.startswith(('4', '8')) else 'SZ',
                    'price': price,
                    'change_pct': data.get('change_pct'),
                    'volume': data.get('volume'),
                    'amount': data.get('amount'),
                    'pe_ttm': data.get('pe_ttm'),
                    'pb': data.get('pb'),
                    'market_cap': data.get('market_cap'),
                    'high_52w': high_52w,
                    'low_52w': low_52w,
                    'position_pct': position_pct,
                })
            else:
                failed.append({
                    'code': code,
                    'error': result.error.message if result.error else '获取失败',
                })
        
        return {
            'success': len(results) > 0,
            'results': results,
            'failed': failed,
            'partial': len(failed) > 0 and len(results) > 0,
            'total': len(codes),
            'success_count': len(results),
            'failed_count': len(failed),
        }
    
    def get_stock_detail(self, code: str, fund_flow_days: int = 10) -> Dict[str, Any]:
        """获取股票详情"""
        realtime_result = self.api.fetch_realtime(code)
        if not realtime_result.success or not realtime_result.data:
            return {'success': False, 'code': code, 'error': '无法获取股票信息'}
        
        realtime = realtime_result.data
        latest_result = self.get_latest_data([code])
        latest = latest_result.get('results', [None])[0] if latest_result.get('success') else None
        fund_flow = self.analyze_main_force(code, fund_flow_days)
        
        result = {
            'success': True,
            'code': code,
            'info': {
                'name': realtime.get('name'),
                'market': 'SH' if code.startswith('6') else 'BJ' if code.startswith(('4', '8')) else 'SZ',
            },
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
        
        return result
    
    def screen_market(self, criteria: Dict[str, Any]) -> Dict[str, Any]:
        """市场筛选"""
        board = criteria.get('board', 'a_share')
        limit = min(criteria.get('limit', 50), 100)
        offset = criteria.get('offset', 0)
        
        filters = {
            'pe_ttm_min': criteria.get('pe_ttm_min'),
            'pe_ttm_max': criteria.get('pe_ttm_max'),
            'pb_min': criteria.get('pb_min'),
            'pb_max': criteria.get('pb_max'),
            'market_cap_min': criteria.get('market_cap_min'),
            'market_cap_max': criteria.get('market_cap_max'),
            'position_min': criteria.get('position_min'),
            'position_max': criteria.get('position_max'),
        }
        
        if filters['position_min'] is not None and 0 < filters['position_min'] <= 1:
            filters['position_min'] *= 100
        if filters['position_max'] is not None and 0 < filters['position_max'] <= 1:
            filters['position_max'] *= 100
        
        has_filter = any(v is not None for v in filters.values())
        if not has_filter:
            return {'success': False, 'error': '市场筛选必须提供至少一个筛选条件'}
        
        stock_list_result = self.get_stock_list(board)
        if not stock_list_result.get('success'):
            return {'success': False, 'error': stock_list_result.get('error', '获取股票列表失败')}
        
        stocks = stock_list_result.get('stocks', [])
        
        need_position = filters['position_min'] is not None or filters['position_max'] is not None
        
        matched = []
        for stock in stocks:
            pe = stock.get('pe_ttm')
            pb = stock.get('pb')
            market_cap = stock.get('market_cap')
            
            if filters['pe_ttm_min'] is not None or filters['pe_ttm_max'] is not None:
                if pe is None or pe < 0:
                    continue
                if filters['pe_ttm_min'] is not None and pe < filters['pe_ttm_min']:
                    continue
                if filters['pe_ttm_max'] is not None and pe > filters['pe_ttm_max']:
                    continue
            
            if filters['pb_min'] is not None and (pb is None or pb < filters['pb_min']):
                continue
            if filters['pb_max'] is not None and (pb is None or pb > filters['pb_max']):
                continue
            
            if filters['market_cap_min'] is not None and (market_cap is None or market_cap < filters['market_cap_min'] * 1e8):
                continue
            if filters['market_cap_max'] is not None and (market_cap is None or market_cap > filters['market_cap_max'] * 1e8):
                continue
            
            matched.append(stock)
        
        if need_position and matched:
            codes = [s['code'] for s in matched[:50]]
            position_result = self.analyze_position(codes)
            
            if position_result.get('success'):
                position_map = {p['code']: p.get('position_pct') for p in position_result.get('results', [])}
                
                filtered = []
                for stock in matched:
                    pos = position_map.get(stock['code'])
                    if pos is None:
                        continue
                    if filters['position_min'] is not None and pos < filters['position_min']:
                        continue
                    if filters['position_max'] is not None and pos > filters['position_max']:
                        continue
                    stock['position_pct'] = pos
                    filtered.append(stock)
                matched = filtered
        
        sort_by = criteria.get('sort_by', 'pe_ttm')
        if sort_by not in ('pe_ttm', 'pb', 'market_cap', 'position_pct'):
            sort_by = 'pe_ttm'
        
        reverse = criteria.get('sort_order', 'asc') == 'desc'
        non_null = [s for s in matched if s.get(sort_by) is not None]
        null_items = [s for s in matched if s.get(sort_by) is None]
        non_null.sort(key=lambda x: x.get(sort_by), reverse=reverse)
        matched = non_null + null_items
        
        total = len(matched)
        page = matched[offset:offset + limit]
        
        return {
            'success': True,
            'board': board,
            'matched_count': total,
            'returned': len(page),
            'offset': offset,
            'limit': limit,
            'has_more': (offset + limit) < total,
            'page_info': {
                'current_offset': offset,
                'current_limit': limit,
                'total_matched': total,
                'has_more': (offset + limit) < total,
                'next_offset': offset + limit if (offset + limit) < total else None,
            },
            'results': page,
        }
    
    def clear_cache(self, pattern: str = None) -> Dict[str, Any]:
        """清空会话缓存
        
        Args:
            pattern: 可选的模式匹配，如 'kline_' 清理所有K线缓存，None 表示清空全部
        
        Returns:
            清理结果
        """
        stats_before = self.cache.get_stats()
        self.cache.clear(pattern)
        logger.info(f"会话缓存已清空: pattern={pattern}, 清理前={stats_before['total_items']}条")
        
        return {
            'success': True,
            'message': f"缓存已清空" + (f" (匹配: {pattern})" if pattern else " (全部)"),
            'cleared_items': stats_before['total_items'],
            'pattern': pattern,
        }
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        stats = self.cache.get_stats()
        return {
            'success': True,
            'total_items': stats['total_items'],
            'max_size': stats['max_size'],
            'recent_keys': stats['keys'],
            'usage_pct': round(stats['total_items'] / stats['max_size'] * 100, 1) if stats['max_size'] > 0 else 0,
        }
