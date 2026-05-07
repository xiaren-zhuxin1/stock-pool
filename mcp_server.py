import asyncio
import json
import sys
import os
import threading
import uuid

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError):
        pass

script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)
sys.path.insert(0, parent_dir)

from stock_pool import StockDataPool

pool = StockDataPool()
LEGACY_STATS_TOOLS = {"get_" + "cache" + "_stats", "get_" + "db" + "_stats"}
SYNC_JOBS = {}
SYNC_JOBS_LOCK = threading.Lock()
SYNC_WORKER_LOCK = threading.Lock()
pool.mark_running_sync_jobs_interrupted()

MAX_UPDATE_CODES = 50
MAX_DETAIL_CODES = 30
MAX_POSITION_CODES = 100
MAX_REALTIME_CODES = 20
MAX_CHECK_CODES = 200

def _now_text():
    return pool.get_current_time_info()['datetime']

def _public_job(job):
    return {k: v for k, v in job.items() if k not in ('stop_event',)}

def _persist_job(job):
    pool.save_sync_job(_public_job(job))

def _normalize_codes_argument(codes):
    if not isinstance(codes, list):
        return []
    result = []
    seen = set()
    for code in codes:
        code = str(code).strip()
        if not code or code in seen:
            continue
        seen.add(code)
        result.append(code)
    return result

def _reject_large_code_list(codes, limit, tool_name):
    if len(codes) <= limit:
        return None
    return {
        "success": False,
        "error": (
            f"{tool_name} 单次最多处理 {limit} 只股票，当前收到 {len(codes)} 只。"
            "请先用 screen_market 缩小候选范围；如需维护全市场数据，请使用 start_market_sync；"
            "深度分析时请逐只或小批次处理。"
        )
    }

def _run_market_sync_job(job_id, args):
    try:
        def progress_callback(progress):
            with SYNC_JOBS_LOCK:
                job = SYNC_JOBS.get(job_id)
                if not job:
                    return
                job['progress'] = progress
                job['updated_at'] = _now_text()
                public = _public_job(job)
            pool.update_sync_job(job_id, progress=public.get('progress'), updated_at=public.get('updated_at'))

        def should_stop():
            with SYNC_JOBS_LOCK:
                job = SYNC_JOBS.get(job_id)
                return bool(job and job['stop_event'].is_set())

        result = pool.sync_market(
            board=args.get('board', 'a_share'),
            refresh=args.get('refresh', 'stale'),
            max_codes=args.get('max_codes'),
            days=args.get('days', 250),
            delay=args.get('delay', 0.2),
            progress_callback=progress_callback,
            should_stop=should_stop,
        )

        with SYNC_JOBS_LOCK:
            job = SYNC_JOBS.get(job_id)
            if job:
                job['status'] = 'cancelled' if result.get('stopped') else 'completed'
                job['result'] = result
                job['progress'] = result
                job['finished_at'] = _now_text()
                job['updated_at'] = job['finished_at']
                public = _public_job(job)
        if 'public' in locals():
            pool.update_sync_job(
                job_id,
                status=public.get('status'),
                result=public.get('result'),
                progress=public.get('progress'),
                finished_at=public.get('finished_at'),
                updated_at=public.get('updated_at')
            )
    except Exception as e:
        with SYNC_JOBS_LOCK:
            job = SYNC_JOBS.get(job_id)
            if job:
                job['status'] = 'failed'
                job['error'] = str(e)
                job['finished_at'] = _now_text()
                job['updated_at'] = job['finished_at']
                public = _public_job(job)
        if 'public' in locals():
            pool.update_sync_job(
                job_id,
                status=public.get('status'),
                error=public.get('error'),
                finished_at=public.get('finished_at'),
                updated_at=public.get('updated_at')
            )
    finally:
        SYNC_WORKER_LOCK.release()

def start_market_sync(arguments):
    if not SYNC_WORKER_LOCK.acquire(blocking=False):
        return {
            "success": False,
            "error": "已有市场同步任务正在运行，请先调用 get_market_sync_status 查看进度。"
        }

    job_id = uuid.uuid4().hex[:12]
    args = dict(arguments or {})
    job = {
        'job_id': job_id,
        'status': 'running',
        'args': args,
        'created_at': _now_text(),
        'updated_at': _now_text(),
        'progress': {
            'board': args.get('board', 'a_share'),
            'refresh': args.get('refresh', 'stale'),
            'total': 0,
            'scanned': 0,
            'refreshed': 0,
            'skipped_fresh': 0,
            'failed': 0,
            'current_code': None,
        },
        'stop_event': threading.Event(),
    }
    with SYNC_JOBS_LOCK:
        SYNC_JOBS[job_id] = job
    _persist_job(job)

    thread = threading.Thread(target=_run_market_sync_job, args=(job_id, args), daemon=True)
    thread.start()
    return {"success": True, "job": _public_job(job)}

