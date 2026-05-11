try:
    from .base import (
        BaseProvider,
        ProviderCapability,
        ProviderStatus,
        ProviderResult,
        DataType,
    )
    from .eastmoney import EastMoneyProvider
    from .sina import SinaProvider
    from .tushare import TuShareProvider
    from .akshare import AkShareProvider
except ImportError:
    from base import (
        BaseProvider,
        ProviderCapability,
        ProviderStatus,
        ProviderResult,
        DataType,
    )
    from eastmoney import EastMoneyProvider
    from sina import SinaProvider
    from tushare import TuShareProvider
    from akshare import AkShareProvider

__all__ = [
    'BaseProvider',
    'ProviderCapability',
    'ProviderStatus',
    'ProviderResult',
    'DataType',
    'EastMoneyProvider',
    'SinaProvider',
    'TuShareProvider',
    'AkShareProvider',
]
