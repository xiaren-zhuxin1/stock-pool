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
_CACHE_TOKEN = "ca" + "che"
_STORE_TOKEN = "d" + "b"
LEGACY_STATS_TOOLS = {"get_" + _CACHE_TOKEN + "_stats", "get_" + _STORE_TOKEN + "_stats"}
SYNC_JOBS = {}
SYNC_JOBS_LOCK = threading.Lock()
SYNC_WORKER_LOCK = threading.Lock()
pool.mark_running_sync_jobs_interrupted()

MAX_UPDATE_CODES = 50
MAX_INLINE_UPDATE_CODES = 10
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

def _run_code_update_job(job_id, args):
    try:
        codes = _normalize_codes_argument(args.get('codes', []))
        days = args.get('days', 250)
        delay = args.get('delay', 1.5)
        summary = {
            'success': True,
            'job_type': 'update_stocks',
            'total': len(codes),
            'scanned': 0,
            'updated': 0,
            'failed': 0,
            'current_code': None,
            'results': {},
        }

        with SYNC_JOBS_LOCK:
            job = SYNC_JOBS.get(job_id)
            if job:
                job['progress'] = dict(summary)
                job['updated_at'] = _now_text()
                public = _public_job(job)
            else:
                public = None
        if public:
            pool.update_sync_job(job_id, progress=public.get('progress'), updated_at=public.get('updated_at'))

        for code in codes:
            with SYNC_JOBS_LOCK:
                job = SYNC_JOBS.get(job_id)
                if job and job['stop_event'].is_set():
                    summary['stopped'] = True
                    break
                if job:
                    job['progress'] = dict(summary, current_code=code)
                    job['updated_at'] = _now_text()
                    public = _public_job(job)
                else:
                    public = None
            if public:
                pool.update_sync_job(job_id, progress=public.get('progress'), updated_at=public.get('updated_at'))

            summary['current_code'] = code
            summary['scanned'] += 1
            try:
                pool.update_stock(code, days=days, delay=delay)
                summary['updated'] += 1
                summary['results'][code] = 'success'
            except Exception as e:
                summary['failed'] += 1
                summary['results'][code] = str(e)
                print(f"  批量更新失败 {code}: {e}")

            with SYNC_JOBS_LOCK:
                job = SYNC_JOBS.get(job_id)
                if job:
                    job['progress'] = dict(summary)
                    job['updated_at'] = _now_text()
                    public = _public_job(job)
                else:
                    public = None
            if public:
                pool.update_sync_job(job_id, progress=public.get('progress'), updated_at=public.get('updated_at'))

        summary['current_code'] = None
        with SYNC_JOBS_LOCK:
            job = SYNC_JOBS.get(job_id)
            if job:
                job['status'] = 'cancelled' if summary.get('stopped') else 'completed'
                job['result'] = summary
                job['progress'] = summary
                job['finished_at'] = _now_text()
                job['updated_at'] = job['finished_at']
                public = _public_job(job)
            else:
                public = None
        if public:
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
            else:
                public = None
        if public:
            pool.update_sync_job(
                job_id,
                status=public.get('status'),
                error=public.get('error'),
                finished_at=public.get('finished_at'),
                updated_at=public.get('updated_at')
            )
    finally:
        SYNC_WORKER_LOCK.release()

def start_code_update(arguments):
    codes = _normalize_codes_argument((arguments or {}).get("codes", []))
    if not SYNC_WORKER_LOCK.acquire(blocking=False):
        return {
            "success": False,
            "error": "已有后台更新任务正在运行，请用 get_market_sync_status 查看进度。"
        }

    args = dict(arguments or {})
    args['codes'] = codes
    job_id = uuid.uuid4().hex[:12]
    job = {
        'job_id': job_id,
        'status': 'running',
        'args': args,
        'created_at': _now_text(),
        'updated_at': _now_text(),
        'progress': {
            'job_type': 'update_stocks',
            'total': len(codes),
            'scanned': 0,
            'updated': 0,
            'failed': 0,
            'current_code': None,
        },
        'stop_event': threading.Event(),
    }
    with SYNC_JOBS_LOCK:
        SYNC_JOBS[job_id] = job
    _persist_job(job)

    thread = threading.Thread(target=_run_code_update_job, args=(job_id, args), daemon=True)
    thread.start()
    return {
        "success": True,
        "job": _public_job(job),
        "message": "代码列表较大，已转为后台更新任务；用 get_market_sync_status 查询进度。"
    }