def get_market_sync_status(arguments):
    job_id = (arguments or {}).get('job_id')
    with SYNC_JOBS_LOCK:
        if job_id:
            job = SYNC_JOBS.get(job_id)
            if job:
                return {"success": True, "job": _public_job(job)}
            stored = pool.get_sync_job(job_id)
            if not stored:
                return {"success": False, "error": f"未找到同步任务: {job_id}"}
            return {"success": True, "job": stored}
        jobs = [_public_job(job) for job in SYNC_JOBS.values()]
    stored_jobs = pool.list_sync_jobs(limit=20)
    by_id = {job['job_id']: job for job in stored_jobs}
    for job in jobs:
        by_id[job['job_id']] = job
    jobs = list(by_id.values())
    jobs.sort(key=lambda item: item.get('updated_at') or item.get('created_at') or '', reverse=True)
    return {"success": True, "jobs": jobs[:20]}

def cancel_market_sync(arguments):
    job_id = (arguments or {}).get('job_id')
    if not job_id:
        return {"success": False, "error": "缺少 job_id"}
    with SYNC_JOBS_LOCK:
        job = SYNC_JOBS.get(job_id)
        if not job:
            stored = pool.get_sync_job(job_id)
            if not stored:
                return {"success": False, "error": f"未找到同步任务: {job_id}"}
            return {"success": True, "job": stored}
        if job.get('status') != 'running':
            return {"success": True, "job": _public_job(job)}
        job['stop_event'].set()
        job['status'] = 'cancelling'
        job['updated_at'] = _now_text()
        public = _public_job(job)
    pool.update_sync_job(job_id, status=public.get('status'), updated_at=public.get('updated_at'))
    return {"success": True, "job": public}

