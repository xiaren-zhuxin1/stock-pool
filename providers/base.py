import sys
import builtins
import time
import random
from abc import ABC, abstractmethod
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


def _log(*args, **kwargs):
    kwargs.setdefault('file', sys.stderr)
    return builtins.print(*args, **kwargs)


class DataType(Enum):
    REALTIME = "realtime"
    DAILY_KLINE = "daily_kline"
    MINUTE_KLINE = "minute_kline"
    VALUATION = "valuation"
    FUND_FLOW = "fund_flow"
    FINANCIAL = "financial"
    STOCK_LIST = "stock_list"
    TECHNICAL = "technical"


class ProviderCapability(Enum):
    REALTIME_QUOTE = "realtime_quote"
    DAILY_KLINE = "daily_kline"
    MINUTE_KLINE = "minute_kline"
    VALUATION = "valuation"
    FUND_FLOW = "fund_flow"
    FINANCIAL = "financial"
    STOCK_LIST = "stock_list"


class ProviderStatus(Enum):
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    RATE_LIMITED = "rate_limited"


class ErrorType(Enum):
    TIMEOUT = "timeout"
    CONNECTION_ERROR = "connection_error"
    RATE_LIMITED = "rate_limited"
    HTTP_ERROR = "http_error"
    DATA_ERROR = "data_error"
    AUTH_ERROR = "auth_error"
    QUOTA_EXCEEDED = "quota_exceeded"
    INVALID_PARAMS = "invalid_params"
    NOT_SUPPORTED = "not_supported"
    UNKNOWN = "unknown"


@dataclass
class ProviderError:
    error_type: ErrorType
    message: str
    provider_name: str
    original_error: Optional[Exception] = None
    retry_after: Optional[int] = None
    is_recoverable: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            'error_type': self.error_type.value,
            'message': self.message,
            'provider': self.provider_name,
            'retry_after': self.retry_after,
            'is_recoverable': self.is_recoverable,
        }


@dataclass
class ProviderResult:
    success: bool
    data: Optional[Any] = None
    provider_name: Optional[str] = None
    data_type: Optional[DataType] = None
    error: Optional[ProviderError] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    fallback_used: bool = False
    fallback_chain: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            'success': self.success,
            'provider': self.provider_name,
            'data_type': self.data_type.value if self.data_type else None,
            'fallback_used': self.fallback_used,
            'fallback_chain': self.fallback_chain,
        }
        if self.data is not None:
            result['data'] = self.data
        if self.error:
            result['error'] = self.error.to_dict()
        if self.metadata:
            result['metadata'] = self.metadata
        return result


@dataclass
class ProviderInfo:
    name: str
    display_name: str
    is_free: bool
    capabilities: List[ProviderCapability]
    priority: int
    requires_auth: bool = False
    auth_configured: bool = False
    status: ProviderStatus = ProviderStatus.AVAILABLE
    error_count: int = 0
    last_error: Optional[str] = None
    last_success: Optional[datetime] = None
    rate_limit_reset: Optional[datetime] = None


