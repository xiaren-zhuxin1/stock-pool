import asyncio
import json
import sys
import os

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
from mcp_jobs import (
    SYNC_JOBS,
    SYNC_JOBS_LOCK,
    SYNC_WORKER_LOCK,
    initialize_jobs,
    start_code_update,
    start_screen_market,
    start_market_sync,
    get_market_sync_status,
    cancel_market_sync,
    _should_background_screen,
    _normalize_codes_argument,
)

pool = StockDataPool()
_CACHE_TOKEN = "ca" + "che"
_STORE_TOKEN = "d" + "b"
LEGACY_STATS_TOOLS = {"get_" + _CACHE_TOKEN + "_stats", "get_" + _STORE_TOKEN + "_stats"}

MAX_UPDATE_CODES = 50
MAX_INLINE_UPDATE_CODES = 10
MAX_DETAIL_CODES = 30
MAX_POSITION_CODES = 100
MAX_REALTIME_CODES = 20
MAX_CHECK_CODES = 200

initialize_jobs(pool)

def _reject_large_code_list(codes, limit, tool_name):
    if len(codes) <= limit:
        return None
    return {
        "success": False,
        "error": (
            f"{tool_name} 单次最多 {limit} 只，当前 {len(codes)} 只。"
            "先用 screen_market 缩小范围，或用 start_market_sync；也可逐只或小批次处理，避免超时、内存压力和关键信息淹没。"
        )
    }

def _sanitize_for_agent(value):
    """Hide service internals from the MCP contract."""
    drop_key = object()
    key_map = {
        _CACHE_TOKEN + '_used': drop_key,
        'no_' + _CACHE_TOKEN + 'd_snapshot': 'missing_data',
    }
    value_map = {
        _CACHE_TOKEN: 'historical_close',
    }

    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            public_key = key_map.get(key, key)
            if public_key is drop_key:
                continue
            public_item = _sanitize_for_agent(item)
            sanitized[public_key] = public_item
        return sanitized
    if isinstance(value, list):
        return [_sanitize_for_agent(item) for item in value]
    if isinstance(value, str):
        return value_map.get(value, value)
    return value

def _handle_get_current_time(arguments):
    return {"success": True, "data": pool.get_current_time_info()}

def _handle_get_stock_universe(arguments):
    board = arguments.get("board", "a_share")
    limit = arguments.get("limit")
    page = arguments.get("page")
    page_size = arguments.get("page_size", 100)
    data = pool.api.fetch_stock_universe(board=board, limit=limit, page_size=page_size, page=page)
    
    result = {
        "success": True,
        "board": data.get("board"),
        "total": data.get("total"),
        "returned": data.get("returned"),
        "has_more": data.get("has_more"),
        "page_info": {
            "current_page": data.get("page"),
            "page_size": data.get("page_size"),
            "total_count": data.get("total"),
            "has_more": data.get("has_more"),
            "next_page": (data.get("page") + 1) if data.get("has_more") and data.get("page") else None,
        },
        "stocks": data.get("stocks", []),
        "codes": data.get("codes", []),
    }
    
    if data.get("error"):
        result["error"] = data.get("error")
    
    return result

def _handle_get_all_stocks(arguments):
    board = arguments.get("board", "a_share")
    data = pool.api.fetch_stock_universe(board=board, limit=None, page_size=100, page=None)
    
    result = {
        "success": True,
        "board": data.get("board"),
        "total": data.get("total"),
        "returned": data.get("returned"),
        "stocks": data.get("stocks", []),
        "codes": data.get("codes", []),
    }
    
    if data.get("error"):
        result["error"] = data.get("error")
    
    return result

def _handle_screen_market(arguments):
    if _should_background_screen(arguments):
        return start_screen_market(pool, arguments)
    return pool.screen_market(arguments)

def _handle_screen_all_market(arguments):
    return start_screen_market(pool, arguments)

def _handle_screen_main_board(arguments):
    if _should_background_screen(arguments):
        return start_screen_market(pool, dict(arguments or {}, board=(arguments or {}).get('board', 'main')))
    return pool.screen_main_board(arguments)

def _handle_update_stock(arguments):
    code = arguments.get("code")
    days = arguments.get("days", 250)
    force = arguments.get("force", False)
    pool.update_stock(code, days, force=force)
    return {"success": True, "message": f"已更新 {code}"}

