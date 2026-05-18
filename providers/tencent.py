import json
from typing import Optional, List, Dict, Any
from .base import (
    BaseProvider, ProviderCapability, ProviderResult, DataType,
    ProviderError, ErrorType,
)


class TencentProvider(BaseProvider):
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._base_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': '*/*',
            'Referer': 'https://gu.qq.com/',
        }

    @property
    def name(self) -> str:
        return 'tencent'

    @property
    def display_name(self) -> str:
        return '腾讯财经'

    @property
    def is_free(self) -> bool:
        return True

    @property
    def capabilities(self) -> List[ProviderCapability]:
        return [
            ProviderCapability.REALTIME_QUOTE,
            ProviderCapability.DAILY_KLINE,
            ProviderCapability.MINUTE_KLINE,
            ProviderCapability.VALUATION,
        ]

    @property
    def priority(self) -> int:
        return 4

    def _get_market_code(self, code: str) -> str:
        if code.startswith('6'):
            return f"sh{code}"
        elif code.startswith(('4', '8')):
            return f"bj{code}"
        return f"sz{code}"

    @staticmethod
    def _to_float(parts: List[str], index: int, multiplier: float = 1.0) -> Optional[float]:
        if len(parts) <= index or parts[index] in ('', '-', '--'):
            return None
        return float(parts[index]) * multiplier

    def fetch_realtime(self, code: str) -> ProviderResult:
        market_code = self._get_market_code(code)
        url = f"https://qt.gtimg.cn/q={market_code}"
        result = self._http_request(url, headers=self._base_headers, data_type=DataType.REALTIME)
        if not result.success:
            return result
        try:
            text = result.data.text
            if not text or '~' not in text:
                return self._create_error_result(
                    self._create_error(ErrorType.DATA_ERROR, "未获取到股票数据"),
                    DataType.REALTIME,
                )
            parts = text.split('~')
            if len(parts) < 50:
                return self._create_error_result(
                    self._create_error(ErrorType.DATA_ERROR, "数据字段不完整"),
                    DataType.REALTIME,
                )
            realtime_data = {
                'code': code,
                'name': parts[1] if len(parts) > 1 else None,
                'price': self._to_float(parts, 3),
                'pre_close': self._to_float(parts, 4),
                'open': self._to_float(parts, 5),
                'volume': self._to_float(parts, 6),
                'high': self._to_float(parts, 33),
                'low': self._to_float(parts, 34),
                'amount': self._to_float(parts, 37),
                'change_pct': self._to_float(parts, 32),
                'pe_ttm': self._to_float(parts, 39),
                'pb': self._to_float(parts, 46),
                'market_cap': self._to_float(parts, 45, 100000000),
                'circ_market_cap': self._to_float(parts, 44, 100000000),
                'data_source': self.name,
            }
            if realtime_data['price'] and realtime_data['pre_close']:
                if realtime_data['change_pct'] is None:
                    realtime_data['change_pct'] = round(
                        (realtime_data['price'] - realtime_data['pre_close'])
                        / realtime_data['pre_close'] * 100, 2
                    )
            missing = [k for k, v in realtime_data.items()
                      if k not in ('data_source', 'change_pct') and v is None]
            realtime_data['missing_fields'] = missing
            realtime_data['data_quality'] = 'full' if not missing else 'partial'
            return self._create_result(realtime_data, DataType.REALTIME)
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            _log(f"[{self.display_name}] 数据解析错误: {e}")
            return self._create_error_result(
                self._create_error(ErrorType.DATA_ERROR, f"数据解析失败: {e}", e),
                DataType.REALTIME,
            )
        except Exception as e:
            _log(f"[{self.display_name}] 未预期的错误: {e}")
            return self._create_error_result(
                self._create_error(ErrorType.DATA_ERROR, f"数据解析失败: {e}", e),
                DataType.REALTIME,
            )

    def fetch_daily_kline(self, code: str, days: int = 250,
                          start_date: Optional[str] = None,
                          end_date: Optional[str] = None) -> ProviderResult:
        market_code = self._get_market_code(code)
        url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        params = {
            '_var': f'kline_dayqfq{market_code}',
            'param': f'{market_code},day,,,,{days},qfq',
        }
        result = self._http_request(url, params=params, headers=self._base_headers, data_type=DataType.DAILY_KLINE)
        if not result.success:
            return result
        try:
            text = result.data.text
            prefix = f'kline_dayqfq{market_code}='
            if prefix in text:
                json_str = text[text.index('=') + 1:]
            else:
                json_str = text
            data = json.loads(json_str)
            if not data or 'data' not in data:
                return self._create_error_result(
                    self._create_error(ErrorType.DATA_ERROR, "未获取到K线数据"),
                    DataType.DAILY_KLINE,
                )
            stock_data = data['data'].get(market_code, {})
            day_data = stock_data.get('qfqday') or stock_data.get('day', [])
            klines = []
            for item in day_data:
                if len(item) >= 6:
                    klines.append(
                        f"{item[0]},{item[1]},{item[2]},{item[3]},{item[4]},{item[5]},0"
                    )
            return self._create_result(klines, DataType.DAILY_KLINE,
                                       {'count': len(klines)})
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            _log(f"[{self.display_name}] 数据解析错误: {e}")
            return self._create_error_result(
                self._create_error(ErrorType.DATA_ERROR, f"数据解析失败: {e}", e),
                DataType.DAILY_KLINE,
            )
        except Exception as e:
            _log(f"[{self.display_name}] 未预期的错误: {e}")
            return self._create_error_result(
                self._create_error(ErrorType.DATA_ERROR, f"数据解析失败: {e}", e),
                DataType.DAILY_KLINE,
            )

    def fetch_minute_kline(self, code: str, klt: int = 5,
                           days: int = 5) -> ProviderResult:
        market_code = self._get_market_code(code)
        klt_map = {1: 'm1', 5: 'm5', 15: 'm15', 30: 'm30', 60: 'm60'}
        klt_name = klt_map.get(klt, 'm5')
        url = "https://web.ifzq.gtimg.cn/appstock/app/kline/mkline"
        params = {
            'param': f'{market_code},{klt_name},320',
        }
        result = self._http_request(url, params=params, headers=self._base_headers, data_type=DataType.MINUTE_KLINE)
        if not result.success:
            return result
        try:
            text = result.data.text
            data = json.loads(text)
            if not data or 'data' not in data:
                return self._create_error_result(
                    self._create_error(ErrorType.DATA_ERROR, "未获取到分钟K线数据"),
                    DataType.MINUTE_KLINE,
                )
            stock_data = data['data'].get(market_code, {})
            minute_data = stock_data.get(klt_name, [])
            klines = []
            for item in minute_data:
                if len(item) >= 6:
                    klines.append(
                        f"{item[0]},{item[1]},{item[2]},{item[3]},{item[4]},{item[5]},0"
                    )
            return self._create_result(klines, DataType.MINUTE_KLINE,
                                       {'count': len(klines), 'klt': klt})
        except Exception as e:
            return self._create_error_result(
                self._create_error(ErrorType.DATA_ERROR, f"分钟K线数据解析失败: {e}"),
                DataType.MINUTE_KLINE,
            )

    def fetch_valuation(self, code: str) -> ProviderResult:
        result = self.fetch_realtime(code)
        if result.success:
            result.data_type = DataType.VALUATION
        return result

    def fetch_fund_flow(self, code: str, days: int = 100) -> ProviderResult:
        return self._not_supported("资金流向", DataType.FUND_FLOW)

    def fetch_stock_list(self, board: str = 'a_share') -> ProviderResult:
        return self._not_supported("股票列表", DataType.STOCK_LIST)