class BaseProvider(ABC):
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._status = ProviderStatus.AVAILABLE
        self._error_count: int = 0
        self._last_error: Optional[str] = None
        self._last_success: Optional[datetime] = None
        self._rate_limit_reset: Optional[datetime] = None
        self._max_retries: int = self.config.get('max_retries', 3)
        self._retry_delay: float = self.config.get('retry_delay', 1.0)
        self._timeout: int = self.config.get('timeout', 15)

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def display_name(self) -> str:
        pass

    @property
    @abstractmethod
    def is_free(self) -> bool:
        pass

    @property
    @abstractmethod
    def capabilities(self) -> List[ProviderCapability]:
        pass

    @property
    @abstractmethod
    def priority(self) -> int:
        pass

    @property
    def requires_auth(self) -> bool:
        return False

    @property
    def is_configured(self) -> bool:
        return True

    def get_info(self) -> ProviderInfo:
        return ProviderInfo(
            name=self.name,
            display_name=self.display_name,
            is_free=self.is_free,
            capabilities=self.capabilities,
            priority=self.priority,
            requires_auth=self.requires_auth,
            auth_configured=self.is_configured,
            status=self._status,
            error_count=self._error_count,
            last_error=self._last_error,
            last_success=self._last_success,
            rate_limit_reset=self._rate_limit_reset,
        )

    def has_capability(self, capability: ProviderCapability) -> bool:
        return capability in self.capabilities

    def is_available(self) -> bool:
        if self._status == ProviderStatus.RATE_LIMITED:
            if self._rate_limit_reset and datetime.now() > self._rate_limit_reset:
                self._status = ProviderStatus.AVAILABLE
                self._rate_limit_reset = None
        return self._status in (ProviderStatus.AVAILABLE, ProviderStatus.DEGRADED)

    def _mark_success(self) -> None:
        self._error_count = 0
        self._last_success = datetime.now()
        if self._status == ProviderStatus.DEGRADED:
            self._status = ProviderStatus.AVAILABLE

    def _mark_error(self, error: ProviderError) -> None:
        self._error_count += 1
        self._last_error = error.message
        if error.error_type == ErrorType.RATE_LIMITED:
            self._status = ProviderStatus.RATE_LIMITED
            if error.retry_after:
                self._rate_limit_reset = datetime.now() + timedelta(seconds=error.retry_after)
        elif error.error_type in (ErrorType.AUTH_ERROR, ErrorType.QUOTA_EXCEEDED):
            self._status = ProviderStatus.UNAVAILABLE
        elif self._error_count >= 3:
            self._status = ProviderStatus.DEGRADED

    def _create_error(self, error_type: ErrorType, message: str,
                      original_error: Optional[Exception] = None,
                      retry_after: Optional[int] = None) -> ProviderError:
        is_recoverable = error_type not in (ErrorType.AUTH_ERROR, ErrorType.QUOTA_EXCEEDED)
        return ProviderError(
            error_type=error_type,
            message=message,
            provider_name=self.name,
            original_error=original_error,
            retry_after=retry_after,
            is_recoverable=is_recoverable,
        )

    def _create_result(self, data: Any, data_type: DataType,
                       metadata: Optional[Dict[str, Any]] = None) -> ProviderResult:
        self._mark_success()
        return ProviderResult(
            success=True,
            data=data,
            provider_name=self.name,
            data_type=data_type,
            metadata=metadata or {},
        )

    def _create_error_result(self, error: ProviderError,
                             data_type: Optional[DataType] = None) -> ProviderResult:
        self._mark_error(error)
        return ProviderResult(
            success=False,
            error=error,
            provider_name=self.name,
            data_type=data_type,
        )

    def _not_supported(self, capability: str, data_type: DataType) -> ProviderResult:
        return self._create_error_result(
            self._create_error(
                ErrorType.NOT_SUPPORTED,
                f"{self.display_name}不支持{capability}数据",
            ),
            data_type,
        )

    def _http_request(self, url: str, params: Optional[Dict] = None,
                      headers: Optional[Dict] = None,
                      data_type: Optional[DataType] = None) -> ProviderResult:
        if not REQUESTS_AVAILABLE:
            return self._create_error_result(
                self._create_error(ErrorType.CONNECTION_ERROR, "requests库未安装"),
                data_type,
            )
        for attempt in range(self._max_retries):
            try:
                if attempt > 0:
                    delay = self._retry_delay * (2 ** attempt) + random.uniform(0, 1)
                    time.sleep(delay)
                response = requests.get(
                    url, params=params, headers=headers,
                    timeout=self._timeout,
                )
                if response.status_code == 200:
                    return self._create_result(response, data_type or DataType.REALTIME)
                elif response.status_code == 429:
                    retry_after = 60 + random.randint(0, 10)
                    return self._create_error_result(
                        self._create_error(
                            ErrorType.RATE_LIMITED,
                            f"API限流，需等待{retry_after}秒",
                            retry_after=retry_after,
                        ),
                        data_type,
                    )
                else:
                    return self._create_error_result(
                        self._create_error(
                            ErrorType.HTTP_ERROR,
                            f"HTTP错误: {response.status_code}",
                        ),
                        data_type,
                    )
            except requests.exceptions.Timeout:
                if attempt < self._max_retries - 1:
                    continue
                return self._create_error_result(
                    self._create_error(ErrorType.TIMEOUT, "请求超时"),
                    data_type,
                )
            except requests.exceptions.ConnectionError as e:
                if attempt < self._max_retries - 1:
                    continue
                return self._create_error_result(
                    self._create_error(ErrorType.CONNECTION_ERROR, f"连接错误: {e}"),
                    data_type,
                )
            except Exception as e:
                return self._create_error_result(
                    self._create_error(ErrorType.UNKNOWN, f"未知错误: {e}"),
                    data_type,
                )
        return self._create_error_result(
            self._create_error(ErrorType.UNKNOWN, "重试次数耗尽"),
            data_type,
        )

    @abstractmethod
    def fetch_realtime(self, code: str) -> ProviderResult:
        pass

    @abstractmethod
    def fetch_daily_kline(self, code: str, days: int = 250,
                          start_date: Optional[str] = None,
                          end_date: Optional[str] = None) -> ProviderResult:
        pass

    @abstractmethod
    def fetch_minute_kline(self, code: str, klt: int = 5,
                           days: int = 5) -> ProviderResult:
        pass

    @abstractmethod
    def fetch_valuation(self, code: str) -> ProviderResult:
        pass

    @abstractmethod
    def fetch_fund_flow(self, code: str, days: int = 100) -> ProviderResult:
        pass

    @abstractmethod
    def fetch_stock_list(self, board: str = 'a_share') -> ProviderResult:
        pass

    def fetch_financial(self, code: str, report_type: str = 'income') -> ProviderResult:
        return self._not_supported("财务", DataType.FINANCIAL)
