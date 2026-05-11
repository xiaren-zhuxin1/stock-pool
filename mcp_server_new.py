import asyncio
import json
import sys
import os
from datetime import datetime, timezone, timedelta

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError):
        pass

script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)
sys.path.insert(0, parent_dir)

from provider_manager import ProviderManager
from mcp_tools_new import TOOLS
from errors import (
    create_success_response, create_error_response, handle_error,
    ValidationError, DataNotFoundError, Logger,
)
from storage import init_database_schema
from indicators import calculate_technical_indicators

import sqlite3
from typing import Optional, List, Dict, Any
from contextlib import contextmanager


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

    def get_current_time_info(self) -> Dict[str, Any]:
        now = datetime.now(SHANGHAI_TZ)
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
            return create_success_response(
                result.data,
                metadata={
                    'provider': result.provider_name,
                    'fallback_used': result.fallback_used,
                    'fallback_chain': result.fallback_chain,
                }
            )
        else:
            return create_error_response(
                message=result.error.message,
                error_code=result.error.error_type.value,
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
        results = []
        for code in codes:
            result = self.provider_manager.fetch_realtime(code)
            if result.success:
                results.append(result.data)
            else:
                results.append({'code': code, 'error': result.error.message})
            if delay:
                import time
                time.sleep(delay)
        
        return create_success_response(results)

    def _handle_get_daily_kline(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        
        days = arguments.get('days', 250)
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        providers = arguments.get('providers')
        
        result = self.provider_manager.fetch_daily_kline(
            code, days, start_date, end_date, providers
        )
        
        if result.success:
            klines = result.data
            parsed = []
            for kline in klines:
                parts = kline.split(',')
                if len(parts) >= 7:
                    parsed.append({
                        'date': parts[0],
                        'open': float(parts[1]) if parts[1] else None,
                        'close': float(parts[2]) if parts[2] else None,
                        'high': float(parts[3]) if parts[3] else None,
                        'low': float(parts[4]) if parts[4] else None,
                        'volume': float(parts[5]) if parts[5] else None,
                        'amount': float(parts[6]) if parts[6] else None,
                    })
            
            return create_success_response(
                parsed,
                metadata={
                    'provider': result.provider_name,
                    'count': len(parsed),
                    'fallback_used': result.fallback_used,
                }
            )
        else:
            return create_error_response(
                message=result.error.message,
                error_code=result.error.error_type.value,
                details={'provider': result.provider_name},
            )

    def _handle_get_minute_kline(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        
        klt = arguments.get('klt', 5)
        days = arguments.get('days', 5)
        providers = arguments.get('providers')
        
        result = self.provider_manager.fetch_minute_kline(code, klt, days, providers)
        
        if result.success:
            klines = result.data
            parsed = []
            for kline in klines:
                parts = kline.split(',')
                if len(parts) >= 7:
                    parsed.append({
                        'time': parts[0],
                        'open': float(parts[1]) if parts[1] else None,
                        'close': float(parts[2]) if parts[2] else None,
                        'high': float(parts[3]) if parts[3] else None,
                        'low': float(parts[4]) if parts[4] else None,
                        'volume': float(parts[5]) if parts[5] else None,
                        'amount': float(parts[6]) if parts[6] else None,
                    })
            
            return create_success_response(
                parsed,
                metadata={
                    'provider': result.provider_name,
                    'klt': klt,
                    'count': len(parsed),
                }
            )
        else:
            return create_error_response(
                message=result.error.message,
                error_code=result.error.error_type.value,
            )

    def _handle_get_valuation(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        
        providers = arguments.get('providers')
        result = self.provider_manager.fetch_valuation(code, providers)
        
        if result.success:
            return create_success_response(
                result.data,
                metadata={'provider': result.provider_name}
            )
        else:
            return create_error_response(
                message=result.error.message,
                error_code=result.error.error_type.value,
            )

    def _handle_get_fund_flow(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        
        days = arguments.get('days', 100)
        providers = arguments.get('providers')
        
        result = self.provider_manager.fetch_fund_flow(code, days, providers)
        
        if result.success:
            return create_success_response(
                result.data,
                metadata={'provider': result.provider_name, 'count': len(result.data) if isinstance(result.data, list) else 1}
            )
        else:
            return create_error_response(
                message=result.error.message,
                error_code=result.error.error_type.value,
            )

    def _handle_get_stock_list(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        board = arguments.get('board', 'a_share')
        providers = arguments.get('providers')
        
        result = self.provider_manager.fetch_stock_list(board, providers)
        
        if result.success:
            stocks = result.data
            codes = [s['code'] for s in stocks]
            return create_success_response(
                {'stocks': stocks, 'codes': codes, 'total': len(stocks)},
                metadata={'provider': result.provider_name, 'board': board}
            )
        else:
            return create_error_response(
                message=result.error.message,
                error_code=result.error.error_type.value,
            )

    def _handle_get_financial_data(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        
        report_type = arguments.get('report_type', 'income')
        providers = arguments.get('providers')
        
        result = self.provider_manager.fetch_financial(code, report_type, providers)
        
        if result.success:
            return create_success_response(
                result.data,
                metadata={'provider': result.provider_name, 'report_type': report_type}
            )
        else:
            return create_error_response(
                message=result.error.message,
                error_code=result.error.error_type.value,
                suggested_action="TuShare需要配置Token，或使用AkShare",
            )

    def _handle_update_stock(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        
        days = arguments.get('days', 250)
        force = arguments.get('force', False)
        
        kline_result = self.provider_manager.fetch_daily_kline(code, days)
        if not kline_result.success:
            return create_error_response(
                message=f"获取K线失败: {kline_result.error.message}",
                error_code=kline_result.error.error_type.value,
            )
        
        valuation_result = self.provider_manager.fetch_valuation(code)
        
        with self._get_connection() as conn:
            from storage import save_daily_data, save_valuation_data, save_stock_info
            
            if kline_result.data:
                save_daily_data(conn, code, kline_result.data)
            
            if valuation_result.success and valuation_result.data:
                valuation_result.data['name'] = valuation_result.data.get('name', '')
                valuation_result.data['market'] = 'SH' if code.startswith('6') else 'SZ'
                save_stock_info(conn, code, valuation_result.data)
                save_valuation_data(conn, code, valuation_result.data)
        
        return create_success_response(
            {'code': code, 'updated': True},
            message=f"已更新 {code}",
            metadata={
                'kline_provider': kline_result.provider_name,
                'valuation_provider': valuation_result.provider_name if valuation_result.success else None,
            }
        )

    def _handle_analyze_position(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        codes = arguments.get('codes', [])
        if not codes:
            raise ValidationError("缺少股票代码列表", field='codes')
        if len(codes) > 100:
            raise ValidationError("单次最多100只股票", field='codes', value=len(codes))
        
        results = []
        for code in codes:
            kline_result = self.provider_manager.fetch_daily_kline(code, 250)
            if not kline_result.success:
                results.append({
                    'code': code,
                    'success': False,
                    'error': kline_result.error.message,
                })
                continue
            
            klines = kline_result.data
            if not klines:
                results.append({
                    'code': code,
                    'success': False,
                    'error': '无K线数据',
                })
                continue
            
            closes = []
            for kline in klines:
                parts = kline.split(',')
                if len(parts) >= 3 and parts[2]:
                    closes.append(float(parts[2]))
            
            if not closes:
                results.append({
                    'code': code,
                    'success': False,
                    'error': '无有效价格数据',
                })
                continue
            
            high_52w = max(closes)
            low_52w = min(closes)
            current = closes[-1]
            
            position_pct = (current - low_52w) / (high_52w - low_52w) * 100 if high_52w != low_52w else 50
            
            results.append({
                'code': code,
                'success': True,
                'current_price': current,
                'high_52w': high_52w,
                'low_52w': low_52w,
                'position_pct': round(position_pct, 2),
                'distance_to_high': round((high_52w - current) / current * 100, 2) if current else None,
                'distance_to_low': round((current - low_52w) / current * 100, 2) if current else None,
                'provider': kline_result.provider_name,
            })
        
        return create_success_response(results)

    def _handle_get_technical_indicators(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        
        with self._get_connection() as conn:
            from storage import get_daily_data_for_technical, save_technical_data
            
            rows = get_daily_data_for_technical(conn, code)
            if not rows:
                return create_error_response(
                    message="无K线数据，请先调用 update_stock",
                    error_code="DATA_NOT_FOUND",
                    suggested_action="调用 update_stock 更新数据",
                )
            
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            technical_items = calculate_technical_indicators(rows, now)
            save_technical_data(conn, code, technical_items)
            
            return create_success_response(technical_items[-50:] if len(technical_items) > 50 else technical_items)

    def _handle_get_latest_data(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        codes = arguments.get('codes', [])
        if not codes:
            raise ValidationError("缺少股票代码列表", field='codes')
        if len(codes) > 30:
            raise ValidationError("单次最多30只股票", field='codes', value=len(codes))
        
        include_realtime = arguments.get('include_realtime', False)
        results = []
        
        for code in codes:
            item = {'code': code}
            
            valuation_result = self.provider_manager.fetch_valuation(code)
            if valuation_result.success:
                item.update(valuation_result.data)
                item['valuation_provider'] = valuation_result.provider_name
            
            if include_realtime:
                realtime_result = self.provider_manager.fetch_realtime(code)
                if realtime_result.success:
                    item['realtime'] = realtime_result.data
                    item['realtime_provider'] = realtime_result.provider_name
            
            results.append(item)
        
        return create_success_response(results)

    def _handle_get_stock_info(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        
        with self._get_connection() as conn:
            from storage import get_stock_info
            info = get_stock_info(conn, code)
        
        if info:
            return create_success_response(info)
        else:
            return create_error_response(
                message=f"未找到股票 {code} 的信息",
                error_code="DATA_NOT_FOUND",
                suggested_action="调用 update_stock 更新数据",
            )

    def _handle_analyze_intraday(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        
        result = self.provider_manager.fetch_minute_kline(code, 5, 1)
        
        if result.success:
            return create_success_response(
                {'minute_data': result.data, 'provider': result.provider_name}
            )
        else:
            return create_error_response(
                message=result.error.message,
                error_code=result.error.error_type.value,
            )

    def _handle_analyze_main_force(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        code = arguments.get('code')
        if not code:
            raise ValidationError("缺少股票代码", field='code')
        
        days = arguments.get('days', 10)
        
        result = self.provider_manager.fetch_fund_flow(code, days)
        if not result.success:
            return create_error_response(
                message=result.error.message,
                error_code=result.error.error_type.value,
            )
        
        fund_flows = result.data
        if not fund_flows:
            return create_error_response(
                message="无资金流向数据",
                error_code="DATA_NOT_FOUND",
            )
        
        main_inflows = [f.get('main_net_inflow') for f in fund_flows if f.get('main_net_inflow')]
        
        if not main_inflows:
            return create_error_response(
                message="无有效主力资金数据",
                error_code="DATA_NOT_FOUND",
            )
        
        total = sum(main_inflows)
        avg = total / len(main_inflows)
        positive_days = sum(1 for v in main_inflows if v > 0)
        
        return create_success_response({
            'code': code,
            'days': len(main_inflows),
            'total_main_inflow': total,
            'avg_main_inflow': avg,
            'positive_days': positive_days,
            'negative_days': len(main_inflows) - positive_days,
            'trend': 'inflow' if total > 0 else 'outflow',
            'provider': result.provider_name,
        })

    def _handle_screen_market(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return create_error_response(
            message="筛选功能需要数据库支持，请使用旧版 stock_pool.py",
            error_code="NOT_IMPLEMENTED",
            suggested_action="使用 start_market_sync 更新数据后，再用数据库查询",
        )

    def _handle_screen_all_market(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return self._handle_screen_market(arguments)

    def _handle_update_stocks(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        codes = arguments.get('codes', [])
        if not codes:
            raise ValidationError("缺少股票代码列表", field='codes')
        if len(codes) > 50:
            raise ValidationError("单次最多50只股票", field='codes', value=len(codes))
        
        results = {}
        for code in codes:
            try:
                result = self._handle_update_stock({'code': code, 'days': arguments.get('days', 250)})
                results[code] = 'success' if result.get('success') else result.get('error', {}).get('message', 'failed')
            except Exception as e:
                results[code] = str(e)
        
        return create_success_response({'results': results})

    def _handle_start_market_sync(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return create_error_response(
            message="批量同步功能需要后台任务支持，请使用旧版 stock_pool.py",
            error_code="NOT_IMPLEMENTED",
        )

    def _handle_get_sync_status(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return create_error_response(
            message="任务状态查询需要后台任务支持",
            error_code="NOT_IMPLEMENTED",
        )

    def _handle_cancel_sync(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return create_error_response(
            message="任务取消需要后台任务支持",
            error_code="NOT_IMPLEMENTED",
        )

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
            'get_financial_data': self._handle_get_financial_data,
            'update_stock': self._handle_update_stock,
            'update_stocks': self._handle_update_stocks,
            'analyze_position': self._handle_analyze_position,
            'get_technical_indicators': self._handle_get_technical_indicators,
            'get_latest_data': self._handle_get_latest_data,
            'get_stock_info': self._handle_get_stock_info,
            'analyze_intraday': self._handle_analyze_intraday,
            'analyze_main_force': self._handle_analyze_main_force,
            'screen_market': self._handle_screen_market,
            'screen_all_market': self._handle_screen_all_market,
            'start_market_sync': self._handle_start_market_sync,
            'get_sync_status': self._handle_get_sync_status,
            'cancel_sync': self._handle_cancel_sync,
        }
        
        handler = handlers.get(name)
        if not handler:
            return create_error_response(
                message=f"未知工具: {name}",
                error_code="UNKNOWN_TOOL",
            )
        
        try:
            return handler(arguments or {})
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
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "stock-pool-v2",
                    "version": "2.0.0"
                }
            }
        }
    
    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"tools": TOOLS}
        }
    
    elif method == "tools/call":
        params = request.get("params", {})
        name = params.get("name")
        arguments = params.get("arguments", {})
        result = server.handle_tool_call(name, arguments)
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, ensure_ascii=False, default=str)
                    }
                ]
            }
        }
    
    else:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32601,
                "message": f"Method not found: {method}"
            }
        }


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
                error_response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32603,
                        "message": str(e)
                    }
                }
                print(json.dumps(error_response), flush=True)
            else:
                print(f"MCP server error: {e}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
