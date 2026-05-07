import asyncio
import json
import sys
import os
from datetime import datetime, timezone, timedelta

script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)
sys.path.insert(0, parent_dir)

from stock_pool import StockDataPool

pool = StockDataPool()
SHANGHAI_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")

TOOLS = [
    {
        "name": "get_current_time",
        "description": "获取当前准确时间，默认返回北京时间（Asia/Shanghai），便于确定数据分析截止日期",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "update_stock",
        "description": "按给定股票代码更新服务缓存（日K、估值、技术指标等），必要时从外部API拉取；如果缓存已是最新，则跳过更新；不会自动枚举全市场股票",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码，如 601138"},
                "days": {"type": "integer", "description": "拉取天数，默认250", "default": 250},
                "force": {"type": "boolean", "description": "强制更新，忽略缓存", "default": False}
            },
            "required": ["code"]
        }
    },
    {
        "name": "update_stocks",
        "description": "按给定股票代码列表批量更新服务缓存，必要时从外部API拉取；不会自动枚举全市场股票",
        "inputSchema": {
            "type": "object",
            "properties": {
                "codes": {"type": "array", "items": {"type": "string"}, "description": "股票代码列表"},
                "days": {"type": "integer", "description": "拉取天数，默认250", "default": 250}
            },
            "required": ["codes"]
        }
    },
    {
        "name": "get_stock_info",
        "description": "获取股票基本信息；服务会优先使用缓存，若该股票尚未更新过，可能返回空",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码"}
            },
            "required": ["code"]
        }
    },
    {
        "name": "get_daily_data",
        "description": "获取指定股票的日K线数据；服务会优先使用缓存，若需分析新股票，请先调用 update_stock/update_stocks 更新缓存",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码"},
                "start_date": {"type": "string", "description": "开始日期，如 2025-01-01"},
                "end_date": {"type": "string", "description": "结束日期，如 2026-05-06"},
                "limit": {"type": "integer", "description": "限制条数"}
            },
            "required": ["code"]
        }
    },
    {
        "name": "get_valuation_data",
        "description": "获取指定股票估值数据（PE、PB等）；服务会优先使用缓存，若需分析新股票，请先调用 update_stock/update_stocks 更新缓存",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码"},
                "start_date": {"type": "string", "description": "开始日期"},
                "end_date": {"type": "string", "description": "结束日期"}
            },
            "required": ["code"]
        }
    },
    {
        "name": "get_technical_data",
        "description": "获取指定股票技术指标数据（MA、位置等）；技术指标由 update_stock/update_stocks 基于已缓存日K计算",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码"},
                "start_date": {"type": "string", "description": "开始日期"},
                "end_date": {"type": "string", "description": "结束日期"}
            },
            "required": ["code"]
        }
    },
    {
        "name": "get_latest_data",
        "description": "获取给定股票列表的最新综合数据；服务会优先使用缓存，仅返回已有可用数据的股票，不会自动扩展到全市场",
        "inputSchema": {
            "type": "object",
            "properties": {
                "codes": {"type": "array", "items": {"type": "string"}, "description": "股票代码列表"}
            },
            "required": ["codes"]
        }
    },
    {
        "name": "get_realtime_price",
        "description": "按给定股票代码实时获取当前价格和估值，直接调用外部API，不使用服务缓存；不支持自动发现股票代码",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码，如 601138"}
            },
            "required": ["code"]
        }
    },
    {
        "name": "get_realtime_prices",
        "description": "按给定股票代码列表批量实时获取当前价格和估值，直接调用外部API，不使用服务缓存；不支持自动发现股票代码",
        "inputSchema": {
            "type": "object",
            "properties": {
                "codes": {"type": "array", "items": {"type": "string"}, "description": "股票代码列表"},
                "delay": {"type": "number", "description": "每只股票请求间隔秒数，默认0.2", "default": 0.2}
            },
            "required": ["codes"]
        }
    },
    {
        "name": "analyze_position",
        "description": "基于给定股票列表的可用历史数据分析52周位置，返回低位/中位/高位分类；服务会优先使用缓存；不是全市场筛选器",
        "inputSchema": {
            "type": "object",
            "properties": {
                "codes": {"type": "array", "items": {"type": "string"}, "description": "股票代码列表"}
            },
            "required": ["codes"]
        }
    },
    {
        "name": "check_missing_data",
        "description": "检查给定股票列表在服务缓存中的日K数据是否缺失，可用于判断是否需要先 update_stock/update_stocks",
        "inputSchema": {
            "type": "object",
            "properties": {
                "codes": {"type": "array", "items": {"type": "string"}, "description": "股票代码列表"},
                "start_date": {"type": "string", "description": "开始日期"},
                "end_date": {"type": "string", "description": "结束日期"}
            },
            "required": ["codes", "start_date", "end_date"]
        }
    },
    {
        "name": "get_cache_stats",
        "description": "获取服务内部缓存统计信息，可用于了解当前缓存覆盖了多少股票和数据范围",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "update_minute_data",
        "description": "按给定股票代码更新服务的分钟K线缓存，必要时从外部API拉取。如果缓存已是最新（5分钟内），则跳过更新；不会自动枚举全市场股票",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码，如 603993"},
                "klt": {"type": "integer", "description": "K线类型：1=1分钟，5=5分钟，15=15分钟，30=30分钟，60=60分钟", "default": 5},
                "days": {"type": "integer", "description": "拉取天数，默认5", "default": 5},
                "force": {"type": "boolean", "description": "强制更新，忽略缓存", "default": False}
            },
            "required": ["code"]
        }
    },
    {
        "name": "get_minute_data",
        "description": "获取指定股票分钟K线数据；服务会优先使用缓存，若需分析新股票，请先调用 update_minute_data 更新缓存",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码"},
                "klt": {"type": "integer", "description": "K线类型：1=1分钟，5=5分钟，15=15分钟，30=30分钟，60=60分钟", "default": 5},
                "start_time": {"type": "string", "description": "开始时间，如 2026-05-07 09:30"},
                "end_time": {"type": "string", "description": "结束时间，如 2026-05-07 15:00"},
                "limit": {"type": "integer", "description": "限制条数"}
            },
            "required": ["code"]
        }
    },
    {
        "name": "analyze_intraday",
        "description": "基于指定股票的可用日K、技术指标和分钟K线分析日内走势；服务会优先使用缓存，若数据为空，请先 update_stock 和 update_minute_data",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码，如 603993"},
                "date": {"type": "string", "description": "分析日期，如 2026-05-07，默认今天"}
            },
            "required": ["code"]
        }
    }
]

