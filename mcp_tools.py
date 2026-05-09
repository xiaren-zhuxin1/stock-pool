TOOLS = [
    {
        "name": "get_current_time",
        "description": "返回北京时间、日期、交易日和交易时段。股票分析前先调用；默认截止日期取返回的 date。",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_stock_universe",
        "description": "原生分页返回板块候选代码。筛选用 screen_market。分页说明：板块股票数通常超过100只，需要分页获取。使用page参数分页（从1开始），每页最多100条。示例：page=1获取前100只，page=2获取101-200只。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "board": {"type": "string", "description": "板块：a_share/main/gem/star/hs_a/bse", "default": "a_share"},
                "page": {"type": "integer", "description": "页码，从1开始。不传则返回limit指定的数量"},
                "page_size": {"type": "integer", "description": "每页数量，默认100，最大100", "default": 100},
                "limit": {"type": "integer", "description": "总数量限制（page为空时生效）"}
            }
        }
    },
    {
        "name": "get_all_stocks",
        "description": "一次性获取板块所有股票代码。适用场景：需要完整股票清单，不希望分页。返回所有股票代码和基本信息，可能耗时较长。建议在需要完整数据时使用，否则用get_stock_universe分页获取。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "board": {"type": "string", "description": "板块：a_share/main/gem/star/hs_a/bse", "default": "a_share"}
            }
        }
    },
    {
        "name": "screen_market",
        "description": "按板块、52周位置、估值、市值筛选股票。需至少一个筛选条件；全市场初筛首选。分页说明：默认返回50条，最多200条。结果超过200条时使用offset分页：offset=0获取1-50条，offset=50获取51-100条，以此类推。建议先用默认limit=50查看结果数量，再决定是否需要分页。",
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
                "market_cap_min": {"type": "number", "description": "总市值下限"},
                "market_cap_max": {"type": "number", "description": "总市值上限"},
                "sort_by": {"type": "string", "description": "position_pct/pe_ttm/pb/market_cap/close/code/date", "default": "position_pct"},
                "sort_order": {"type": "string", "description": "asc/desc", "default": "asc"},
                "limit": {"type": "integer", "description": "返回数量，默认50，最大200", "default": 50},
                "offset": {"type": "integer", "description": "分页偏移量。offset=0从第1条开始，offset=50从第51条开始", "default": 0},
                "universe_limit": {"type": "integer", "description": "候选检查上限；试跑用"},
                "refresh": {"type": "string", "description": "none/missing/stale/force", "default": "none"},
                "max_refresh": {"type": "integer", "description": "更新上限；最大200"},
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
        "description": "筛选所有符合条件的股票，无数量限制。适用场景：需要完整筛选结果，不希望分页。自动后台执行，返回job_id后用get_market_sync_status查进度。建议在筛选结果可能很多时使用，否则用screen_market分页获取。",
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
                "market_cap_min": {"type": "number", "description": "总市值下限"},
                "market_cap_max": {"type": "number", "description": "总市值上限"},
                "sort_by": {"type": "string", "description": "position_pct/pe_ttm/pb/market_cap/close/code/date", "default": "position_pct"},
                "sort_order": {"type": "string", "description": "asc/desc", "default": "asc"},
                "refresh": {"type": "string", "description": "none/missing/stale/force", "default": "none"},
                "max_refresh": {"type": "integer", "description": "更新上限；最大200"},
                "days": {"type": "integer", "description": "日K天数，默认250", "default": 250}
            }
        }
    },
    {
        "name": "screen_main_board",
        "description": "按52周位置、估值、市值筛选沪深主板。需至少一个筛选条件。分页说明：默认返回50条，最多200条。结果超过200条时使用offset分页：offset=0获取1-50条，offset=50获取51-100条。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "board": {"type": "string", "description": "main/sh_main/sz_main", "default": "main"},
                "position_min": {"type": "number", "description": "52周位置下限"},
                "position_max": {"type": "number", "description": "52周位置上限"},
                "pe_ttm_min": {"type": "number", "description": "市盈率TTM下限"},
                "pe_ttm_max": {"type": "number", "description": "市盈率TTM上限"},
                "pb_min": {"type": "number", "description": "市净率下限"},
                "pb_max": {"type": "number", "description": "市净率上限"},
                "market_cap_min": {"type": "number", "description": "总市值下限"},
                "market_cap_max": {"type": "number", "description": "总市值上限"},
                "sort_by": {"type": "string", "description": "position_pct/pe_ttm/pb/market_cap/close/code/date", "default": "position_pct"},
                "sort_order": {"type": "string", "description": "asc/desc", "default": "asc"},
                "limit": {"type": "integer", "description": "返回数量，默认50，最大200", "default": 50},
                "offset": {"type": "integer", "description": "分页偏移量。offset=0从第1条开始，offset=50从第51条开始", "default": 0},
                "universe_limit": {"type": "integer", "description": "候选检查上限；试跑用"},
                "refresh": {"type": "string", "description": "none/missing/stale/force", "default": "none"},
                "max_refresh": {"type": "integer", "description": "更新上限；最大200"},
                "days": {"type": "integer", "description": "日K天数，默认250", "default": 250},
                "include_realtime": {"type": "boolean", "description": "补实时行情", "default": False},
                "realtime_limit": {"type": "integer", "description": "实时补价上限，默认20，最大50", "default": 20},
                "batch_size": {"type": "integer", "description": "批大小，默认200，最大500", "default": 200},
                "background": {"type": "boolean", "description": "强制后台执行", "default": False}
            }
        }
    },
    {
        "name": "start_market_sync",
        "description": "启动板块数据同步任务，返回 job_id 和进度。不返回股票详情。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "board": {"type": "string", "description": "板块：a_share/main/gem/star/hs_a/bse", "default": "a_share"},
                "refresh": {"type": "string", "description": "missing/stale/force", "default": "stale"},
                "max_codes": {"type": "integer", "description": "处理上限；试跑用"},
                "days": {"type": "integer", "description": "历史天数，默认250", "default": 250},
                "delay": {"type": "number", "description": "单股请求间隔秒，默认0.2", "default": 0.2}
            }
        }
    },
    {
        "name": "get_market_sync_status",
        "description": "分页查询同步任务；传 job_id 查单个任务。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "同步任务ID"},
                "limit": {"type": "integer", "description": "返回数，默认20，最大100", "default": 20},
                "offset": {"type": "integer", "description": "分页偏移", "default": 0}
            }
        }
    },
    {
        "name": "cancel_market_sync",
        "description": "取消运行中的同步任务。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "同步任务ID"}
            },
            "required": ["job_id"]
        }
    },
    {
        "name": "update_stock",
        "description": "更新单只股票日K、估值和技术指标。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码，如 601138"},
                "days": {"type": "integer", "description": "天数，默认250", "default": 250},
                "force": {"type": "boolean", "description": "强制刷新", "default": False}
            },
            "required": ["code"]
        }
    },
    {
        "name": "update_stocks",
        "description": "批量更新指定股票。最多50只；超过10只自动后台执行，返回 job_id 后用 get_market_sync_status 查进度。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "codes": {"type": "array", "items": {"type": "string"}, "description": "股票代码列表"},
                "days": {"type": "integer", "description": "天数，默认250", "default": 250},
                "delay": {"type": "number", "description": "单股请求间隔秒，默认1.5", "default": 1.5}
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
    {
        "name": "get_daily_data",
        "description": "分页查询日K线。空结果先调用 update_stock。分页说明：默认返回全部数据，可用limit限制数量。数据量大时建议分页：limit=100, offset=0获取前100条，offset=100获取101-200条。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码"},
                "start_date": {"type": "string", "description": "开始日期，如 2025-01-01"},
                "end_date": {"type": "string", "description": "结束日期，如 2026-05-06"},
                "limit": {"type": "integer", "description": "返回条数上限。不传则返回全部"},
                "offset": {"type": "integer", "description": "分页偏移量。offset=0从第1条开始，offset=100从第101条开始", "default": 0}
            },
            "required": ["code"]
        }
    },
    {
        "name": "get_valuation_data",
        "description": "分页查询 PE、PB 等估值数据。空结果先调用 update_stock。分页说明：默认返回全部数据，可用limit限制数量。数据量大时建议分页：limit=100, offset=0获取前100条。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码"},
                "start_date": {"type": "string", "description": "开始日期"},
                "end_date": {"type": "string", "description": "结束日期"},
                "limit": {"type": "integer", "description": "返回条数上限。不传则返回全部"},
                "offset": {"type": "integer", "description": "分页偏移量。offset=0从第1条开始", "default": 0}
            },
            "required": ["code"]
        }
    },
    {
        "name": "get_technical_data",
        "description": "分页查询均线、52周位置等技术指标。空结果先调用 update_stock。分页说明：默认返回全部数据，可用limit限制数量。数据量大时建议分页：limit=100, offset=0获取前100条。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码"},
                "start_date": {"type": "string", "description": "开始日期"},
                "end_date": {"type": "string", "description": "结束日期"},
                "limit": {"type": "integer", "description": "返回条数上限。不传则返回全部"},
                "offset": {"type": "integer", "description": "分页偏移量。offset=0从第1条开始", "default": 0}
            },
            "required": ["code"]
        }
    },
    {
        "name": "get_latest_data",
        "description": "查询指定股票最新综合数据。单次最多30只；大量请先筛选后分批，避免超时、内存压力和关键信息淹没。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "codes": {"type": "array", "items": {"type": "string"}, "description": "股票代码列表"},
                "include_realtime": {"type": "boolean", "description": "补实时行情", "default": False},
                "realtime_limit": {"type": "integer", "description": "实时补价上限"},
                "batch_size": {"type": "integer", "description": "批大小，默认200，最大500", "default": 200}
            },
            "required": ["codes"]
        }
    },
    {
        "name": "get_realtime_price",
        "description": "查询单只股票实时行情。",
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
        "description": "批量查询实时行情。单次最多20只；大量请分批，避免超时、内存压力和关键信息淹没。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "codes": {"type": "array", "items": {"type": "string"}, "description": "股票代码列表"},
                "delay": {"type": "number", "description": "请求间隔秒，默认0.2", "default": 0.2}
            },
            "required": ["codes"]
        }
    },
    {
        "name": "analyze_position",
        "description": "分析指定股票52周位置。单次最多100只；大量请分批，避免关键信息淹没。",
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
        "description": "检查指定股票日K缺失。单次最多200只；大量请分批，避免超时。",
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
        "name": "get_minute_data",
        "description": "分页查询分钟K线。空结果按 resolution 调用 update_minute_data 或停止重试。分页说明：分钟数据量大，建议用start_time/end_time限定范围，或用limit分页：limit=500, offset=0获取前500条。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码"},
                "klt": {"type": "integer", "description": "1/5/15/30/60分钟", "default": 5},
                "start_time": {"type": "string", "description": "开始时间，如 2026-05-07 09:30"},
                "end_time": {"type": "string", "description": "结束时间，如 2026-05-07 15:00"},
                "limit": {"type": "integer", "description": "返回条数上限。不传则返回全部"},
                "offset": {"type": "integer", "description": "分页偏移量。offset=0从第1条开始", "default": 0}
            },
            "required": ["code"]
        }
    },
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
    {
        "name": "update_fund_flow",
        "description": "更新单只股票资金流向数据。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码，如 601138"},
                "days": {"type": "integer", "description": "天数，默认100", "default": 100},
                "delay": {"type": "number", "description": "请求间隔秒，默认1.5", "default": 1.5},
                "force": {"type": "boolean", "description": "强制刷新", "default": False}
            },
            "required": ["code"]
        }
    },
    {
        "name": "get_fund_flow",
        "description": "分页查询资金流向数据。分页说明：默认返回全部数据，可用limit限制数量。建议用start_date/end_date限定时间范围，或用limit分页：limit=50, offset=0获取前50条。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码"},
                "start_date": {"type": "string", "description": "开始日期，如 2025-01-01"},
                "end_date": {"type": "string", "description": "结束日期，如 2026-05-06"},
                "limit": {"type": "integer", "description": "返回条数上限。不传则返回全部"},
                "offset": {"type": "integer", "description": "分页偏移量。offset=0从第1条开始", "default": 0}
            },
            "required": ["code"]
        }
    },
    {
        "name": "analyze_main_force",
        "description": "分析主力资金动向，包括净流入、连续流入/流出天数、趋势强度等。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码，如 601138"},
                "days": {"type": "integer", "description": "分析天数，默认10", "default": 10}
            },
            "required": ["code"]
        }
    }
]