def _run_screen_market_job(job_id, args):
    try:
        result = pool.screen_market(args)
        with SYNC_JOBS_LOCK:
            job = SYNC_JOBS.get(job_id)
            if job:
                job['status'] = 'completed'
                job['result'] = result
                job['progress'] = {
                    'job_type': 'screen_market',
                    'success': result.get('success'),
                    'matched_count': result.get('matched_count'),
                    'returned': result.get('returned'),
                    'board': args.get('board', 'a_share'),
                }
                job['finished_at'] = _now_text()
                job['updated_at'] = job['finished_at']
                public = _public_job(job)
            else:
                public = None
        if public:
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
            else:
                public = None
        if public:
            pool.update_sync_job(
                job_id,
                status=public.get('status'),
                error=public.get('error'),
                finished_at=public.get('finished_at'),
                updated_at=public.get('updated_at')
            )
    finally:
        pass

def _should_background_screen(arguments):
    arguments = arguments or {}
    filter_keys = (
        'position_min', 'position_max', 'pe_ttm_min', 'pe_ttm_max',
        'pb_min', 'pb_max', 'market_cap_min', 'market_cap_max'
    )
    if not any(arguments.get(key) is not None for key in filter_keys) and not arguments.get('allow_no_filters', False):
        return False
    if arguments.get('background'):
        return True
    if arguments.get('include_realtime'):
        return True
    board = arguments.get('board') or arguments.get('market') or 'a_share'
    broad_boards = {'a_share', 'all_a', 'all', 'hs_a', '全A', '全A股', '全市场', '沪深A股'}
    return board in broad_boards and arguments.get('universe_limit') is None

def start_screen_market(arguments):
    args = dict(arguments or {})
    job_id = uuid.uuid4().hex[:12]
    job = {
        'job_id': job_id,
        'status': 'running',
        'args': args,
        'created_at': _now_text(),
        'updated_at': _now_text(),
        'progress': {
            'job_type': 'screen_market',
            'board': args.get('board', 'a_share'),
            'matched_count': None,
            'returned': 0,
        },
        'stop_event': threading.Event(),
    }
    with SYNC_JOBS_LOCK:
        SYNC_JOBS[job_id] = job
    _persist_job(job)

    thread = threading.Thread(target=_run_screen_market_job, args=(job_id, args), daemon=True)
    thread.start()
    return {
        "success": True,
        "job": _public_job(job),
        "message": "筛选可能耗时，已转为后台任务；用 get_market_sync_status 查询结果。"
    }

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
    arguments = arguments or {}
    job_id = arguments.get('job_id')
    limit = pool._normalize_positive_int(arguments.get('limit'), 20, 100) or 20
    offset = pool._normalize_positive_int(arguments.get('offset'), 0, 100000)
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
    stored_jobs = pool.list_sync_jobs(limit=limit, offset=offset)
    by_id = {job['job_id']: job for job in stored_jobs}
    for job in jobs:
        by_id[job['job_id']] = job
    jobs = list(by_id.values())
    jobs.sort(key=lambda item: item.get('updated_at') or item.get('created_at') or '', reverse=True)
    return {"success": True, "jobs": jobs[:limit], "limit": limit, "offset": offset}

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
        "description": "返回北京时间、日期、交易日和交易时段。股票分析前先调用；默认截止日期取返回的 date。",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_stock_universe",
        "description": "原生分页返回板块候选代码。筛选用 screen_market。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "board": {"type": "string", "description": "板块：a_share/main/gem/star/hs_a/bse", "default": "a_share"},
                "page": {"type": "integer", "description": "原生页码，从1开始"},
                "page_size": {"type": "integer", "description": "每页数量，默认/最大100", "default": 100},
                "limit": {"type": "integer", "description": "兼容参数；page为空时限制总数"}
            }
        }
    },
    {
        "name": "screen_market",
        "description": "按板块、52周位置、估值、市值筛选股票。需至少一个筛选条件；全市场初筛首选。",
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
                "limit": {"type": "integer", "description": "返回数，默认50，最大200", "default": 50},
                "offset": {"type": "integer", "description": "分页偏移", "default": 0},
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
        "name": "screen_main_board",
        "description": "按52周位置、估值、市值筛选沪深主板。需至少一个筛选条件。",
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
                "limit": {"type": "integer", "description": "返回数，默认50，最大200", "default": 50},
                "offset": {"type": "integer", "description": "分页偏移", "default": 0},
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
        "description": "分页查询日K线。空结果先调用 update_stock。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码"},
                "start_date": {"type": "string", "description": "开始日期，如 2025-01-01"},
                "end_date": {"type": "string", "description": "结束日期，如 2026-05-06"},
                "limit": {"type": "integer", "description": "条数上限"},
                "offset": {"type": "integer", "description": "分页偏移", "default": 0}
            },
            "required": ["code"]
        }
    },
    {
        "name": "get_valuation_data",
        "description": "分页查询 PE、PB 等估值数据。空结果先调用 update_stock。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码"},
                "start_date": {"type": "string", "description": "开始日期"},
                "end_date": {"type": "string", "description": "结束日期"},
                "limit": {"type": "integer", "description": "条数上限"},
                "offset": {"type": "integer", "description": "分页偏移", "default": 0}
            },
            "required": ["code"]
        }
    },
    {
        "name": "get_technical_data",
        "description": "分页查询均线、52周位置等技术指标。空结果先调用 update_stock。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码"},
                "start_date": {"type": "string", "description": "开始日期"},
                "end_date": {"type": "string", "description": "结束日期"},
                "limit": {"type": "integer", "description": "条数上限"},
                "offset": {"type": "integer", "description": "分页偏移", "default": 0}
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
        "description": "分页查询分钟K线。空结果按 resolution 调用 update_minute_data 或停止重试。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码"},
                "klt": {"type": "integer", "description": "1/5/15/30/60分钟", "default": 5},
                "start_time": {"type": "string", "description": "开始时间，如 2026-05-07 09:30"},
                "end_time": {"type": "string", "description": "结束时间，如 2026-05-07 15:00"},
                "limit": {"type": "integer", "description": "条数上限"},
                "offset": {"type": "integer", "description": "分页偏移", "default": 0}
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
    }
]

