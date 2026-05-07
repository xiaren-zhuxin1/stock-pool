import asyncio
import json
import sys
import os

script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)
sys.path.insert(0, parent_dir)

from stock_pool import StockDataPool

pool = StockDataPool()

TOOLS = [
    {
        "name": "update_stock",
        "description": "更新股票数据，从API拉取K线、估值等数据。如果数据已是最新，则跳过更新",
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
        "description": "批量更新多只股票数据",
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
        "description": "获取股票基本信息",
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
        "description": "获取股票日K线数据",
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
        "description": "获取股票估值数据（PE、PB等）",
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
        "description": "获取股票技术指标数据（MA、位置等）",
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
        "description": "获取多只股票的最新数据（综合信息）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "codes": {"type": "array", "items": {"type": "string"}, "description": "股票代码列表"}
            },
            "required": ["codes"]
        }
    },
    {
        "name": "analyze_position",
        "description": "分析股票52周位置，返回低位/中位/高位分类",
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
        "description": "检查股票数据是否缺失",
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
        "name": "get_db_stats",
        "description": "获取数据库统计信息",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "update_minute_data",
        "description": "更新股票分钟K线数据。如果数据已是最新（5分钟内），则跳过更新",
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
        "description": "获取股票分钟K线数据",
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
        "description": "分析股票日内走势，包括上午复盘、下午预测和概率计算",
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
        if name == "update_stock":
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
        
        elif name == "get_db_stats":
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
    
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request.get("id"),
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
            "id": request.get("id"),
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
            "id": request.get("id"),
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
            "id": request.get("id"),
            "error": {
                "code": -32601,
                "message": f"Method not found: {method}"
            }
        }

async def main():
    while True:
        try:
            line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
            if not line:
                break
            
            request = json.loads(line.strip())
            response = await handle_request(request)
            print(json.dumps(response), flush=True)
        
        except json.JSONDecodeError:
            continue
        except Exception as e:
            error_response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32603,
                    "message": str(e)
                }
            }
            print(json.dumps(error_response), flush=True)

if __name__ == "__main__":
    asyncio.run(main())
