import asyncio
import json
import sys
import os
import time
import builtins
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Callable
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
from stock_pool import StockDataPool
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
        self._hits = 0
        self._misses = 0
    
    def get(self, key: str) -> Optional[Any]:
        with self.lock:
            if key not in self.cache:
                self._misses += 1
                return None
            value, timestamp = self.cache[key]
            if time.time() - timestamp > self.ttl:
                del self.cache[key]
                self._misses += 1
                return None
            self.cache.move_to_end(key)
            self._hits += 1
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
            self._hits = 0
            self._misses = 0
    
    def stats(self) -> Dict[str, Any]:
        with self.lock:
            total = self._hits + self._misses
            hit_rate = self._hits / total * 100 if total > 0 else 0
            return {
                'size': len(self.cache),
                'max_size': self.max_size,
                'hits': self._hits,
                'misses': self._misses,
                'hit_rate_pct': round(hit_rate, 2),
            }


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
    '_internal_source': _SANITIZE_DROP,
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
        db_path = self.config.get('db_path')
        self.pool = StockDataPool(db_path)
        self._screener_cache = LRUCache(max_size=10, ttl=14400)
        logger.info("StockPoolServer 初始化完成")

    @staticmethod
    def get_current_time_info(now: Optional[datetime] = None) -> Dict[str, Any]:
        return StockDataPool.get_current_time_info(now)

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
    def _normalize_codes_argument(codes_arg, field='codes'):
        if not codes_arg:
            raise ValidationError("缺少股票代码列表", field=field)
        if isinstance(codes_arg, str):
            stripped = codes_arg.strip()
            if stripped.startswith('['):
                try:
                    parsed = json.loads(stripped)
                except json.JSONDecodeError:
                    raise ValidationError("股票代码列表不是有效的JSON数组", field=field, value=codes_arg)
                if not isinstance(parsed, list):
                    raise ValidationError("股票代码列表必须是数组", field=field, value=codes_arg)
                codes = parsed
            else:
                codes = [stripped]
        else:
            codes = list(codes_arg)

        cleaned = []
        for code in codes:
            code = str(code).strip()
            if code:
                cleaned.append(code)
        if not cleaned:
            raise ValidationError("缺少股票代码列表", field=field)
        return cleaned

    @staticmethod
    def _chunked(items, size):
        size = max(1, int(size or 1))
        for i in range(0, len(items), size):
            yield items[i:i + size]

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

    def _handle_get_realtime_quotes(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        codes = self._normalize_codes_argument(arguments.get('codes'), field='codes')
        if len(codes) > 5:
            raise ValidationError("单次最多5只股票；大量股票请由agent分批遍历", field='codes', value=len(codes))
        results = self.pool.get_realtime_prices(codes, 0.2)
        return create_success_response(results)

    def _handle_get_daily_kline(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        days = self._normalize_positive_int(arguments.get('days', 250), 250, 300) or 250

        data = self.pool.get_daily_data(code, start_date, end_date, limit=days)
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
        days = self._normalize_positive_int(arguments.get('days', 3), 3, 5) or 3

        time_info = self.pool.get_current_time_info()
        today = time_info['date']
        from datetime import timedelta as _td
        start_date = (datetime.strptime(today, '%Y-%m-%d') - _td(days=days)).strftime('%Y-%m-%d')
        start_time = f'{start_date} 09:30'
        end_time = f'{today} 15:00'

        data = self.pool.get_minute_data(code, klt, start_time=start_time, end_time=end_time)
        if not data:
            return create_error_response(
                message=f"未获取到 {code} 的分钟K线数据",
                error_code='DATA_NOT_FOUND',
                recoverable=True,
                suggested_action="非交易时段无分钟数据，请在交易时间重试",
            )
        return create_success_response(data)

    def _handle_get_fund_flow(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        limit = self._normalize_positive_int(arguments.get('limit', 10), 10, 30) or 10

        data = self.pool.get_fund_flow(code, start_date, end_date, limit)
        if not data:
            self.pool.update_fund_flow(code, days=max(limit, 30), delay=0)
            data = self.pool.get_fund_flow(code, start_date, end_date, limit)
        if not data:
            return create_error_response(
                message=f"未获取到 {code} 的资金流向数据。可能是数据源暂时不可用或该股票暂无资金流向记录",
                error_code='DATA_NOT_FOUND',
                recoverable=True,
                suggested_action="请检查股票代码是否正确，稍后重试；部分小盘股/新股可能无资金流向数据",
            )
        
        analysis = self.pool.analyze_main_force(code, limit)
        result = {
            'code': code,
            'fund_flow': data,
            'analysis': analysis if analysis.get('success') else None,
        }
        return create_success_response(result)

    def _handle_get_stock_list(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        board = arguments.get('board', 'a_share')
        page = arguments.get('page') or 1
        page_size = arguments.get('page_size', 50)

        result = self.pool.api.fetch_stock_list(board)
        if not result.success:
            return self._make_data_error(board, result, '股票列表')

        stocks = result.data
        codes = [s['code'] for s in stocks]

        page = self._normalize_positive_int(page, 1, 100000) or 1
        page_size = self._normalize_positive_int(page_size, 50, 50) or 50
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

    def _handle_get_financial_data(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        report_type = arguments.get('report_type', 'income')
        result = self.pool.api.fetch_financial(code, report_type)
        if result.success:
            return create_success_response(result.data)
        else:
            return self._make_data_error(code, result, '财务数据')

    def _handle_analyze_position(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        codes = self._normalize_codes_argument(arguments.get('codes'), field='codes')
        if len(codes) > 20:
            raise ValidationError("单次最多20只股票；大量候选请由agent分批遍历", field='codes', value=len(codes))
        result = self.pool.analyze_position(codes)
        return create_success_response(result)

    def _handle_analyze_stock(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        fund_flow_days = self._normalize_positive_int(arguments.get('fund_flow_days', 10), 10, 20) or 10

        indicators = self.pool.get_technical_data(code)
        if not indicators:
            self.pool.update_stock(code, days=250, delay=0)
            indicators = self.pool.get_technical_data(code)
        if not indicators:
            return create_error_response(
                message=f"未获取到 {code} 的技术指标数据，无法进行分析",
                error_code='DATA_NOT_FOUND',
                recoverable=True,
                suggested_action="请检查股票代码是否正确，或稍后重试",
            )

        kline_data = self.pool.get_daily_data(code)
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

        fund_flow_result = self.pool.analyze_main_force(code, days=fund_flow_days)
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

        valuation_data = self.pool.get_valuation_data(code)
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
        codes = self._normalize_codes_argument(arguments.get('codes'), field='codes')
        if len(codes) > 10:
            raise ValidationError("单次最多10只股票；大量股票请由agent分批遍历", field='codes', value=len(codes))
        include_realtime = arguments.get('include_realtime', False)
        results = self.pool.get_latest_data(codes, include_realtime=include_realtime)
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
        fund_flow_days = self._normalize_positive_int(arguments.get('fund_flow_days', 10), 10, 20) or 10

        info = self.pool.get_stock_info(code)
        if not info:
            return create_error_response(
                message=f"未找到股票 {code} 的信息，请检查股票代码是否正确",
                error_code='INVALID_CODE',
                recoverable=False,
                suggested_action=f"请确认股票代码 {code} 是否正确",
            )

        latest_list = self.pool.get_latest_data([code], include_realtime=include_realtime)
        latest = latest_list[0] if latest_list else None
        fund_flow = self.pool.analyze_main_force(code, days=fund_flow_days)

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
        result = self.pool.analyze_intraday(code, date)
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

    def _handle_screen_market(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return self.pool.screen_market(arguments)

    handle_tool_call_handlers = None

    def handle_tool_call(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        handlers = {
            'get_current_time': self._handle_get_current_time,
            'get_realtime_quotes': self._handle_get_realtime_quotes,
            'get_daily_kline': self._handle_get_daily_kline,
            'get_minute_kline': self._handle_get_minute_kline,
            'get_fund_flow': self._handle_get_fund_flow,
            'get_stock_list': self._handle_get_stock_list,
            'get_financial_data': self._handle_get_financial_data,
            'analyze_position': self._handle_analyze_position,
            'analyze_stock': self._handle_analyze_stock,
            'get_latest_data': self._handle_get_latest_data,
            'get_stock_detail': self._handle_get_stock_detail,
            'analyze_intraday': self._handle_analyze_intraday,
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


def handle_tool_call(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    return server.handle_tool_call(name, arguments)


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