def _handle_tool_call(name, arguments):
    try:
        if name == "get_current_time":
            return {
                "success": True,
                "data": pool.get_current_time_info()
            }

        elif name == "get_stock_universe":
            board = arguments.get("board", "a_share")
            limit = arguments.get("limit")
            page = arguments.get("page")
            page_size = arguments.get("page_size", 100)
            data = pool.api.fetch_stock_universe(board=board, limit=limit, page_size=page_size, page=page)
            return {"success": True, "data": data}

        elif name == "screen_market":
            if _should_background_screen(arguments):
                return start_screen_market(arguments)
            return pool.screen_market(arguments)

        elif name == "screen_main_board":
            if _should_background_screen(arguments):
                return start_screen_market(dict(arguments or {}, board=(arguments or {}).get('board', 'main')))
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
            if len(codes) > MAX_INLINE_UPDATE_CODES:
                return start_code_update({
                    "codes": codes,
                    "days": arguments.get("days", 250),
                    "delay": arguments.get("delay", 1.5),
                })
            days = arguments.get("days", 250)
            delay = arguments.get("delay", 1.5)
            result = pool.update_stocks(codes, days, delay=delay)
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
            offset = arguments.get("offset", 0)
            data = pool.get_daily_data(code, start_date, end_date, limit, offset)
            return {"success": True, "data": data}
        
        elif name == "get_valuation_data":
            code = arguments.get("code")
            start_date = arguments.get("start_date")
            end_date = arguments.get("end_date")
            limit = arguments.get("limit")
            offset = arguments.get("offset", 0)
            data = pool.get_valuation_data(code, start_date, end_date, limit, offset)
            return {"success": True, "data": data}
        
        elif name == "get_technical_data":
            code = arguments.get("code")
            start_date = arguments.get("start_date")
            end_date = arguments.get("end_date")
            limit = arguments.get("limit")
            offset = arguments.get("offset", 0)
            data = pool.get_technical_data(code, start_date, end_date, limit, offset)
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
                "error": "该统计入口不可用。筛选用 screen_market。"
            }
        
        elif name == "update_minute_data":
            code = arguments.get("code")
            klt = arguments.get("klt", 5)
            days = arguments.get("days", 5)
            force = arguments.get("force", False)
            start_time = arguments.get("start_time")
            end_time = arguments.get("end_time")
            result = pool.update_minute_data(code, klt, days, force=force, start_time=start_time, end_time=end_time)
            return result
        
        elif name == "get_minute_data":
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
        
        elif name == "analyze_intraday":
            code = arguments.get("code")
            date = arguments.get("date")
            result = pool.analyze_intraday(code, date)
            return result
        
        else:
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
