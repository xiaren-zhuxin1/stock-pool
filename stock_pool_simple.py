"""
简化的股票数据池 - 纯实时API调用，无缓存
"""
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from provider_manager import ProviderManager
from indicators import (
    calculate_ma, calculate_technical_indicators, ema, rsi,
    calculate_returns, calculate_volume_analysis,
    generate_technical_signals, calculate_support_resistance
)
from errors import ValidationError, logger

SHANGHAI_TZ = timezone(timedelta(hours=8), name='Asia/Shanghai')


class StockDataPool:
    """纯实时API调用的股票数据池，无数据库缓存"""
    
    def __init__(self):
        self.api = ProviderManager()
    
    @staticmethod
    def get_current_time_info(now: Optional[datetime] = None) -> Dict[str, Any]:
        """返回北京时间与A股交易时段状态"""
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
    
    def get_realtime_quotes(self, codes: List[str], delay: float = 0.2) -> List[Dict[str, Any]]:
        """批量获取实时行情"""
        results = []
        for code in codes:
            result = self.api.fetch_realtime(code)
            if result.success and result.data:
                results.append({
                    'code': code,
                    'success': True,
                    **result.data,
                    'provider': result.provider_name,
                })
            else:
                err_msg = result.error.message if result.error else '未知错误'
                results.append({
                    'code': code,
                    'success': False,
                    'error': err_msg,
                })
            if delay:
                time.sleep(delay)
        return results
    
    def get_daily_kline(self, code: str, days: int = 250, 
                        start_date: Optional[str] = None,
                        end_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取日K线数据"""
        result = self.api.fetch_daily_kline(code, days)
        if not result.success or not result.data:
            return []
        
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
        
        if start_date:
            klines = [k for k in klines if k.get('date', '') >= start_date]
        if end_date:
            klines = [k for k in klines if k.get('date', '') <= end_date]
        
        return klines
    
    def get_minute_kline(self, code: str, klt: int = 5, days: int = 5) -> List[Dict[str, Any]]:
        """获取分钟K线数据"""
        result = self.api.fetch_minute_kline(code, klt, days)
        if not result.success or not result.data:
            return []
        
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
        
        return klines
    
    def get_fund_flow(self, code: str, days: int = 10) -> List[Dict[str, Any]]:
        """获取资金流向数据"""
        result = self.api.fetch_fund_flow(code, days)
        if not result.success or not result.data:
            return []
        return result.data
    
    def analyze_main_force(self, code: str, days: int = 10) -> Dict[str, Any]:
        """分析主力资金"""
        fund_flow_data = self.get_fund_flow(code, days)
        
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
    
    def get_stock_list(self, board: str = 'a_share') -> List[Dict[str, Any]]:
        """获取股票列表"""
        result = self.api.fetch_stock_list(board)
        if not result.success or not result.data:
            return []
        return result.data
    
    def get_financial_data(self, code: str, report_type: str = 'income') -> Dict[str, Any]:
        """获取财务数据"""
        result = self.api.fetch_financial(code, report_type)
        if not result.success or not result.data:
            return {}
        return result.data
    
    def analyze_position(self, codes: List[str]) -> List[Dict[str, Any]]:
        """分析52周位置"""
        results = []
        for code in codes:
            result = self.api.fetch_realtime(code)
            if result.success and result.data:
                data = result.data
                high_52w = data.get('high_52w')
                low_52w = data.get('low_52w')
                price = data.get('price')
                
                position_pct = None
                if high_52w and low_52w and price and high_52w > low_52w:
                    position_pct = round((price - low_52w) / (high_52w - low_52w) * 100, 2)
                
                results.append({
                    'code': code,
                    'name': data.get('name'),
                    'price': price,
                    'high_52w': high_52w,
                    'low_52w': low_52w,
                    'position_pct': position_pct,
                })
            else:
                results.append({
                    'code': code,
                    'error': result.error.message if result.error else '获取失败',
                })
        return results
    
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
        
        minute_data = self.get_minute_kline(code, klt=1, days=1)
        if not minute_data:
            return {
                'success': False,
                'error': {
                    'code': 'NO_MINUTE_DATA',
                    'message': '未获取到分钟数据',
                    'severity': 'error',
                    'recoverable': True,
                    'suggested_action': '请检查股票代码是否正确',
                }
            }
        
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
            return {
                'success': False,
                'code': code,
                'error': '无法获取股票数据',
            }
        
        realtime = realtime_result.data
        
        kline_data = self.get_daily_kline(code, days=250)
        if not kline_data:
            return {
                'success': False,
                'code': code,
                'error': '无法获取K线数据',
            }
        
        kline_sorted = sorted(kline_data, key=lambda x: x.get('date', ''))
        closes = [float(r['close']) for r in kline_sorted if r.get('close')]
        highs = [float(r['high']) for r in kline_sorted if r.get('high')]
        lows = [float(r['low']) for r in kline_sorted if r.get('low')]
        volumes = [float(r.get('volume') or 0) for r in kline_sorted]
        
        # 计算技术指标
        from datetime import datetime as dt
        rows = [(k.get('date'), k.get('open'), k.get('high'), k.get('low'), 
                 k.get('close'), k.get('volume')) for k in kline_sorted]
        technical_indicators = calculate_technical_indicators(rows, dt.now().strftime('%Y-%m-%d %H:%M:%S'))
        
        # 生成技术信号
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
        
        valuation_summary = {
            'pe_ttm': pe_ttm,
            'pb': pb,
            'market_cap_yi': round(market_cap / 100000000, 2) if market_cap else None,
            'valuation_level': valuation_level,
        }
        
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
            'valuation': valuation_summary,
        }
    
    def get_latest_data(self, codes: List[str]) -> List[Dict[str, Any]]:
        """获取最新综合数据"""
        results = []
        for code in codes:
            result = self.api.fetch_realtime(code)
            if result.success and result.data:
                data = result.data
                high_52w = data.get('high_52w')
                low_52w = data.get('low_52w')
                price = data.get('price')
                
                position_pct = None
                if high_52w and low_52w and price and high_52w > low_52w:
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
                results.append({
                    'code': code,
                    'error': result.error.message if result.error else '获取失败',
                })
        return results
    
    def get_stock_detail(self, code: str, fund_flow_days: int = 10) -> Dict[str, Any]:
        """获取股票详情"""
        realtime_result = self.api.fetch_realtime(code)
        if not realtime_result.success or not realtime_result.data:
            return {
                'success': False,
                'code': code,
                'error': '无法获取股票信息',
            }
        
        realtime = realtime_result.data
        latest_list = self.get_latest_data([code])
        latest = latest_list[0] if latest_list else None
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
        limit = criteria.get('limit', 50)
        offset = criteria.get('offset', 0)
        
        filters = {
            'pe_ttm_min': criteria.get('pe_ttm_min'),
            'pe_ttm_max': criteria.get('pe_ttm_max'),
            'pb_min': criteria.get('pb_min'),
            'pb_max': criteria.get('pb_max'),
            'market_cap_min': criteria.get('market_cap_min'),
            'market_cap_max': criteria.get('market_cap_max'),
        }
        
        for key in ('market_cap_min', 'market_cap_max'):
            if filters[key] is not None:
                filters[key] *= 100000000
        
        has_filter = any(v is not None for v in filters.values())
        if not has_filter:
            return {
                'success': False,
                'error': '市场筛选必须提供至少一个筛选条件',
            }
        
        universe_result = self.api.fetch_stock_list(board)
        if not universe_result.success or not universe_result.data:
            return {
                'success': False,
                'error': '无法获取股票列表',
            }
        
        matched = []
        for row in universe_result.data:
            pe_ttm = row.get('pe_ttm')
            pb = row.get('pb')
            market_cap = row.get('market_cap')
            
            if filters['pe_ttm_min'] is not None and (pe_ttm is None or pe_ttm < filters['pe_ttm_min']):
                continue
            if filters['pe_ttm_max'] is not None and (pe_ttm is None or pe_ttm > filters['pe_ttm_max']):
                continue
            if filters['pb_min'] is not None and (pb is None or pb < filters['pb_min']):
                continue
            if filters['pb_max'] is not None and (pb is None or pb > filters['pb_max']):
                continue
            if filters['market_cap_min'] is not None and (market_cap is None or market_cap < filters['market_cap_min']):
                continue
            if filters['market_cap_max'] is not None and (market_cap is None or market_cap > filters['market_cap_max']):
                continue
            
            matched.append({
                'code': row.get('code'),
                'name': row.get('name'),
                'price': row.get('close'),
                'pe_ttm': pe_ttm,
                'pb': pb,
                'market_cap': market_cap,
            })
        
        sort_by = criteria.get('sort_by', 'pe_ttm')
        reverse = criteria.get('sort_order', 'asc') == 'desc'
        
        non_null = [m for m in matched if m.get(sort_by) is not None]
        null_items = [m for m in matched if m.get(sort_by) is None]
        non_null.sort(key=lambda x: x.get(sort_by), reverse=reverse)
        matched = non_null + null_items
        
        page = matched[offset:offset + limit]
        
        return {
            'success': True,
            'board': board,
            'matched_count': len(matched),
            'returned': len(page),
            'offset': offset,
            'limit': limit,
            'has_more': (offset + limit) < len(matched),
            'results': page,
        }