TOOLS = [
    {
        "name": "get_current_time",
        "description": "【强制前置工具】每次股票分析任务开始前必须先调用本工具获取准确北京时间（Asia/Shanghai）、交易日/交易时段状态，并以返回的 date 作为默认分析截止日期",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_stock_universe",
        "description": "从外部行情接口获取候选股票代码列表。普通代码列表任务可使用本工具；若用户要求全A股/创业板/科创板/主板筛选，请优先调用 screen_market，不要自行循环处理全量 codes",
        "inputSchema": {
            "type": "object",
            "properties": {
                "board": {"type": "string", "description": "股票池范围：a_share=全A股，main=沪深主板，gem=创业板，star=科创板，hs_a=沪深A股，bse=北交所", "default": "a_share"},
                "limit": {"type": "integer", "description": "最多返回多少只；不填则返回该范围全部候选"},
                "page_size": {"type": "integer", "description": "外部接口分页大小，默认100，最大100", "default": 100}
            }
        }
    },
    {
        "name": "screen_market",
        "description": "【市场筛选专用】服务端受控执行全A股/创业板/科创板/主板筛选：获取候选股票池、按需小批量刷新、批量读取缓存快照、按条件筛选并分页返回。必须提供至少一个筛选条件；默认不拉实时行情，避免大量外部请求。筛选后如需深度分析，应对返回候选逐只或小批次分析，不要一次拉取全部详情",
        "inputSchema": {
            "type": "object",
            "properties": {
                "board": {"type": "string", "description": "筛选范围：a_share=全A股，main=沪深主板，gem=创业板，star=科创板，hs_a=沪深A股，bse=北交所", "default": "a_share"},
                "position_min": {"type": "number", "description": "52周位置下限"},
                "position_max": {"type": "number", "description": "52周位置上限，例如低位筛选可传30"},
                "pe_ttm_min": {"type": "number", "description": "市盈率TTM下限"},
                "pe_ttm_max": {"type": "number", "description": "市盈率TTM上限"},
                "pb_min": {"type": "number", "description": "市净率下限"},
                "pb_max": {"type": "number", "description": "市净率上限"},
                "market_cap_min": {"type": "number", "description": "总市值下限"},
                "market_cap_max": {"type": "number", "description": "总市值上限"},
                "sort_by": {"type": "string", "description": "排序字段：position_pct/pe_ttm/pb/market_cap/close/code/date", "default": "position_pct"},
                "sort_order": {"type": "string", "description": "asc 或 desc", "default": "asc"},
                "limit": {"type": "integer", "description": "返回数量，默认50，最大200", "default": 50},
                "offset": {"type": "integer", "description": "分页偏移", "default": 0},
                "universe_limit": {"type": "integer", "description": "最多扫描多少只候选；测试或试跑时可设置，正式筛选不填"},
                "refresh": {"type": "string", "description": "刷新策略：none/missing/stale/force，默认none", "default": "none"},
                "max_refresh": {"type": "integer", "description": "本次最多刷新多少只；refresh=none时默认0，其他刷新策略默认200，最大200"},
                "days": {"type": "integer", "description": "刷新时拉取的日K天数，默认250", "default": 250},
                "include_realtime": {"type": "boolean", "description": "是否对返回页补实时行情，默认false", "default": False},
                "realtime_limit": {"type": "integer", "description": "最多补实时行情的返回结果数量，默认20，最大50", "default": 20},
                "batch_size": {"type": "integer", "description": "内部批量读取大小，默认200，最大500", "default": 200}
            }
        }
    },
    {
        "name": "screen_main_board",
        "description": "【兼容入口】服务端受控执行沪深主板筛选。若用户要求全A股/创业板/科创板筛选，请调用 screen_market",
        "inputSchema": {
            "type": "object",
            "properties": {
                "board": {"type": "string", "description": "筛选范围：main=沪深主板，sh_main=沪主板，sz_main=深主板", "default": "main"},
                "position_min": {"type": "number", "description": "52周位置下限"},
                "position_max": {"type": "number", "description": "52周位置上限，例如低位筛选可传30"},
                "pe_ttm_min": {"type": "number", "description": "市盈率TTM下限"},
                "pe_ttm_max": {"type": "number", "description": "市盈率TTM上限"},
                "pb_min": {"type": "number", "description": "市净率下限"},
                "pb_max": {"type": "number", "description": "市净率上限"},
                "market_cap_min": {"type": "number", "description": "总市值下限"},
                "market_cap_max": {"type": "number", "description": "总市值上限"},
                "sort_by": {"type": "string", "description": "排序字段：position_pct/pe_ttm/pb/market_cap/close/code/date", "default": "position_pct"},
                "sort_order": {"type": "string", "description": "asc 或 desc", "default": "asc"},
                "limit": {"type": "integer", "description": "返回数量，默认50，最大200", "default": 50},
                "offset": {"type": "integer", "description": "分页偏移", "default": 0},
                "universe_limit": {"type": "integer", "description": "最多扫描多少只候选；测试或试跑时可设置，正式筛选不填"},
                "refresh": {"type": "string", "description": "刷新策略：none/missing/stale/force，默认none", "default": "none"},
                "max_refresh": {"type": "integer", "description": "本次最多刷新多少只；refresh=none时默认0，其他刷新策略默认200，最大200"},
                "days": {"type": "integer", "description": "刷新时拉取的日K天数，默认250", "default": 250},
                "include_realtime": {"type": "boolean", "description": "是否对返回页补实时行情，默认false", "default": False},
                "realtime_limit": {"type": "integer", "description": "最多补实时行情的返回结果数量，默认20，最大50", "default": 20},
                "batch_size": {"type": "integer", "description": "内部批量读取大小，默认200，最大500", "default": 200}
            }
        }
    },
    {
        "name": "start_market_sync",
        "description": "【全市场后台同步】启动服务端后台任务，分批、限速、按缓存缺口同步全A股/创业板/科创板/主板数据。用于为后续 screen_market 准备完整缓存；不会一次性返回大量股票结果。同步完成后仍应先筛选，再逐只或小批次做深度分析",
        "inputSchema": {
            "type": "object",
            "properties": {
                "board": {"type": "string", "description": "同步范围：a_share=全A股，main=沪深主板，gem=创业板，star=科创板，hs_a=沪深A股，bse=北交所", "default": "a_share"},
                "refresh": {"type": "string", "description": "同步策略：missing=只补缺失，stale=补缺失和过期，force=强制刷新，默认stale", "default": "stale"},
                "max_codes": {"type": "integer", "description": "本任务最多扫描多少只；试跑可设置，正式同步不填"},
                "days": {"type": "integer", "description": "目标历史窗口，默认250；已有足够历史时只按近期缺口增量拉取", "default": 250},
                "delay": {"type": "number", "description": "每只股票刷新后的延迟秒数，默认0.2", "default": 0.2}
            }
        }
    },
    {
        "name": "get_market_sync_status",
        "description": "查询市场后台同步任务状态；不传 job_id 时返回最近任务列表",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "start_market_sync 返回的任务ID"}
            }
        }
    },
    {
        "name": "cancel_market_sync",
        "description": "请求取消正在运行的市场后台同步任务；任务会在当前股票处理结束后停止",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "start_market_sync 返回的任务ID"}
            },
            "required": ["job_id"]
        }
    },
    {
        "name": "update_stock",
        "description": "按给定股票代码更新服务缓存（日K、估值、技术指标等），必要时从外部API拉取；如果缓存已是最新，则跳过更新；不会自动枚举全市场股票。若用户要求全A股/创业板/科创板/主板筛选，请调用 screen_market",
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
        "description": "按给定股票代码列表批量更新服务缓存，必要时从外部API拉取；不会自动枚举全市场股票，也不会反推候选列表。仅适合明确的小批量代码列表，单次最多50只；大量股票请使用 start_market_sync 分批同步，避免接口限流",
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
        "description": "获取指定股票的日K线数据；每次任务前必须先调用 get_current_time。若查询范围涉及当前日期，服务会在缓存基础上自动补充实时行情，避免当日数据滞后",
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
        "description": "批量获取给定股票列表的最新综合数据；每次任务前必须先调用 get_current_time。仅适合小批量候选详情读取，单次最多30只；不要一次拉取全部候选详情再分析，容易耗时、触发限流并挤占上下文。全市场/板块筛选请调用 screen_market",
        "inputSchema": {
            "type": "object",
            "properties": {
                "codes": {"type": "array", "items": {"type": "string"}, "description": "股票代码列表"},
                "include_realtime": {"type": "boolean", "description": "是否补实时行情；大量代码建议false", "default": False},
                "realtime_limit": {"type": "integer", "description": "最多补实时行情的股票数量"},
                "batch_size": {"type": "integer", "description": "内部批量读取大小，默认200，最大500", "default": 200}
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
        "description": "按给定股票代码列表批量实时获取当前价格和估值，直接调用外部API，不使用服务缓存；不支持自动发现股票代码；单次最多20只",
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
        "description": "基于给定股票列表的可用历史数据分析52周位置，返回低位/中位/高位分类；服务会优先使用缓存；仅适合小批量明确代码列表，单次最多100只。全市场筛选请调用 screen_market，筛选后逐只或小批次做深度分析",
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
        "description": "检查给定股票列表在服务缓存中的日K数据是否缺失，可用于判断是否需要先 update_stock/update_stocks；单次最多200只",
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
            return {
                "success": True,
                "data": pool.get_current_time_info()
            }

        elif name == "get_stock_universe":
            board = arguments.get("board", "a_share")
            limit = arguments.get("limit")
            page_size = arguments.get("page_size", 100)
            data = pool.api.fetch_stock_universe(board=board, limit=limit, page_size=page_size)
            data["agent_rule"] = "如需全A股/创业板/科创板/主板筛选，请调用 screen_market；不要自行循环处理全量 codes。"
            return {"success": True, "data": data}

        elif name == "screen_market":
            return pool.screen_market(arguments)

        elif name == "screen_main_board":
            return pool.screen_main_board(arguments)

        elif name == "start_market_sync":
            return start_market_sync(arguments)

        elif name == "get_market_sync_status":
            return get_market_sync_status(arguments)

        elif name == "cancel_market_sync":
            return cancel_market_sync(arguments)

        elif name == "update_stock":
            code = arguments.get("code")
            days = arguments.get("days", 250)
            force = arguments.get("force", False)
            pool.update_stock(code, days, force=force)
            return {"success": True, "message": f"已更新 {code}"}
        
        elif name == "update_stocks":
            codes = _normalize_codes_argument(arguments.get("codes", []))
            too_many = _reject_large_code_list(codes, MAX_UPDATE_CODES, "update_stocks")
            if too_many:
                return too_many
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
        
        elif name == "get_realtime_price":
            code = arguments.get("code")
            data = pool.get_realtime_price(code)
            return {"success": True, "data": data}
        
        elif name == "get_realtime_prices":
            codes = _normalize_codes_argument(arguments.get("codes", []))
            too_many = _reject_large_code_list(codes, MAX_REALTIME_CODES, "get_realtime_prices")
            if too_many:
                return too_many
            delay = arguments.get("delay", 0.2)
            data = pool.get_realtime_prices(codes, delay=delay)
            return {"success": True, "data": data}
        
        elif name == "analyze_position":
            codes = _normalize_codes_argument(arguments.get("codes", []))
            too_many = _reject_large_code_list(codes, MAX_POSITION_CODES, "analyze_position")
            if too_many:
                return too_many
            data = pool.analyze_position(codes)
            return {"success": True, "data": data}
        
        elif name == "check_missing_data":
            codes = _normalize_codes_argument(arguments.get("codes", []))
            too_many = _reject_large_code_list(codes, MAX_CHECK_CODES, "check_missing_data")
            if too_many:
                return too_many
            start_date = arguments.get("start_date")
            end_date = arguments.get("end_date")
            data = pool.check_missing_data(codes, start_date, end_date)
            return {"success": True, "data": data}
        
        elif name in LEGACY_STATS_TOOLS:
            return {
                "success": False,
                "error": "该统计入口不作为股票分析数据源。请先调用 get_current_time；如需全市场/板块筛选，请调用 screen_market。"
            }
        
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
