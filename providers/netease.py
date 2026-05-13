import json
from typing import Optional, List, Dict, Any
from .base import (
    BaseProvider, ProviderCapability, ProviderResult, DataType,
    ProviderError, ErrorType,
)


class NeteaseProvider(BaseProvider):
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._base_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': '*/*',
            'Referer': 'https://quotes.money.163.com/',
        }

    @property
    def name(self) -> str:
        return 'netease'

    @property
    def display_name(self) -> str:
        return '网易财经'

    @property
    def is_free(self) -> bool:
        return True

    @property
    def capabilities(self) -> List[ProviderCapability]:
        return [
            ProviderCapability.REALTIME_QUOTE,
            ProviderCapability.DAILY_KLINE,
        ]

    @property
    def priority(self) -> int:
        return 5

    def _get_market_code(self, code: str) -> str:
        if code.startswith('6'):
            return f"0{code}"
        elif code.startswith(('4', '8')):
            return f"0{code}"
        return f"1{code}"

    def fetch_realtime(self, code: str) -> ProviderResult:
        market_code = self._get_market_code(code)
        url = f"https://api.money.126.net/data/feed/{market_code}"
        result = self._http_request(url, headers=self._base_headers, data_type=DataType.REALTIME)
        if not result.success:
            return result
        try:
            text = result.data.text
            prefix = f'_ntes_quote_callback({market_code}:'
            suffix = ');'
            if prefix in text:
                json_str = text[text.index(prefix) + len(prefix):text.rindex(suffix)]
            else:
                json_str = text
            data = json.loads(json_str)
            if not data:
                return self._create_error_result(
                    self._create_error(ErrorType.DATA_ERROR, "未获取到股票数据"),
                    DataType.REALTIME,
                )
            realtime_data = {
                'code': code,
                'name': data.get('name'),
                'price': float(data['price']) if data.get('price') else None,
                'open': float(data['open']) if data.get('open') else None,
                'high': float(data['high']) if data.get('high') else None,
                'low': float(data['low']) if data.get('low') else None,
                'pre_close': float(data['yestclose']) if data.get('yestclose') else None,
                'volume': float(data['volume']) if data.get('volume') else None,
                'amount': float(data['turnover']) if data.get('turnover') else None,
                'change_pct': float(data['percent']) if data.get('percent') else None,
                'data_source': self.name,
            }
            missing = [k for k, v in realtime_data.items()
                      if k not in ('data_source', 'change_pct') and v is None]
            realtime_data['missing_fields'] = missing
            realtime_data['data_quality'] = 'full' if not missing else 'partial'
            return self._create_result(realtime_data, DataType.REALTIME)
        except Exception as e:
            return self._create_error_result(
                self._create_error(ErrorType.DATA_ERROR, f"数据解析失败: {e}"),
                DataType.REALTIME,
            )

    def fetch_daily_kline(self, code: str, days: int = 250,
                          start_date: Optional[str] = None,
                          end_date: Optional[str] = None) -> ProviderResult:
        market_code = self._get_market_code(code)
        url = "https://quotes.money.163.com/service/chddata.html"
        params = {
            'code': market_code,
            'start': start_date.replace('-', '') if start_date else '19900101',
            'end': end_date.replace('-', '') if end_date else '20991231',
            'fields': 'TOPEN;HIGH;LOW;TCLOSE;VOTURNOVER;TURNOVER',
        }
        result = self._http_request(url, params=params, headers=self._base_headers, data_type=DataType.DAILY_KLINE)
        if not result.success:
            return result
        try:
            text = result.data.text
            lines = text.strip().split('\n')
            if len(lines) < 2:
                return self._create_error_result(
                    self._create_error(ErrorType.DATA_ERROR, "未获取到K线数据"),
                    DataType.DAILY_KLINE,
                )
            klines = []
            for line in lines[1:]:
                parts = line.split(',')
                if len(parts) >= 7 and parts[3] and parts[3] != 'None':
                    klines.append(
                        f"{parts[0]},{parts[3]},{parts[6]},{parts[4]},{parts[5]},{parts[7]},{parts[8]}"
                    )
            klines.reverse()
            klines = klines[-days:] if len(klines) > days else klines
            return self._create_result(klines, DataType.DAILY_KLINE,
                                       {'count': len(klines)})
        except Exception as e:
            return self._create_error_result(
                self._create_error(ErrorType.DATA_ERROR, f"K线数据解析失败: {e}"),
                DataType.DAILY_KLINE,
            )

    def fetch_minute_kline(self, code: str, klt: int = 5,
                           days: int = 5) -> ProviderResult:
        return self._not_supported("分钟K线", DataType.MINUTE_KLINE)

    def fetch_valuation(self, code: str) -> ProviderResult:
        return self._not_supported("估值", DataType.VALUATION)

    def fetch_fund_flow(self, code: str, days: int = 100) -> ProviderResult:
        return self._not_supported("资金流向", DataType.FUND_FLOW)

    def fetch_stock_list(self, board: str = 'a_share') -> ProviderResult:
        return self._not_supported("股票列表", DataType.STOCK_LIST)