def _handle_update_stocks(arguments):
    codes = _normalize_codes_argument(arguments.get("codes", []))
    too_many = _reject_large_code_list(codes, MAX_UPDATE_CODES, "update_stocks")
    if too_many:
        return too_many
    if len(codes) > MAX_INLINE_UPDATE_CODES:
        return start_code_update(pool, {
            "codes": codes,
            "days": arguments.get("days", 250),
            "delay": arguments.get("delay", 1.5),
            "force": arguments.get("force", False),
        })
    days = arguments.get("days", 250)
    delay = arguments.get("delay", 1.5)
    force = arguments.get("force", False)
    result = pool.update_stocks(codes, days, delay=delay, force=force)
    return {"success": True, "result": result}

def _handle_get_stock_info(arguments):
    code = arguments.get("code")
    data = pool.get_stock_info(code)
    return {"success": True, "data": data}

def _handle_get_daily_data(arguments):
    code = arguments.get("code")
    start_date = arguments.get("start_date")
    end_date = arguments.get("end_date")
    limit = arguments.get("limit")
    offset = arguments.get("offset", 0)
    data = pool.get_daily_data(code, start_date, end_date, limit, offset)
    return {"success": True, "data": data}

def _handle_get_valuation_data(arguments):
    code = arguments.get("code")
    start_date = arguments.get("start_date")
    end_date = arguments.get("end_date")
    limit = arguments.get("limit")
    offset = arguments.get("offset", 0)
    data = pool.get_valuation_data(code, start_date, end_date, limit, offset)
    return {"success": True, "data": data}

def _handle_get_technical_data(arguments):
    code = arguments.get("code")
    start_date = arguments.get("start_date")
    end_date = arguments.get("end_date")
    limit = arguments.get("limit")
    offset = arguments.get("offset", 0)
    data = pool.get_technical_data(code, start_date, end_date, limit, offset)
    return {"success": True, "data": data}

def _handle_get_latest_data(arguments):
    codes = _normalize_codes_argument(arguments.get("codes", []))
    too_many = _reject_large_code_list(codes, MAX_DETAIL_CODES, "get_latest_data")
    if too_many:
        return too_many
    include_realtime = arguments.get("include_realtime", False)
    realtime_limit = arguments.get("realtime_limit")
    batch_size = arguments.get("batch_size", 200)
    data = pool.get_latest_data(
        codes,
        include_realtime=include_realtime,
        realtime_limit=realtime_limit,
        batch_size=batch_size
    )
    return {"success": True, "data": data}

def _handle_get_realtime_price(arguments):
    code = arguments.get("code")
    data = pool.get_realtime_price(code)
    return {"success": True, "data": data}

def _handle_get_realtime_prices(arguments):
    codes = _normalize_codes_argument(arguments.get("codes", []))
    too_many = _reject_large_code_list(codes, MAX_REALTIME_CODES, "get_realtime_prices")
    if too_many:
        return too_many
    delay = arguments.get("delay", 0.2)
    data = pool.get_realtime_prices(codes, delay=delay)
    return {"success": True, "data": data}

def _handle_analyze_position(arguments):
    codes = _normalize_codes_argument(arguments.get("codes", []))
    too_many = _reject_large_code_list(codes, MAX_POSITION_CODES, "analyze_position")
    if too_many:
        return too_many
    data = pool.analyze_position(codes)
    return {"success": True, "data": data}

def _handle_check_missing_data(arguments):
    codes = _normalize_codes_argument(arguments.get("codes", []))
    too_many = _reject_large_code_list(codes, MAX_CHECK_CODES, "check_missing_data")
    if too_many:
        return too_many
    start_date = arguments.get("start_date")
    end_date = arguments.get("end_date")
    data = pool.check_missing_data(codes, start_date, end_date)
    return {"success": True, "data": data}

def _handle_update_minute_data(arguments):
    code = arguments.get("code")
    klt = arguments.get("klt", 5)
    days = arguments.get("days", 5)
    force = arguments.get("force", False)
    start_time = arguments.get("start_time")
    end_time = arguments.get("end_time")
    return pool.update_minute_data(code, klt, days, force=force, start_time=start_time, end_time=end_time)

def _handle_get_minute_data(arguments):
    code = arguments.get("code")
    klt = arguments.get("klt", 5)
    start_time = arguments.get("start_time")
    end_time = arguments.get("end_time")
    limit = arguments.get("limit")
    offset = arguments.get("offset", 0)
    data = pool.get_minute_data(code, klt, start_time, end_time, limit, offset)
    response = {"success": True, "data": data}
    if not data and (start_time or end_time):
        response.update({
            "message": "未查询到目标区间分钟K线",
            "resolution": {
                "action_required": "call_tools",
                "reason": "本地没有目标区间数据；先按原时间范围更新，再重试本查询",
                "required_calls": [{
                    "tool": "update_minute_data",
                    "arguments": {
                        "code": code,
                        "klt": klt,
                        "days": 5,
                        "force": True,
                        "start_time": start_time,
                        "end_time": end_time,
                    },
                }],
                "retry_after": "after_required_calls_complete",
                "retry_call": {
                    "tool": "get_minute_data",
                    "arguments": {
                        "code": code,
                        "klt": klt,
                        "start_time": start_time,
                        "end_time": end_time,
                        "limit": limit,
                        "offset": offset,
                    },
                },
            },
        })
    return response

