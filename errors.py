import sys
import builtins
import traceback
from datetime import datetime
from typing import Optional, Dict, Any, List
from enum import Enum


def print(*args, **kwargs):
    kwargs.setdefault('file', sys.stderr)
    return builtins.print(*args, **kwargs)


class ErrorSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class StockPoolError(Exception):
    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        details: Optional[Dict[str, Any]] = None,
        recoverable: bool = True,
        suggested_action: Optional[str] = None,
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code or "UNKNOWN"
        self.severity = severity
        self.details = details or {}
        self.recoverable = recoverable
        self.suggested_action = suggested_action
        self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        result = {
            'success': False,
            'error': {
                'code': self.error_code,
                'message': self.message,
                'severity': self.severity.value,
                'recoverable': self.recoverable,
                'timestamp': self.timestamp,
            }
        }
        if self.details:
            result['error']['details'] = self.details
        if self.suggested_action:
            result['error']['suggested_action'] = self.suggested_action
        return result


class ProviderError(StockPoolError):
    def __init__(
        self,
        message: str,
        provider_name: str,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        recoverable: bool = True,
        suggested_action: Optional[str] = None,
    ):
        details = details or {}
        details['provider'] = provider_name
        super().__init__(
            message=message,
            error_code=error_code or "PROVIDER_ERROR",
            severity=ErrorSeverity.ERROR,
            details=details,
            recoverable=recoverable,
            suggested_action=suggested_action,
        )


class DataNotFoundError(StockPoolError):
    def __init__(self, message: str, data_type: Optional[str] = None, code: Optional[str] = None):
        details = {}
        if data_type:
            details['data_type'] = data_type
        if code:
            details['code'] = code
        super().__init__(
            message=message,
            error_code="DATA_NOT_FOUND",
            severity=ErrorSeverity.WARNING,
            details=details,
            recoverable=True,
            suggested_action="请先调用 update_stock 更新数据",
        )


class ValidationError(StockPoolError):
    def __init__(self, message: str, field: Optional[str] = None, value: Any = None):
        details = {}
        if field:
            details['field'] = field
        if value is not None:
            details['value'] = str(value)
        super().__init__(
            message=message,
            error_code="VALIDATION_ERROR",
            severity=ErrorSeverity.WARNING,
            details=details,
            recoverable=True,
        )


class RateLimitError(StockPoolError):
    def __init__(self, message: str, retry_after: Optional[int] = None):
        details = {}
        if retry_after:
            details['retry_after'] = retry_after
        super().__init__(
            message=message,
            error_code="RATE_LIMITED",
            severity=ErrorSeverity.WARNING,
            details=details,
            recoverable=True,
            suggested_action=f"请等待 {retry_after} 秒后重试" if retry_after else "请稍后重试",
        )


class ConfigurationError(StockPoolError):
    def __init__(self, message: str, config_key: Optional[str] = None):
        details = {}
        if config_key:
            details['config_key'] = config_key
        super().__init__(
            message=message,
            error_code="CONFIG_ERROR",
            severity=ErrorSeverity.CRITICAL,
            details=details,
            recoverable=False,
        )


class Logger:
    _instance = None
    _log_file: Optional[str] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._initialized = True
            self._logs: List[Dict[str, Any]] = []
            self._max_logs = 1000
    
    def set_log_file(self, path: str):
        self._log_file = path
    
    def _format_message(self, level: str, message: str, **kwargs) -> str:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        extra = ' '.join(f'{k}={v}' for k, v in kwargs.items() if v is not None)
        return f"[{timestamp}] [{level}] {message} {extra}".strip()
    
    def _add_log(self, level: str, message: str, **kwargs):
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'level': level,
            'message': message,
            **kwargs
        }
        self._logs.append(log_entry)
        if len(self._logs) > self._max_logs:
            self._logs = self._logs[-self._max_logs:]
    
    def debug(self, message: str, **kwargs):
        self._add_log('DEBUG', message, **kwargs)
    
    def info(self, message: str, **kwargs):
        formatted = self._format_message('INFO', message, **kwargs)
        print(formatted)
        self._add_log('INFO', message, **kwargs)
    
    def warning(self, message: str, **kwargs):
        formatted = self._format_message('WARN', message, **kwargs)
        print(formatted)
        self._add_log('WARNING', message, **kwargs)
    
    def error(self, message: str, **kwargs):
        formatted = self._format_message('ERROR', message, **kwargs)
        print(formatted)
        self._add_log('ERROR', message, **kwargs)
    
    def critical(self, message: str, **kwargs):
        formatted = self._format_message('CRITICAL', message, **kwargs)
        print(formatted)
        self._add_log('CRITICAL', message, **kwargs)
    
    def exception(self, message: str, exc: Optional[Exception] = None, **kwargs):
        if exc:
            tb = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            kwargs['traceback'] = tb
        self.error(message, **kwargs)
    
    def get_logs(self, level: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        logs = self._logs
        if level:
            logs = [l for l in logs if l['level'] == level]
        return logs[-limit:]


logger = Logger()


def handle_error(error: Exception, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if isinstance(error, StockPoolError):
        result = error.to_dict()
        logger.error(error.message, error_code=error.error_code, **error.details)
    else:
        result = {
            'success': False,
            'error': {
                'code': 'UNKNOWN_ERROR',
                'message': str(error),
                'severity': 'error',
                'recoverable': True,
                'timestamp': datetime.now().isoformat(),
            }
        }
        logger.exception("未处理的异常", exc=error)
    
    if context:
        result['error']['context'] = context
    
    return result


def create_error_response(
    message: str,
    error_code: str = "ERROR",
    severity: ErrorSeverity = ErrorSeverity.ERROR,
    recoverable: bool = True,
    suggested_action: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    result = {
        'success': False,
        'error': {
            'code': error_code,
            'message': message,
            'severity': severity.value,
            'recoverable': recoverable,
            'timestamp': datetime.now().isoformat(),
        }
    }
    if suggested_action:
        result['error']['suggested_action'] = suggested_action
    if details:
        result['error']['details'] = details
    return result


def create_success_response(
    data: Any = None,
    message: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    result = {'success': True}
    if data is not None:
        result['data'] = data
    if message:
        result['message'] = message
    if metadata:
        result['metadata'] = metadata
    return result
