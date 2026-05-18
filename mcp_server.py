"""
MCP 服务器 v3 - 实时优先 + 会话缓存

核心特性：
1. 实时优先 - 每次会话重新获取，无脏数据
2. 会话缓存 - 同一会话内避免重复请求
3. 部分成功 - 部分失败时返回可用结果
4. 限流控制 - 内置请求限流器
"""
import asyncio
import contextlib
import json
import sys
import os
from datetime import datetime
from typing import Optional, Dict, Any, List

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError):
        pass

script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)
sys.path.insert(0, parent_dir)

from stock_pool import StockDataPool
from mcp_tools import TOOLS
from errors import (
    create_success_response, create_error_response,
    ValidationError, Logger,
)

logger = Logger()


class StockPoolServer:
    """股票池服务器 v3 - 实时优先 + 会话缓存"""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.pool = StockDataPool(config)
        logger.info("StockPoolServer v3 初始化完成（实时优先+会话缓存）")
    
    @staticmethod
    def get_current_time_info(now: Optional[datetime] = None) -> Dict[str, Any]:
        return StockDataPool.get_current_time_info(now)
    
    def _normalize_codes(self, codes_arg, field='codes') -> List[str]:
        if not codes_arg:
            raise ValidationError("缺少股票代码", field=field)
        
        if isinstance(codes_arg, str):
            stripped = codes_arg.strip()
            if stripped.startswith('['):
                try:
                    parsed = json.loads(stripped)
                except json.JSONDecodeError:
                    raise ValidationError("股票代码列表不是有效的JSON数组", field=field)
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
            raise ValidationError("缺少股票代码", field=field)
        
        return cleaned
    
    def _handle_get_current_time(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return create_success_response(self.get_current_time_info())
    
    def _handle_get_realtime_quotes(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        codes = self._normalize_codes(arguments.get('codes'))
        if len(codes) > 20:
            raise ValidationError("单次最多20只股票", field='codes', value=len(codes))
        
        result = self.pool.get_realtime_quotes(codes)
        
        if result.get('partial'):
            return {
                'success': True,
                'partial': True,
                'message': f"部分成功: {result['success_count']}/{result['total']}",
                'results': result['results'],
                'failed': result['failed'],
            }
        
        if not result.get('success'):
            return create_error_response(
                message="所有股票行情获取失败",
                error_code='DATA_NOT_FOUND',
            )
        
        return create_success_response(result['results'])
    
    def _handle_get_daily_kline(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        
        days = arguments.get('days', 250)
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        
        result = self.pool.get_daily_kline(code, days, start_date, end_date)
        
        if not result.get('success'):
            return create_error_response(
                message=result.get('error', f"未获取到 {code} 的日K线数据"),
                error_code='DATA_NOT_FOUND',
                recoverable=True,
                suggested_action="请检查股票代码是否正确",
            )
        
        return create_success_response({
            'code': code,
            'count': result['count'],
            'klines': result['klines'],
        })
    
    def _handle_get_minute_kline(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        
        klt = arguments.get('klt', 5)
        days = arguments.get('days', 5)
        
        result = self.pool.get_minute_kline(code, klt, days)
        
        if not result.get('success'):
            return create_error_response(
                message=result.get('error', f"未获取到 {code} 的分钟K线数据"),
                error_code='DATA_NOT_FOUND',
                recoverable=True,
                suggested_action="非交易时段无分钟数据",
            )
        
        return create_success_response({
            'code': code,
            'count': result['count'],
            'klines': result['klines'],
        })
    
    def _handle_get_fund_flow(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        
        limit = arguments.get('limit', 10)
        
        result = self.pool.get_fund_flow(code, limit)
        
        if not result.get('success'):
            return create_error_response(
                message=result.get('error', f"未获取到 {code} 的资金流向数据"),
                error_code='DATA_NOT_FOUND',
                recoverable=True,
                suggested_action="部分小盘股/新股可能无资金流向数据",
            )
        
        analysis = self.pool.analyze_main_force(code, limit)
        
        return create_success_response({
            'code': code,
            'fund_flow': result['data'],
            'analysis': analysis if analysis.get('success') else None,
        })
    
    def _handle_get_stock_list(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        board = arguments.get('board', 'a_share')
        page = arguments.get('page', 1)
        page_size = min(arguments.get('page_size', 100), 100)
        
        result = self.pool.get_stock_list(board)
        
        if not result.get('success'):
            return create_error_response(
                message=result.get('error', "未获取到股票列表"),
                error_code='DATA_NOT_FOUND',
            )
        
        stocks = result['stocks']
        start = (page - 1) * page_size
        end = start + page_size
        page_stocks = stocks[start:end]
        
        return create_success_response({
            'stocks': page_stocks,
            'total': len(stocks),
            'page': page,
            'page_size': page_size,
            'total_pages': (len(stocks) + page_size - 1) // page_size,
        })
    
    def _handle_get_financial_data(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        
        report_type = arguments.get('report_type', 'income')
        result = self.pool.get_financial_data(code, report_type)
        
        if not result.get('success'):
            return create_error_response(
                message=result.get('error', f"未获取到 {code} 的财务数据"),
                error_code='DATA_NOT_FOUND',
            )
        
        return create_success_response(result['data'])
    
    def _handle_analyze_position(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        codes = self._normalize_codes(arguments.get('codes'))
        if len(codes) > 20:
            raise ValidationError("单次最多20只股票", field='codes', value=len(codes))
        
        result = self.pool.analyze_position(codes)
        
        if result.get('partial'):
            return {
                'success': True,
                'partial': True,
                'message': f"部分成功: {result['success_count']}/{result['total']}",
                'results': result['results'],
                'failed': result['failed'],
            }
        
        if not result.get('success'):
            return create_error_response(
                message="所有股票位置分析失败",
                error_code='DATA_NOT_FOUND',
            )
        
        return create_success_response(result['results'])
    
    def _handle_analyze_stock(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        
        fund_flow_days = arguments.get('fund_flow_days', 10)
        result = self.pool.analyze_stock(code, fund_flow_days)
        
        if not result.get('success'):
            return create_error_response(
                message=result.get('error', '分析失败'),
                error_code='ANALYSIS_FAILED',
            )
        
        return create_success_response(result)
    
    def _handle_get_latest_data(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        codes = self._normalize_codes(arguments.get('codes'))
        if len(codes) > 10:
            raise ValidationError("单次最多10只股票", field='codes', value=len(codes))
        
        result = self.pool.get_latest_data(codes)
        
        if result.get('partial'):
            return {
                'success': True,
                'partial': True,
                'message': f"部分成功: {result['success_count']}/{result['total']}",
                'results': result['results'],
                'failed': result['failed'],
            }
        
        if not result.get('success'):
            return create_error_response(
                message="所有股票数据获取失败",
                error_code='DATA_NOT_FOUND',
            )
        
        return create_success_response(result['results'])
    
    def _handle_get_stock_detail(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        
        fund_flow_days = arguments.get('fund_flow_days', 10)
        result = self.pool.get_stock_detail(code, fund_flow_days)
        
        if not result.get('success'):
            return create_error_response(
                message=result.get('error', '获取详情失败'),
                error_code='DATA_NOT_FOUND',
            )
        
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
            return create_error_response(
                message=error.get('message', '日内分析失败'),
                error_code=error.get('code', 'ANALYSIS_FAILED'),
                recoverable=error.get('recoverable', True),
                suggested_action=error.get('suggested_action'),
            )
    
    def _handle_screen_market(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return self.pool.screen_market(arguments)
    
    def _handle_clear_cache(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        pattern = arguments.get('pattern')
        result = self.pool.clear_cache(pattern)
        return create_success_response(result)
    
    def _handle_get_cache_stats(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        result = self.pool.get_cache_stats()
        return create_success_response(result)
    
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
            'clear_cache': self._handle_clear_cache,
            'get_cache_stats': self._handle_get_cache_stats,
        }
        
        handler = handlers.get(name)
        if not handler:
            return create_error_response(
                message=f"未知工具: {name}",
                error_code='UNKNOWN_TOOL',
            )
        
        try:
            return handler(arguments or {})
        except ValidationError as e:
            return e.to_dict()
        except Exception as e:
            logger.error(f"工具执行失败 {name}: {e}")
            return create_error_response(
                message=f"执行失败: {str(e)}",
                error_code='EXECUTION_ERROR',
            )


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
                "serverInfo": {"name": "stock-pool-v3", "version": "3.0.0"},
            }
        }
    elif method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}
    elif method == "tools/call":
        params = request.get("params", {})
        name = params.get("name")
        arguments = params.get("arguments", {})
        # MCP stdio requires stdout to contain only JSON-RPC frames. Some
        # third-party market-data libraries print diagnostics directly, so
        # route that noise to stderr while a tool is running.
        with contextlib.redirect_stdout(sys.stderr):
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
