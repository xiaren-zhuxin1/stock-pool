import json
from typing import Optional, List, Dict, Any
from .base import (
    BaseProvider, ProviderCapability, ProviderResult, DataType,
    ProviderError, ErrorType,
)


class EastMoneyProvider(BaseProvider):
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._base_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        }

    @property
    def name(self) -> str:
        return 'eastmoney'

    @property
    def display_name(self) -> str:
        return '东方财富'

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
            ProviderCapability.FUND_FLOW,
            ProviderCapability.STOCK_LIST,
        ]

    @property
    def priority(self) -> int:
        return 1

    def _get_headers(self, referer: Optional[str] = None) -> Dict[str, str]:
        headers = dict(self._base_headers)
        if referer:
            headers['Referer'] = referer
            headers['Origin'] = referer.rstrip('/')
        return headers

    def _json_request(self, url: str, params: Optional[Dict] = None,
                      referer: Optional[str] = None,
                      data_type: Optional[DataType] = None) -> ProviderResult:
        headers = self._get_headers(referer)
        result = self._http_request(url, params=params, headers=headers, data_type=data_type)
        if not result.success:
            return result
        try:
            parsed = result.data.json()
            return self._create_result(parsed, data_type or DataType.REALTIME)
        except json.JSONDecodeError as e:
            return self._create_error_result(
                self._create_error(ErrorType.DATA_ERROR, f"JSON解析失败: {e}"),
                data_type,
            )

    def _get_market_code(self, code: str) -> str:
        if code.startswith('6'):
            market = '1'
        elif code.startswith(('4', '8')):
            market = '0'
        else:
            market = '0'
        return f"{market}.{code}"

    @staticmethod
    def _scaled_quote_value(data: Dict[str, Any], field: str, scale_field: str = 'f152') -> Optional[float]:
        value = data.get(field)
        if value in (None, '', '-'):
            return None
        try:
            scale = int(data.get(scale_field) or 0)
            return float(value) / (10 ** scale)
        except (TypeError, ValueError):
            return None

    def fetch_realtime(self, code: str) -> ProviderResult:
        secid = self._get_market_code(code)
        url = "https://push2.eastmoney.com/api/qt/stock/get"
        params = {
            'secid': secid,
            'fields': 'f57,f58,f43,f169,f170,f46,f44,f51,f168,f47,f48,f60,f45,f52,f50,f49,f171,f113,f114,f115,f117,f152,f162,f163,f164,f165,f166,f167,f39,f40,f41,f71,f83,f84,f85,f86,f92,f93,f94,f95,f96,f107,f111,f116,f124,f1,f13',
            'ut': 'fa5fd1943c7b386f1722cd924488a4d8',
        }

        result = self._json_request(url, params, referer='https://quote.eastmoney.com/', data_type=DataType.REALTIME)
        if not result.success:
            return result

        try:
            data = result.data
            if not data or 'data' not in data or not data['data']:
                return self._create_error_result(
                    self._create_error(ErrorType.DATA_ERROR, "未获取到股票数据"),
                    DataType.REALTIME,
                )

            d = data['data']
            realtime_data = {
                'code': code,
                'name': d.get('f58'),
                'price': d.get('f43') / 100 if d.get('f43') else None,
                'open': d.get('f46') / 100 if d.get('f46') else None,
                'high': d.get('f44') / 100 if d.get('f44') else None,
                'low': d.get('f45') / 100 if d.get('f45') else None,
                'pre_close': d.get('f60') / 100 if d.get('f60') else None,
                'volume': d.get('f47'),
                'amount': d.get('f48'),
                'change_pct': d.get('f170') / 100 if d.get('f170') else None,
                'pe_ttm': self._scaled_quote_value(d, 'f162'),
                'pe_lyr': self._scaled_quote_value(d, 'f163'),
                'pb': self._scaled_quote_value(d, 'f167'),
                'market_cap': d.get('f116'),
                'circ_market_cap': d.get('f117'),
                'high_52w': d.get('f44') / 100 if d.get('f44') else None,
                'low_52w': d.get('f45') / 100 if d.get('f45') else None,
                'data_source': self.name,
            }

            missing = [k for k, v in realtime_data.items()
                      if k not in ['data_source'] and v is None]
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
        secid = self._get_market_code(code)
        url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            'secid': secid,
            'fields1': 'f1,f2,f3,f4,f5,f6',
            'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62',
            'klt': '101',
            'fqt': '1',
            'end': '20500101',
            'lmt': str(days),
        }

        result = self._json_request(url, params, referer='https://quote.eastmoney.com/', data_type=DataType.DAILY_KLINE)
        if not result.success:
            return result

        try:
            data = result.data
            if not data or 'data' not in data or not data['data']:
                return self._create_error_result(
                    self._create_error(ErrorType.DATA_ERROR, "未获取到K线数据"),
                    DataType.DAILY_KLINE,
                )

            klines = data['data'].get('klines', [])
            return self._create_result(klines, DataType.DAILY_KLINE,
                                       {'count': len(klines)})
        except Exception as e:
            return self._create_error_result(
                self._create_error(ErrorType.DATA_ERROR, f"K线数据解析失败: {e}"),
                DataType.DAILY_KLINE,
            )

    def fetch_minute_kline(self, code: str, klt: int = 5,
                           days: int = 5) -> ProviderResult:
        secid = self._get_market_code(code)
        url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            'secid': secid,
            'fields1': 'f1,f2,f3,f4,f5,f6',
            'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62',
            'klt': str(klt),
            'fqt': '1',
            'end': '20500101',
            'lmt': str(days * 240 // klt),
        }

        result = self._json_request(url, params, referer='https://quote.eastmoney.com/', data_type=DataType.MINUTE_KLINE)
        if not result.success:
            return result

        try:
            data = result.data
            if not data or 'data' not in data or not data['data']:
                return self._create_error_result(
                    self._create_error(ErrorType.DATA_ERROR, "未获取到分钟K线数据"),
                    DataType.MINUTE_KLINE,
                )

            klines = data['data'].get('klines', [])
            return self._create_result(klines, DataType.MINUTE_KLINE,
                                       {'count': len(klines), 'klt': klt})
        except Exception as e:
            return self._create_error_result(
                self._create_error(ErrorType.DATA_ERROR, f"分钟K线数据解析失败: {e}"),
                DataType.MINUTE_KLINE,
            )

    def fetch_valuation(self, code: str) -> ProviderResult:
        return self.fetch_realtime(code)

    def fetch_fund_flow(self, code: str, days: int = 100) -> ProviderResult:
        secid = self._get_market_code(code)
        url = "https://push2his.eastmoney.com/api/qt/stock/fflow/kline/get"
        params = {
            'secid': secid,
            'fields1': 'f1,f2,f3,f7',
            'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65',
            'klt': '101',
            'lmt': str(days),
        }

        result = self._json_request(url, params, referer='https://quote.eastmoney.com/', data_type=DataType.FUND_FLOW)
        if not result.success:
            return result

        try:
            data = result.data
            if not data or 'data' not in data or not data['data']:
                return self._create_error_result(
                    self._create_error(ErrorType.DATA_ERROR, "未获取到资金流向数据"),
                    DataType.FUND_FLOW,
                )

            klines = data['data'].get('klines', [])
            return self._create_result(klines, DataType.FUND_FLOW,
                                       {'count': len(klines)})
        except Exception as e:
            return self._create_error_result(
                self._create_error(ErrorType.DATA_ERROR, f"资金流向数据解析失败: {e}"),
                DataType.FUND_FLOW,
            )

    def fetch_stock_list(self, board: str = 'a_share') -> ProviderResult:
        board_map = {
            'a_share': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23',
            'main': 'm:1+t:2,m:0+t:6',
            'gem': 'm:0+t:80',
            'star': 'm:1+t:23',
            'sh_main': 'm:1+t:2',
            'sz_main': 'm:0+t:6',
            'bse': 'm:0+t:81,m:1+t:23',
            'hs_a': 'm:1+t:2,m:0+t:6,m:0+t:80,m:1+t:23',
        }

        market = board_map.get(board, board_map['a_share'])
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            'pn': '1',
            'pz': '5000',
            'po': '1',
            'np': '1',
            'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
            'fltt': '2',
            'invt': '2',
            'fid': 'f3',
            'fs': market,
            'fields': 'f12,f14,f2,f3,f4,f5,f6,f7,f9,f15,f16,f17,f18,f20,f21,f23,f24,f25,f22,f11,f62,f128,f136,f115,f152',
        }

        result = self._json_request(url, params, referer='https://quote.eastmoney.com/', data_type=DataType.STOCK_LIST)
        if not result.success:
            return result

        try:
            data = result.data
            if not data or 'data' not in data or not data['data']:
                return self._create_error_result(
                    self._create_error(ErrorType.DATA_ERROR, "未获取到股票列表"),
                    DataType.STOCK_LIST,
                )

            diff = data['data'].get('diff', [])
            stocks = []
            for item in diff:
                stock_code = str(item.get('f12', ''))
                stocks.append({
                    'code': stock_code,
                    'name': item.get('f14'),
                    'market': 'SH' if stock_code.startswith('6') else ('BJ' if stock_code.startswith(('4', '8')) else 'SZ'),
                    'close': item.get('f2'),
                    'change_pct': item.get('f3'),
                    'pe_ttm': item.get('f9') if item.get('f9') not in (None, '', '-') else item.get('f115'),
                    'pb': item.get('f23'),
                    'market_cap': item.get('f20'),
                    'circ_market_cap': item.get('f21'),
                    'data_source': self.name,
                })

            return self._create_result(stocks, DataType.STOCK_LIST,
                                       {'board': board, 'count': len(stocks)})
        except Exception as e:
            return self._create_error_result(
                self._create_error(ErrorType.DATA_ERROR, f"股票列表解析失败: {e}"),
                DataType.STOCK_LIST,
            )
