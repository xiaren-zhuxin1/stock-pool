"""
MCP工具定义 - 按数据类型聚合

工具分类：
1. 系统工具 - get_current_time, get_provider_status, get_db_stats
2. 行情工具 - get_realtime_quote, get_realtime_quotes, get_daily_kline, get_minute_kline
3. 估值工具 - get_valuation, analyze_position
4. 资金流工具 - get_fund_flow, analyze_main_force
5. 股票筛选工具 - get_stock_list, screen_market, screen_all_market, screen_main_board
6. 数据管理工具 - update_stock, update_stocks, update_minute_data, update_fund_flow, start_market_sync, get_sync_status, cancel_sync, check_missing_data
7. 技术指标工具 - get_technical_indicators
8. 财务数据工具 - get_financial_data
9. 综合数据工具 - get_latest_data, get_stock_info
10. 日内分析工具 - analyze_intraday
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
    {
        "name": "get_provider_status",
        "description": "查询所有数据源状态，包括可用性、优先级、错误信息。用于诊断数据获取问题。",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_db_stats",
        "description": "查询数据库统计信息，包括各表记录数、日期范围等。",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },

    # ==================== 行情工具 ====================
    {
        "name": "get_realtime_quote",
        "description": "获取单只股票实时行情。支持多数据源自动降级：东方财富 -> 新浪 -> AkShare -> 腾讯 -> 网易。返回价格、涨跌幅、成交量等。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码，如 601138"},
                "providers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "指定数据源顺序，如 ['eastmoney', 'akshare']。默认自动选择。"
                }
            },
            "required": ["code"]
        }
    },
    {
        "name": "get_realtime_quotes",
        "description": "批量获取实时行情。单次最多20只。支持多数据源自动降级。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "codes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "股票代码列表，最多20只"
                },
                "delay": {"type": "number", "description": "请求间隔秒，默认0.2", "default": 0.2}
            },
            "required": ["codes"]
        }
    },
    {
        "name": "get_daily_kline",
        "description": "获取日K线数据。支持多数据源自动降级：东方财富 -> 新浪 -> AkShare -> 腾讯 -> 网易 -> TuShare -> Baostock。返回开高低收、成交量。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码"},
                "days": {"type": "integer", "description": "获取天数，默认250", "default": 250},
                "start_date": {"type": "string", "description": "开始日期，如 2024-01-01"},
                "end_date": {"type": "string", "description": "结束日期，如 2024-12-31"},
                "providers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "指定数据源顺序"
                }
            },
            "required": ["code"]
        }
    },
    {
        "name": "get_minute_kline",
        "description": "获取分钟K线数据。支持多数据源自动降级：东方财富 -> AkShare -> 腾讯 -> TuShare -> Baostock。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码"},
                "klt": {"type": "integer", "description": "分钟周期: 1/5/15/30/60", "default": 5},
                "days": {"type": "integer", "description": "获取天数，默认5", "default": 5},
                "providers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "指定数据源顺序"
                }
            },
            "required": ["code"]
        }
    },

    # ==================== 估值工具 ====================
    {
        "name": "get_valuation",
        "description": "获取股票估值数据（PE、PB、市值等）。支持多数据源自动降级：东方财富 -> AkShare -> TuShare -> Baostock。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码"},
                "start_date": {"type": "string", "description": "开始日期"},
                "end_date": {"type": "string", "description": "结束日期"},
                "limit": {"type": "integer", "description": "返回条数"},
                "providers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "指定数据源顺序"
                }
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

    # ==================== 资金流工具 ====================
    {
        "name": "get_fund_flow",
        "description": "获取资金流向数据。支持多数据源自动降级：东方财富 -> AkShare。返回主力、散户资金流入流出。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码"},
                "start_date": {"type": "string", "description": "开始日期"},
                "end_date": {"type": "string", "description": "结束日期"},
                "limit": {"type": "integer", "description": "返回条数"},
                "providers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "指定数据源顺序"
                }
            },
            "required": ["code"]
        }
    },
    {
        "name": "analyze_main_force",
        "description": "分析主力资金动向。返回连续流入/流出天数、趋势强度等。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码"},
                "days": {"type": "integer", "description": "分析天数，默认10", "default": 10}
            },
            "required": ["code"]
        }
    },

    # ==================== 股票筛选工具 ====================
    {
        "name": "get_stock_list",
        "description": "获取板块股票列表。支持多数据源自动降级：东方财富 -> AkShare -> TuShare -> Baostock。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "board": {
                    "type": "string",
                    "description": "板块: a_share/main/gem/star/sh_main/sz_main/bse",
                    "default": "a_share"
                },
                "providers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "指定数据源顺序"
                }
            }
        }
    },
    {
        "name": "get_stock_universe",
        "description": "分页获取板块候选股票代码。返回股票代码和基本信息，支持分页。",
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
                    "description": "页码，从1开始",
                    "default": 1
                },
                "page_size": {
                    "type": "integer",
                    "description": "每页数量，默认100，最大100",
                    "default": 100
                },
                "limit": {
                    "type": "integer",
                    "description": "总数量限制（page为空时生效）"
                }
            }
        }
    },
    {
        "name": "get_all_stocks",
        "description": "一次性获取板块所有股票代码。适用场景：需要完整股票清单，不希望分页。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "board": {
                    "type": "string",
                    "description": "板块: a_share/main/gem/star/hs_a/bse",
                    "default": "a_share"
                }
            }
        }
    },
    {
        "name": "screen_market",
        "description": "按52周位置、估值、市值筛选股票。需至少一个筛选条件。分页说明：默认返回50条，最多200条。结果超过200条时使用offset分页。重要：筛选前需要先更新股票数据。如果返回matched_count=0，可能是因为没有数据，请先用start_market_sync更新数据。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "board": {"type": "string", "description": "板块：a_share/main/gem/star/hs_a/bse", "default": "a_share"},
                "position_min": {"type": "number", "description": "52周位置下限"},
                "position_max": {"type": "number", "description": "52周位置上限"},
                "pe_ttm_min": {"type": "number", "description": "市盈率TTM下限"},
                "pe_ttm_max": {"type": "number", "description": "市盈率TTM上限"},
                "pb_min": {"type": "number", "description": "市净率下限"},
                "pb_max": {"type": "number", "description": "市净率上限"},
                "market_cap_min": {"type": "number", "description": "总市值下限(亿)"},
                "market_cap_max": {"type": "number", "description": "总市值上限(亿)"},
                "sort_by": {"type": "string", "description": "排序字段: position_pct/pe_ttm/pb/market_cap/close/code/date", "default": "position_pct"},
                "sort_order": {"type": "string", "description": "排序方向: asc/desc", "default": "asc"},
                "limit": {"type": "integer", "description": "返回数量，默认50，最大200", "default": 50},
                "offset": {"type": "integer", "description": "分页偏移量", "default": 0},
                "refresh": {"type": "string", "description": "刷新策略: none/missing/stale/force", "default": "none"},
                "max_refresh": {"type": "integer", "description": "更新上限，最大200"},
                "days": {"type": "integer", "description": "日K天数，默认250", "default": 250},
                "include_realtime": {"type": "boolean", "description": "补实时行情", "default": False},
                "realtime_limit": {"type": "integer", "description": "实时补价上限，默认20，最大50", "default": 20},
                "batch_size": {"type": "integer", "description": "批大小，默认200，最大500", "default": 200},
                "background": {"type": "boolean", "description": "强制后台执行", "default": False}
            }
        }
    },
    {
        "name": "screen_all_market",
        "description": "筛选所有符合条件的股票，无数量限制。自动后台执行，返回job_id后用get_sync_status查进度。工作流程：1. 调用screen_all_market设置筛选条件，获得job_id；2. 用get_sync_status(job_id)查询进度，等待status='completed'；3. 从result字段获取完整筛选结果。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "board": {"type": "string", "description": "板块", "default": "a_share"},
                "position_min": {"type": "number", "description": "52周位置下限"},
                "position_max": {"type": "number", "description": "52周位置上限"},
                "pe_ttm_min": {"type": "number", "description": "市盈率TTM下限"},
                "pe_ttm_max": {"type": "number", "description": "市盈率TTM上限"},
                "pb_min": {"type": "number", "description": "市净率下限"},
                "pb_max": {"type": "number", "description": "市净率上限"},
                "market_cap_min": {"type": "number", "description": "总市值下限(亿)"},
                "market_cap_max": {"type": "number", "description": "总市值上限(亿)"},
                "sort_by": {"type": "string", "description": "排序字段", "default": "position_pct"},
                "sort_order": {"type": "string", "description": "排序方向", "default": "asc"}
            }
        }
    },
    {
        "name": "screen_main_board",
        "description": "按52周位置、估值、市值筛选沪深主板。需至少一个筛选条件。分页说明同screen_market。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "board": {"type": "string", "description": "板块: main/sh_main/sz_main", "default": "main"},
                "position_min": {"type": "number", "description": "52周位置下限"},
                "position_max": {"type": "number", "description": "52周位置上限"},
                "pe_ttm_min": {"type": "number", "description": "市盈率TTM下限"},
                "pe_ttm_max": {"type": "number", "description": "市盈率TTM上限"},
                "pb_min": {"type": "number", "description": "市净率下限"},
                "pb_max": {"type": "number", "description": "市净率上限"},
                "market_cap_min": {"type": "number", "description": "总市值下限(亿)"},
                "market_cap_max": {"type": "number", "description": "总市值上限(亿)"},
                "sort_by": {"type": "string", "description": "排序字段", "default": "position_pct"},
                "sort_order": {"type": "string", "description": "排序方向: asc/desc", "default": "asc"},
                "limit": {"type": "integer", "description": "返回数量，默认50，最大200", "default": 50},
                "offset": {"type": "integer", "description": "分页偏移", "default": 0},
                "refresh": {"type": "string", "description": "刷新策略: none/missing/stale/force", "default": "none"},
                "max_refresh": {"type": "integer", "description": "更新上限，最大200"},
                "days": {"type": "integer", "description": "日K天数，默认250", "default": 250},
                "include_realtime": {"type": "boolean", "description": "补实时行情", "default": False},
                "realtime_limit": {"type": "integer", "description": "实时补价上限，默认20", "default": 20},
                "batch_size": {"type": "integer", "description": "批大小，默认200", "default": 200},
                "background": {"type": "boolean", "description": "强制后台执行", "default": False}
            }
        }
    },

    # ==================== 数据管理工具 ====================
    {
        "name": "update_stock",
        "description": "更新单只股票数据（K线、估值、技术指标）。从多个数据源获取并缓存。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码"},
                "days": {"type": "integer", "description": "获取天数，默认250", "default": 250},
                "force": {"type": "boolean", "description": "强制刷新", "default": False}
            },
            "required": ["code"]
        }
    },
    {
        "name": "update_stocks",
        "description": "批量更新股票数据。最多50只。超过10只自动后台执行。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "codes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "股票代码列表，最多50只"
                },
                "days": {"type": "integer", "description": "获取天数", "default": 250},
                "force": {"type": "boolean", "description": "强制刷新", "default": False}
            },
            "required": ["codes"]
        }
    },
    {
        "name": "update_minute_data",
        "description": "更新单只股票分钟K线；可带 start_time/end_time 检查目标区间是否可用。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码，如 603993"},
                "klt": {"type": "integer", "description": "1/5/15/30/60分钟", "default": 5},
                "days": {"type": "integer", "description": "天数，默认5", "default": 5},
                "force": {"type": "boolean", "description": "强制刷新", "default": False},
                "start_time": {"type": "string", "description": "目标开始时间"},
                "end_time": {"type": "string", "description": "目标结束时间"}
            },
            "required": ["code"]
        }
    },
    {
        "name": "update_fund_flow",
        "description": "更新单只股票资金流向数据。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码，如 601138"},
                "days": {"type": "integer", "description": "天数，默认100", "default": 100},
                "force": {"type": "boolean", "description": "强制刷新", "default": False}
            },
            "required": ["code"]
        }
    },
    {
        "name": "start_market_sync",
        "description": "启动板块数据同步任务。后台执行，返回job_id后用get_sync_status查进度。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "board": {"type": "string", "description": "板块：a_share/main/gem/star/hs_a/bse", "default": "a_share"},
                "refresh": {"type": "string", "description": "刷新策略: missing/stale/force", "default": "stale"},
                "days": {"type": "integer", "description": "历史天数，默认250", "default": 250},
                "max_codes": {"type": "integer", "description": "处理上限；试跑用"},
                "delay": {"type": "number", "description": "单股请求间隔秒，默认0.2", "default": 0.2}
            }
        }
    },
    {
        "name": "get_sync_status",
        "description": "查询同步任务状态。传 job_id 查单个任务，不传则列出最近任务。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "任务ID"},
                "limit": {"type": "integer", "description": "返回数，默认20", "default": 20},
                "offset": {"type": "integer", "description": "分页偏移", "default": 0}
            }
        }
    },
    {
        "name": "cancel_sync",
        "description": "取消运行中的同步任务。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "任务ID"}
            },
            "required": ["job_id"]
        }
    },
    {
        "name": "check_missing_data",
        "description": "检查指定股票日K缺失。单次最多200只。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "codes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "股票代码列表，最多200只"
                },
                "start_date": {"type": "string", "description": "开始日期"},
                "end_date": {"type": "string", "description": "结束日期"}
            },
            "required": ["codes", "start_date", "end_date"]
        }
    },

    # ==================== 技术指标工具 ====================
    {
        "name": "get_technical_indicators",
        "description": "获取技术指标（均线、MACD、KDJ、BOLL等）。需要先更新数据。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码"},
                "start_date": {"type": "string", "description": "开始日期"},
                "end_date": {"type": "string", "description": "结束日期"},
                "limit": {"type": "integer", "description": "返回条数"}
            },
            "required": ["code"]
        }
    },

    # ==================== 财务数据工具 ====================
    {
        "name": "get_financial_data",
        "description": "获取财务数据（利润表、资产负债表、现金流量表）。支持多数据源：TuShare -> AkShare。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码"},
                "report_type": {
                    "type": "string",
                    "description": "报表类型: income/balance/cashflow",
                    "default": "income"
                },
                "providers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "指定数据源顺序"
                }
            },
            "required": ["code"]
        }
    },

    # ==================== 综合数据工具 ====================
    {
        "name": "get_latest_data",
        "description": "查询指定股票最新综合数据。单次最多30只；大量请先筛选后分批，避免超时、内存压力和关键信息淹没。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "codes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "股票代码列表，最多30只"
                },
                "include_realtime": {"type": "boolean", "description": "包含实时行情", "default": False},
                "realtime_limit": {"type": "integer", "description": "实时补价上限"},
                "batch_size": {"type": "integer", "description": "批大小，默认200", "default": 200}
            },
            "required": ["codes"]
        }
    },
    {
        "name": "get_stock_info",
        "description": "查询股票基本信息。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码"}
            },
            "required": ["code"]
        }
    },

    # ==================== 日内分析工具 ====================
    {
        "name": "analyze_intraday",
        "description": "分析单只股票日内走势；先调用 get_current_time。失败时按 resolution 调用工具或等待，不要改用其他日期。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码，如 603993"},
                "date": {"type": "string", "description": "分析日期，默认今天"}
            },
            "required": ["code"]
        }
    },
]