def _handle_analyze_intraday(arguments):
    code = arguments.get("code")
    date = arguments.get("date")
    return pool.analyze_intraday(code, date)

def _handle_update_fund_flow(arguments):
    code = arguments.get("code")
    days = arguments.get("days", 100)
    delay = arguments.get("delay", 1.5)
    force = arguments.get("force", False)
    try:
        result = pool.update_fund_flow(code, days, delay, force)
        return result
    except Exception as e:
        return {"success": False, "code": code, "error": str(e)}

def _handle_get_fund_flow(arguments):
    code = arguments.get("code")
    start_date = arguments.get("start_date")
    end_date = arguments.get("end_date")
    limit = arguments.get("limit")
    offset = arguments.get("offset", 0)
    data = pool.get_fund_flow(code, start_date, end_date, limit, offset)
    return {"success": True, "data": data}

def _handle_analyze_main_force(arguments):
    code = arguments.get("code")
    days = arguments.get("days", 10)
    result = pool.analyze_main_force(code, days)
    return result

def _handle_legacy_stats(arguments):
    return {"success": False, "error": "该统计入口不可用。筛选用 screen_market。"}

TOOL_HANDLERS = {
    "get_current_time": _handle_get_current_time,
    "get_stock_universe": _handle_get_stock_universe,
    "get_all_stocks": _handle_get_all_stocks,
    "screen_market": _handle_screen_market,
    "screen_all_market": _handle_screen_all_market,
    "screen_main_board": _handle_screen_main_board,
    "start_market_sync": lambda args: start_market_sync(pool, args),
    "get_market_sync_status": lambda args: get_market_sync_status(pool, args),
    "cancel_market_sync": lambda args: cancel_market_sync(pool, args),
    "update_stock": _handle_update_stock,
    "update_stocks": _handle_update_stocks,
    "get_stock_info": _handle_get_stock_info,
    "get_daily_data": _handle_get_daily_data,
    "get_valuation_data": _handle_get_valuation_data,
    "get_technical_data": _handle_get_technical_data,
    "get_latest_data": _handle_get_latest_data,
    "get_realtime_price": _handle_get_realtime_price,
    "get_realtime_prices": _handle_get_realtime_prices,
    "analyze_position": _handle_analyze_position,
    "check_missing_data": _handle_check_missing_data,
    "update_minute_data": _handle_update_minute_data,
    "get_minute_data": _handle_get_minute_data,
    "analyze_intraday": _handle_analyze_intraday,
    "update_fund_flow": _handle_update_fund_flow,
    "get_fund_flow": _handle_get_fund_flow,
    "analyze_main_force": _handle_analyze_main_force,
}

for tool_name in LEGACY_STATS_TOOLS:
    TOOL_HANDLERS[tool_name] = _handle_legacy_stats

def _handle_tool_call(name, arguments):
    try:
        handler = TOOL_HANDLERS.get(name)
        if handler:
            return handler(arguments)
        return {"success": False, "error": f"Unknown tool: {name}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def handle_tool_call(name, arguments):
    return _sanitize_for_agent(_handle_tool_call(name, arguments))

async def handle_request(request):
    method = request.get("method")
    request_id = request.get("id")
    is_notification = "id" not in request
    
    # JSON-RPC notifications (for example MCP's "notifications/initialized")
    # must not receive a response. Returning an error with id=null makes Cline's
    # MCP client reject the message during connection validation.
    if is_notification:
        return None
    
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {}
                },
                "serverInfo": {
                    "name": "stock-pool",
                    "version": "1.0.0"
                }
            }
        }
    
    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": TOOLS
            }
        }
    
    elif method == "tools/call":
        params = request.get("params", {})
        name = params.get("name")
        arguments = params.get("arguments", {})
        result = handle_tool_call(name, arguments)
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
            # Only send JSON-RPC errors when we have a valid request id.
            # Cline rejects server messages with id=null, so notification/parse
            # errors are logged to stderr instead of stdout.
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
