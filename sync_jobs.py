import json
from typing import Any, Callable, Dict, Optional


def json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def json_loads(value: Any, default: Any = None) -> Any:
    if not value:
        return {} if default is None else default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {} if default is None else default


def sync_job_from_row(row: Any) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    return {
        'job_id': row[0],
        'status': row[1],
        'args': json_loads(row[2]),
        'progress': json_loads(row[3]),
        'result': json_loads(row[4], None) if row[4] else None,
        'error': row[5],
        'created_at': row[6],
        'updated_at': row[7],
        'finished_at': row[8],
    }


class SyncJobStore:
    def __init__(
        self,
        connect: Callable[[], Any],
        normalize_positive_int: Callable[[Any, int, int], int],
        current_time_info: Callable[[], Dict[str, Any]],
    ) -> None:
        self._connect = connect
        self._normalize_positive_int = normalize_positive_int
        self._current_time_info = current_time_info

    def save(self, job: Dict[str, Any]) -> None:
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO service_sync_jobs
                (job_id, status, args_json, progress_json, result_json, error, created_at, updated_at, finished_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                job.get('job_id'),
                job.get('status'),
                json_dumps(job.get('args')),
                json_dumps(job.get('progress')),
                json_dumps(job.get('result')) if job.get('result') is not None else None,
                job.get('error'),
                job.get('created_at'),
                job.get('updated_at'),
                job.get('finished_at'),
            ))
            conn.commit()
        finally:
            conn.close()

    def update(self, job_id: str, **fields: Any) -> None:
        if not fields:
            return
        allowed = {
            'status': 'status',
            'args': 'args_json',
            'progress': 'progress_json',
            'result': 'result_json',
            'error': 'error',
            'created_at': 'created_at',
            'updated_at': 'updated_at',
            'finished_at': 'finished_at',
        }
        sets = []
        params = []
        for key, value in fields.items():
            column = allowed.get(key)
            if not column:
                continue
            sets.append(f'{column} = ?')
            if key in ('args', 'progress', 'result'):
                params.append(json_dumps(value) if value is not None else None)
            else:
                params.append(value)
        if not sets:
            return
        params.append(job_id)

        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(f'''
                UPDATE service_sync_jobs
                SET {', '.join(sets)}
                WHERE job_id = ?
            ''', params)
            conn.commit()
        finally:
            conn.close()

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT job_id, status, args_json, progress_json, result_json, error, created_at, updated_at, finished_at
                FROM service_sync_jobs
                WHERE job_id = ?
            ''', (job_id,))
            return sync_job_from_row(cursor.fetchone())
        finally:
            conn.close()

    def list(self, limit: Any = 20, offset: Any = 0) -> list:
        limit = self._normalize_positive_int(limit, 20, 100)
        offset = self._normalize_positive_int(offset, 0, 100000)
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT job_id, status, args_json, progress_json, result_json, error, created_at, updated_at, finished_at
                FROM service_sync_jobs
                ORDER BY updated_at DESC
                LIMIT ?
                OFFSET ?
            ''', (limit, offset))
            return [sync_job_from_row(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def mark_running_interrupted(self, timestamp: Optional[str] = None) -> None:
        timestamp = timestamp or self._current_time_info()['datetime']
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE service_sync_jobs
                SET status = ?, error = ?, updated_at = ?, finished_at = ?
                WHERE status IN (?, ?)
            ''', ('interrupted', '服务重启，后台同步任务已中断', timestamp, timestamp, 'running', 'cancelling'))
            conn.commit()
        finally:
            conn.close()