def handle_tool_call(name, arguments):
    try:
        if name == "get_current_time":
            now = datetime.now(SHANGHAI_TZ)
            return {
                "success": True,
                "data": {
                    "timezone": "Asia/Shanghai",
                    "utc_offset": "+08:00",
                    "datetime": now.isoformat(timespec="seconds"),
                    "date": now.date().isoformat(),
                    "time": now.time().isoformat(timespec="seconds"),
                    "timestamp": int(now.timestamp())
                }
            }

        elif name == "update_stock":
            code = arguments.get("code")
            days = arguments.get("days", 250)
            force = arguments.get("force", False)
            pool.update_stock(code, days, force=force)
            return {"success": True, "message": f"已更新 {code}"}
        
        elif name == "update_stocks":
            codes = arguments.get("codes", [])
            days = arguments.get("days", 250)
            result = pool.update_stocks(codes, days)
            return {"success": True, "result": result}
        
        elif name == "get_stock_info":
            code = arguments.get("code")
            data = pool.get_stock_info(code)
            return {"success": True, "data": data}
        
        elif name == "get_daily_data":
            code = arguments.get("code")
            start_date = arguments.get("start_date")
            end_date = arguments.get("end_date")
            limit = arguments.get("limit")
            data = pool.get_daily_data(code, start_date, end_date, limit)
            return {"success": True, "data": data}
        
        elif name == "get_valuation_data":
            code = arguments.get("code")
            start_date = arguments.get("start_date")
            end_date = arguments.get("end_date")
            data = pool.get_valuation_data(code, start_date, end_date)
            return {"success": True, "data": data}
        
        elif name == "get_technical_data":
            code = arguments.get("code")
            start_date = arguments.get("start_date")
            end_date = arguments.get("end_date")
            data = pool.get_technical_data(code, start_date, end_date)
            return {"success": True, "data": data}
        
        elif name == "get_latest_data":
            codes = arguments.get("codes", [])
            data = pool.get_latest_data(codes)
            return {"success": True, "data": data}
        
        elif name == "get_realtime_price":
            code = arguments.get("code")
            data = pool.get_realtime_price(code)
            return {"success": True, "data": data}
        
        elif name == "get_realtime_prices":
            codes = arguments.get("codes", [])
            delay = arguments.get("delay", 0.2)
            data = pool.get_realtime_prices(codes, delay=delay)
            return {"success": True, "data": data}
        
        elif name == "analyze_position":
            codes = arguments.get("codes", [])
            data = pool.analyze_position(codes)
            return {"success": True, "data": data}
        
        elif name == "check_missing_data":
            codes = arguments.get("codes", [])
            start_date = arguments.get("start_date")
            end_date = arguments.get("end_date")
            data = pool.check_missing_data(codes, start_date, end_date)
            return {"success": True, "data": data}
        
        elif name in ("get_cache_stats", "get_db_stats"):
            data = pool.get_db_stats()
            return {"success": True, "data": data}
        
        elif name == "update_minute_data":
            code = arguments.get("code")
            klt = arguments.get("klt", 5)
            days = arguments.get("days", 5)
            force = arguments.get("force", False)
            pool.update_minute_data(code, klt, days, force=force)
            return {"success": True, "message": f"已更新 {code} {klt}分钟K线"}
        
        elif name == "get_minute_data":
            code = arguments.get("code")
            klt = arguments.get("klt", 5)
            start_time = arguments.get("start_time")
            end_time = arguments.get("end_time")
            limit = arguments.get("limit")
            data = pool.get_minute_data(code, klt, start_time, end_time, limit)
            return {"success": True, "data": data}
        
        elif name == "analyze_intraday":
            code = arguments.get("code")
            date = arguments.get("date")
            result = pool.analyze_intraday(code, date)
            return result
        
        else:
            return {"success": False, "error": f"Unknown tool: {name}"}
    
    except Exception as e:
        return {"success": False, "error": str(e)}

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
