import os
import sys
import builtins
import time
from typing import Optional, List, Dict, Any, Type
from datetime import datetime, timedelta

try:
    from .providers.base import (
        BaseProvider, ProviderCapability, ProviderResult, DataType,
        ProviderError, ErrorType, ProviderInfo,
    )
    from .providers.eastmoney import EastMoneyProvider
    from .providers.sina import SinaProvider
    from .providers.akshare import AkShareProvider
    from .providers.tushare import TuShareProvider
    from .providers.tencent import TencentProvider
    from .providers.netease import NeteaseProvider
    from .providers.baostock import BaostockProvider
except ImportError:
    from providers.base import (
        BaseProvider, ProviderCapability, ProviderResult, DataType,
        ProviderError, ErrorType, ProviderInfo,
    )
    from providers.eastmoney import EastMoneyProvider
    from providers.sina import SinaProvider
    from providers.akshare import AkShareProvider
    from providers.tushare import TuShareProvider
    from providers.tencent import TencentProvider
    from providers.netease import NeteaseProvider
    from providers.baostock import BaostockProvider


def _log(*args, **kwargs):
    kwargs.setdefault('file', sys.stderr)
    return builtins.print(*args, **kwargs)


class ProviderManager:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._providers: Dict[str, BaseProvider] = {}
        self._capability_providers: Dict[ProviderCapability, List[str]] = {}
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl: int = self.config.get('cache_ttl', 300)
        self._enable_cache: bool = self.config.get('enable_cache', False)
        self._provider_cooldown: Dict[str, datetime] = {}
        self._cooldown_seconds: int = self.config.get('cooldown_seconds', 300)
        self._init_providers()
        self._build_capability_index()

    def _init_providers(self) -> None:
        provider_classes: List[Type[BaseProvider]] = [
            EastMoneyProvider,
            SinaProvider,
            AkShareProvider,
            TencentProvider,
            NeteaseProvider,
        ]

        tushare_token = os.environ.get('TUSHARE_TOKEN') or self.config.get('tushare_token')
        if tushare_token:
            provider_classes.append(TuShareProvider)

        try:
            import baostock
            provider_classes.append(BaostockProvider)
        except ImportError:
            pass

        for provider_class in provider_classes:
            provider_name = provider_class.__name__.replace('Provider', '').lower()
            provider_config = self.config.get(provider_name, {})
            if provider_class == TuShareProvider:
                provider_config['token'] = tushare_token

            try:
                provider = provider_class(provider_config)
                self._providers[provider.name] = provider
                _log(f"[ProviderManager] 已加载: {provider.display_name} (优先级: {provider.priority})")
            except Exception as e:
                _log(f"[ProviderManager] 加载失败 {provider_class.__name__}: {e}")

    def _build_capability_index(self) -> None:
        self._capability_providers = {}
        for capability in ProviderCapability:
            providers = []
            for name, provider in self._providers.items():
                if provider.has_capability(capability):
                    providers.append(name)
            providers.sort(key=lambda n: self._providers[n].priority)
            self._capability_providers[capability] = providers

    def get_provider(self, name: str) -> Optional[BaseProvider]:
        return self._providers.get(name)

    def get_all_providers(self) -> Dict[str, BaseProvider]:
        return dict(self._providers)

    def get_provider_info(self, name: str) -> Optional[ProviderInfo]:
        provider = self._providers.get(name)
        if provider:
            return provider.get_info()
        return None

    def get_all_provider_info(self) -> List[ProviderInfo]:
        return [p.get_info() for p in self._providers.values()]

    def get_providers_for_capability(self, capability: ProviderCapability) -> List[str]:
        return list(self._capability_providers.get(capability, []))

    def _get_cache_key(self, capability: ProviderCapability, **kwargs: Any) -> str:
        key_parts = [capability.value]
        for k, v in sorted(kwargs.items()):
            if v is not None:
                key_parts.append(f"{k}={v}")
        return "|".join(key_parts)

    def _get_from_cache(self, key: str) -> Optional[Any]:
        if not self._enable_cache:
            return None
        cached = self._cache.get(key)
        if cached:
            if datetime.now() < cached['expires']:
                return cached['data']
            else:
                del self._cache[key]
        return None

    def _set_cache(self, key: str, data: Any, ttl: Optional[int] = None) -> None:
        if not self._enable_cache:
            return
        ttl = ttl or self._cache_ttl
        self._cache[key] = {
            'data': data,
            'expires': datetime.now() + timedelta(seconds=ttl),
        }

    def _execute_with_fallback(
        self,
        capability: ProviderCapability,
        method_name: str,
        provider_names: Optional[List[str]] = None,
        **kwargs: Any
    ) -> ProviderResult:
        if provider_names is None:
            provider_names = self.get_providers_for_capability(capability)

        if not provider_names:
            return ProviderResult(
                success=False,
                error=ProviderError(
                    error_type=ErrorType.INVALID_PARAMS,
                    message=f"没有可用的数据源支持: {capability.value}",
                    provider_name='ProviderManager',
                    is_recoverable=False,
                ),
                data_type=self._capability_to_data_type(capability),
            )

        fallback_chain: List[str] = []
        last_error: Optional[ProviderError] = None

        for provider_name in provider_names:
            provider = self._providers.get(provider_name)
            if not provider:
                continue
            if not provider.is_available():
                _log(f"[ProviderManager] {provider.display_name} 不可用，跳过")
                continue
            if not provider.is_configured:
                _log(f"[ProviderManager] {provider.display_name} 未配置，跳过")
                continue

            cooldown_until = self._provider_cooldown.get(provider_name)
            if cooldown_until and datetime.now() < cooldown_until:
                _log(f"[ProviderManager] {provider.display_name} 冷却中，跳过")
                continue

            fallback_chain.append(provider_name)

            cache_key = self._get_cache_key(capability, provider=provider_name, **kwargs)
            cached = self._get_from_cache(cache_key)
            if cached:
                _log(f"[ProviderManager] 命中缓存: {provider.display_name}")
                return ProviderResult(
                    success=True,
                    data=cached,
                    provider_name=provider_name,
                    data_type=self._capability_to_data_type(capability),
                    metadata={'cache_hit': True},
                )

            _log(f"[ProviderManager] 尝试: {provider.display_name}")

            try:
                method = getattr(provider, method_name)
                result = method(**kwargs)
                if result.success:
                    if result.data is not None and result.data != [] and result.data != {}:
                        self._set_cache(cache_key, result.data)
                        result.fallback_chain = fallback_chain
                        result.fallback_used = len(fallback_chain) > 1
                        return result
                    elif result.data == [] or result.data == {}:
                        _log(f"[ProviderManager] {provider.display_name} 返回空数据，继续降级")
                    else:
                        self._set_cache(cache_key, result.data)
                        result.fallback_chain = fallback_chain
                        result.fallback_used = len(fallback_chain) > 1
                        return result
                else:
                    last_error = result.error
                    _log(f"[ProviderManager] {provider.display_name} 失败: {result.error.message if result.error else 'Unknown'}")
                    self._provider_cooldown[provider_name] = datetime.now() + timedelta(seconds=self._cooldown_seconds)
                    if result.error and not result.error.is_recoverable:
                        break
            except Exception as e:
                last_error = ProviderError(
                    error_type=ErrorType.UNKNOWN,
                    message=str(e),
                    provider_name=provider_name,
                )
                _log(f"[ProviderManager] {provider.display_name} 异常: {e}")
                self._provider_cooldown[provider_name] = datetime.now() + timedelta(seconds=self._cooldown_seconds)

        error_msg = f"所有数据源均失败。尝试顺序: {', '.join(fallback_chain)}"
        if last_error:
            error_msg += f"。最后错误: {last_error.message}"

        return ProviderResult(
            success=False,
            error=ProviderError(
                error_type=last_error.error_type if last_error else ErrorType.UNKNOWN,
                message=error_msg,
                provider_name='ProviderManager',
                original_error=last_error,
                is_recoverable=True,
            ),
            data_type=self._capability_to_data_type(capability),
            fallback_chain=fallback_chain,
        )

    def _capability_to_data_type(self, capability: ProviderCapability) -> DataType:
        mapping = {
            ProviderCapability.REALTIME_QUOTE: DataType.REALTIME,
            ProviderCapability.DAILY_KLINE: DataType.DAILY_KLINE,
            ProviderCapability.MINUTE_KLINE: DataType.MINUTE_KLINE,
            ProviderCapability.VALUATION: DataType.VALUATION,
            ProviderCapability.FUND_FLOW: DataType.FUND_FLOW,
            ProviderCapability.FINANCIAL: DataType.FINANCIAL,
            ProviderCapability.STOCK_LIST: DataType.STOCK_LIST,
        }
        return mapping.get(capability, DataType.REALTIME)

    def fetch_realtime(self, code: str, providers: Optional[List[str]] = None) -> ProviderResult:
        return self._execute_with_fallback(
            ProviderCapability.REALTIME_QUOTE, 'fetch_realtime',
            provider_names=providers, code=code,
        )

    def fetch_daily_kline(self, code: str, days: int = 250,
                          start_date: Optional[str] = None,
                          end_date: Optional[str] = None,
                          providers: Optional[List[str]] = None) -> ProviderResult:
        return self._execute_with_fallback(
            ProviderCapability.DAILY_KLINE, 'fetch_daily_kline',
            provider_names=providers, code=code, days=days,
            start_date=start_date, end_date=end_date,
        )

    def get_daily_kline(self, code: str, days: int = 250,
                        start_date: Optional[str] = None,
                        end_date: Optional[str] = None,
                        providers: Optional[List[str]] = None) -> ProviderResult:
        """兼容旧调用名；新代码优先使用 fetch_daily_kline。"""
        return self.fetch_daily_kline(code, days, start_date, end_date, providers)

    def fetch_minute_kline(self, code: str, klt: int = 5, days: int = 5,
                           providers: Optional[List[str]] = None) -> ProviderResult:
        return self._execute_with_fallback(
            ProviderCapability.MINUTE_KLINE, 'fetch_minute_kline',
            provider_names=providers, code=code, klt=klt, days=days,
        )

    def fetch_valuation(self, code: str, providers: Optional[List[str]] = None) -> ProviderResult:
        return self._execute_with_fallback(
            ProviderCapability.VALUATION, 'fetch_valuation',
            provider_names=providers, code=code,
        )

    def fetch_fund_flow(self, code: str, days: int = 100,
                        providers: Optional[List[str]] = None) -> ProviderResult:
        return self._execute_with_fallback(
            ProviderCapability.FUND_FLOW, 'fetch_fund_flow',
            provider_names=providers, code=code, days=days,
        )

    def fetch_stock_list(self, board: str = 'a_share',
                         providers: Optional[List[str]] = None) -> ProviderResult:
        return self._execute_with_fallback(
            ProviderCapability.STOCK_LIST, 'fetch_stock_list',
            provider_names=providers, board=board,
        )

    def fetch_financial(self, code: str, report_type: str = 'income',
                        providers: Optional[List[str]] = None) -> ProviderResult:
        return self._execute_with_fallback(
            ProviderCapability.FINANCIAL, 'fetch_financial',
            provider_names=providers, code=code, report_type=report_type,
        )

    def clear_cache(self) -> None:
        self._cache.clear()
        _log("[ProviderManager] 缓存已清空")

    def get_status(self) -> Dict[str, Any]:
        status: Dict[str, Any] = {
            'providers': {},
            'capabilities': {},
        }
        for name, provider in self._providers.items():
            info = provider.get_info()
            status['providers'][name] = {
                'display_name': info.display_name,
                'is_free': info.is_free,
                'status': info.status.value,
                'priority': info.priority,
                'capabilities': [c.value for c in info.capabilities],
                'is_configured': info.auth_configured if info.requires_auth else True,
                'error_count': info.error_count,
                'last_error': info.last_error,
            }
        for capability, providers in self._capability_providers.items():
            status['capabilities'][capability.value] = providers
        return status
