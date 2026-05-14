"""
MCP工具定义 - 面向agent的精简接口

设计原则：
1. agent只需关心"要什么数据"，不需要关心"数据从哪来"、"怎么更新"
2. 所有数据获取自动刷新：缓存过期自动拉取，agent无需调用update
3. 内部重试/降级/缓存不暴露给agent，只返回最终结果
4. 错误提示明确：区分永久错误(代码错误)和临时错误(网络/限流)
5. 工具精简合并，减少agent的选择负担

工具分类（13个）：
- 系统工具: get_current_time
- 行情工具: get_realtime_quotes, get_daily_kline, get_minute_kline
- 分析工具: analyze_stock, analyze_position, analyze_intraday
- 数据工具: get_fund_flow, get_financial_data, get_latest_data, get_stock_detail
- 筛选工具: screen_market, get_stock_list
"""

TOOLS = [
    # ==================== 系统工具 ====================
    {
        "name": "get_current_time",
        "description": "返回北京时间、日期、交易日和交易时段。股票分析前先调用；默认截止日期取返回的 date。",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },

    # ==================== 行情工具 ====================
    {
        "name": "get_realtime_quotes",
        "description": "获取实时行情。支持单只或多只股票，最多20只。返回价格、涨跌幅、成交量等。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "codes": {
                    "description": "股票代码，可以是单个代码如 '601138' 或列表如 ['601138', '600487']，最多20只",
                    "oneOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}}
                    ]
                }
            },
            "required": ["codes"]
        }
    },
    {
        "name": "get_daily_kline",
        "description": "获取日K线数据。返回开高低收、成交量。数据自动刷新。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码"},
                "days": {"type": "integer", "description": "获取天数，默认250", "default": 250},
                "start_date": {"type": "string", "description": "开始日期，如 2024-01-01"},
                "end_date": {"type": "string", "description": "结束日期，如 2024-12-31"}
            },
            "required": ["code"]
        }
    },
    {
        "name": "get_minute_kline",
        "description": "获取分钟K线数据。返回开高低收、成交量。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码"},
                "klt": {"type": "integer", "description": "分钟周期: 1/5/15/30/60", "default": 5},
                "days": {"type": "integer", "description": "获取天数，默认5", "default": 5}
            },
            "required": ["code"]
        }
    },

    # ==================== 分析工具 ====================
    {
        "name": "analyze_stock",
        "description": "综合分析股票：技术面信号+收益风险指标+量价分析+支撑压力位+主力资金+估值评估。一次调用获取完整分析，无需分别查询多个工具。返回技术信号(金叉/死叉/超买超卖)、风险指标(夏普/索提诺/最大回撤)、支撑压力位、主力资金趋势、估值水平评估。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码"},
                "fund_flow_days": {"type": "integer", "description": "主力资金分析天数，默认10", "default": 10}
            },
            "required": ["code"]
        }
    },
    {
        "name": "analyze_position",
        "description": "分析股票52周位置。返回当前价格距离52周高低的百分比，判断是否处于低位。单次最多100只。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "codes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "股票代码列表，最多100只"
                }
            },
            "required": ["codes"]
        }
    },
    {
        "name": "analyze_intraday",
        "description": "分析单只股票日内走势。先调用 get_current_time 确认交易时段。非交易时间会返回明确错误提示。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码，如 603993"},
                "date": {"type": "string", "description": "分析日期，默认今天"}
            },
            "required": ["code"]
        }
    },

    # ==================== 资金流工具 ====================
    {
        "name": "get_fund_flow",
        "description": "获取资金流向数据及主力资金分析。返回主力/散户资金流入流出、连续流入/流出天数、趋势强度等。数据自动刷新。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码"},
                "start_date": {"type": "string", "description": "开始日期"},
                "end_date": {"type": "string", "description": "结束日期"},
                "limit": {"type": "integer", "description": "返回条数，默认10", "default": 10}
            },
            "required": ["code"]
        }
    },

    # ==================== 股票筛选工具 ====================
    {
        "name": "get_stock_list",
        "description": "获取板块股票列表。返回股票代码和名称。支持分页。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "board": {
                    "type": "string",
                    "description": "板块: a_share/main/gem/star/hs_a/bse",
                    "default": "a_share"
                },
                "page": {
                    "type": "integer",
                    "description": "页码，从1开始。不传则返回全部"
                },
                "page_size": {
                    "type": "integer",
                    "description": "每页数量，默认100，最大100",
                    "default": 100
                }
            }
        }
    },
    {
        "name": "screen_market",
        "description": "按估值、市值、52周位置筛选全市场股票。结果基于最近可用交易数据，可选补充实时行情。PE/PB/市值实时获取，52周位置基于历史数据计算。覆盖5000+只股票，需至少一个筛选条件。默认返回50条，最多200条；结果超过200条时用offset分页获取下一批。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "board": {"type": "string", "description": "板块：a_share/main/gem/star/hs_a/bse", "default": "a_share"},
                "position_min": {"type": "number", "description": "52周位置下限(%)"},
                "position_max": {"type": "number", "description": "52周位置上限(%)"},
                "pe_ttm_min": {"type": "number", "description": "市盈率TTM下限(正值，负PE即亏损自动排除)"},
                "pe_ttm_max": {"type": "number", "description": "市盈率TTM上限(正值，负PE即亏损自动排除)"},
                "pb_min": {"type": "number", "description": "市净率下限"},
                "pb_max": {"type": "number", "description": "市净率上限"},
                "market_cap_min": {"type": "number", "description": "总市值下限(亿)"},
                "market_cap_max": {"type": "number", "description": "总市值上限(亿)"},
                "sort_by": {"type": "string", "description": "排序字段: pe_ttm/position_pct/pb/market_cap/close/code/name", "default": "pe_ttm"},
                "sort_order": {"type": "string", "description": "排序方向: asc/desc", "default": "asc"},
                "limit": {"type": "integer", "description": "返回数量，默认50，最大200", "default": 50},
                "offset": {"type": "integer", "description": "分页偏移量", "default": 0},
                "include_realtime": {"type": "boolean", "description": "补实时行情", "default": False}
            }
        }
    },

    # ==================== 财务数据工具 ====================
    {
        "name": "get_financial_data",
        "description": "获取财务数据（利润表、资产负债表、现金流量表）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码"},
                "report_type": {
                    "type": "string",
                    "description": "报表类型: income/balance/cashflow",
                    "default": "income"
                }
            },
            "required": ["code"]
        }
    },

    # ==================== 综合数据工具 ====================
    {
        "name": "get_latest_data",
        "description": "查询指定股票最新综合数据（行情+估值+52周位置）。单次最多30只；大量请先筛选后分批。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "codes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "股票代码列表，最多30只"
                },
                "include_realtime": {"type": "boolean", "description": "包含实时行情", "default": False}
            },
            "required": ["codes"]
        }
    },
    {
        "name": "get_stock_detail",
        "description": "查询指定股票的综合详情，包括基本信息、最新行情和主力资金动向。一次调用获取完整画像，避免多次查询。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码"},
                "include_realtime": {"type": "boolean", "description": "包含实时行情", "default": True},
                "fund_flow_days": {"type": "integer", "description": "主力资金分析天数", "default": 10}
            },
            "required": ["code"]
        }
    },

]
