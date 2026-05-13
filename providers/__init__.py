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
    from .akshare import AkShareProvider
    from .tushare import TuShareProvider
    from .tencent import TencentProvider
    from .netease import NeteaseProvider
    from .baostock import BaostockProvider
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
    from akshare import AkShareProvider
    from tushare import TuShareProvider
    from tencent import TencentProvider
    from netease import NeteaseProvider
    from baostock import BaostockProvider

__all__ = [
    'BaseProvider',
    'ProviderCapability',
    'ProviderStatus',
    'ProviderResult',
    'DataType',
    'EastMoneyProvider',
    'SinaProvider',
    'AkShareProvider',
    'TuShareProvider',
    'TencentProvider',
    'NeteaseProvider',
    'BaostockProvider',
]
