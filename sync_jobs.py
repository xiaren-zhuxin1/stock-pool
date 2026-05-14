import json
from typing import Any


def json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def json_loads(value: Any, default: Any = None) -> Any:
    if not value:
        return {} if default is None else default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {} if default is None else default
