import threading
import uuid

SYNC_JOBS = {}
SYNC_JOBS_LOCK = threading.Lock()
SYNC_WORKER_LOCK = threading.Lock()

def _now_text(pool):
    return pool.get_current_time_info()['datetime']

def _public_job(job):
    return {k: v for k, v in job.items() if k not in ('stop_event',)}

def _persist_job(pool, job):
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

def _run_market_sync_job(pool, job_id, args):
    try:
        def progress_callback(progress):
            with SYNC_JOBS_LOCK:
                job = SYNC_JOBS.get(job_id)
                if not job:
                    return
                job['progress'] = progress
                job['updated_at'] = _now_text(pool)
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
                job['finished_at'] = _now_text(pool)
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
                job['finished_at'] = _now_text(pool)
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

def _run_code_update_job(pool, job_id, args):
    try:
        codes = _normalize_codes_argument(args.get('codes', []))
        days = args.get('days', 250)
        delay = args.get('delay', 1.5)
        force = args.get('force', False)
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
                job['updated_at'] = _now_text(pool)
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

            summary['current_code'] = code
            summary['scanned'] += 1

            try:
                pool.update_stock(code, days=days, delay=delay, force=force)
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
                    job['updated_at'] = _now_text(pool)
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
                job['progress'] = dict(summary)
                job['result'] = dict(summary)
                job['finished_at'] = _now_text(pool)
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
                job['finished_at'] = _now_text(pool)
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

def start_code_update(pool, arguments):
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
        'created_at': _now_text(pool),
        'updated_at': _now_text(pool),
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
    _persist_job(pool, job)

    thread = threading.Thread(target=_run_code_update_job, args=(pool, job_id, args), daemon=True)
    thread.start()
    return {
        "success": True,
        "job": _public_job(job),
        "message": "代码列表较大，已转为后台更新任务；用 get_market_sync_status 查询进度。"
    }

def _run_screen_market_job(pool, job_id, args):
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
                job['finished_at'] = _now_text(pool)
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
                job['finished_at'] = _now_text(pool)
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

def start_screen_market(pool, arguments):
    args = dict(arguments or {})
    job_id = uuid.uuid4().hex[:12]
    job = {
        'job_id': job_id,
        'status': 'running',
        'args': args,
        'created_at': _now_text(pool),
        'updated_at': _now_text(pool),
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
    _persist_job(pool, job)

    thread = threading.Thread(target=_run_screen_market_job, args=(pool, job_id, args), daemon=True)
    thread.start()
    return {
        "success": True,
        "job": _public_job(job),
        "message": "筛选可能耗时，已转为后台任务；用 get_market_sync_status 查询结果。"
    }

def start_market_sync(pool, arguments):
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
        'created_at': _now_text(pool),
        'updated_at': _now_text(pool),
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
    _persist_job(pool, job)

    thread = threading.Thread(target=_run_market_sync_job, args=(pool, job_id, args), daemon=True)
    thread.start()
    return {"success": True, "job": _public_job(job)}

def get_market_sync_status(pool, arguments):
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

def cancel_market_sync(pool, arguments):
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
        job['updated_at'] = _now_text(pool)
        public = _public_job(job)
    pool.update_sync_job(job_id, status=public.get('status'), updated_at=public.get('updated_at'))
    return {"success": True, "job": public}

def initialize_jobs(pool):
    pool.mark_running_sync_jobs_interrupted()
