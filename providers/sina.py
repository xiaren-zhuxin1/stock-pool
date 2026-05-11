import requests
import time
import random
import re
from typing import Optional, List, Dict, Any
from .base import (
    BaseProvider, ProviderCapability, ProviderResult, DataType,
    ProviderError, ErrorType,
)


class SinaProvider(BaseProvider):
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._base_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': '*/*',
            'Referer': 'https://finance.sina.com.cn/',
        }

    @property
    def name(self) -> str:
        return 'sina'

    @property
    def display_name(self) -> str:
        return '新浪财经'

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
        return 2

    def _get_market_code(self, code: str) -> str:
        if code.startswith('6'):
            return f"sh{code}"
        return f"sz{code}"

    def _request(self, url: str, params: Optional[Dict] = None) -> ProviderResult:
        for attempt in range(self._max_retries):
            try:
                if attempt > 0:
                    delay = self._retry_delay * (2 ** attempt) + random.uniform(0, 1)
                    time.sleep(delay)

                response = requests.get(url, params=params, headers=self._base_headers,
                                       timeout=self._timeout)
                
                if response.status_code == 200:
                    return self._create_result(response, DataType.REALTIME)
                elif response.status_code == 429:
                    retry_after = 60 + random.randint(0, 10)
                    return self._create_error_result(
                        self._create_error(ErrorType.RATE_LIMITED,
                                          f"API限流，需等待{retry_after}秒",
                                          retry_after=retry_after),
                    )
                else:
                    return self._create_error_result(
                        self._create_error(ErrorType.HTTP_ERROR,
                                          f"HTTP错误: {response.status_code}"),
                    )
            except requests.exceptions.Timeout:
                if attempt < self._max_retries - 1:
                    continue
                return self._create_error_result(
                    self._create_error(ErrorType.TIMEOUT, "请求超时"),
                )
            except requests.exceptions.ConnectionError as e:
                if attempt < self._max_retries - 1:
                    continue
                return self._create_error_result(
                    self._create_error(ErrorType.CONNECTION_ERROR, f"连接错误: {e}"),
                )
            except Exception as e:
                return self._create_error_result(
                    self._create_error(ErrorType.UNKNOWN, f"未知错误: {e}"),
                )
        return self._create_error_result(
            self._create_error(ErrorType.UNKNOWN, "重试次数耗尽"),
        )

    def fetch_realtime(self, code: str) -> ProviderResult:
        market_code = self._get_market_code(code)
        url = f"https://hq.sinajs.cn/list={market_code}"
        
        result = self._request(url)
        if not result.success:
            result.data_type = DataType.REALTIME
            return result
        
        try:
            text = result.data.text
            if not text or 'hq_str_' not in text:
                return self._create_error_result(
                    self._create_error(ErrorType.DATA_ERROR, "未获取到股票数据"),
                    DataType.REALTIME,
                )
            
            match = re.search(r'="([^"]*)"', text)
            if not match:
                return self._create_error_result(
                    self._create_error(ErrorType.DATA_ERROR, "数据格式错误"),
                    DataType.REALTIME,
                )
            
            parts = match.group(1).split(',')
            if len(parts) < 32:
                return self._create_error_result(
                    self._create_error(ErrorType.DATA_ERROR, "数据字段不完整"),
                    DataType.REALTIME,
                )
            
            realtime_data = {
                'code': code,
                'name': parts[0],
                'open': float(parts[1]) if parts[1] else None,
                'pre_close': float(parts[2]) if parts[2] else None,
                'price': float(parts[3]) if parts[3] else None,
                'high': float(parts[4]) if parts[4] else None,
                'low': float(parts[5]) if parts[5] else None,
                'volume': float(parts[8]) if parts[8] else None,
                'amount': float(parts[9]) if parts[9] else None,
                'data_source': self.name,
            }
            
            if realtime_data['pre_close'] and realtime_data['price']:
                realtime_data['change_pct'] = (
                    (realtime_data['price'] - realtime_data['pre_close']) 
                    / realtime_data['pre_close'] * 100
                )
            
            missing = [k for k, v in realtime_data.items()
                      if k not in ['data_source', 'change_pct'] and v is None]
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
        url = "https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData"
        params = {
            'symbol': market_code,
            'scale': '240',
            'ma': 'no',
            'datalen': str(days),
        }
        
        result = self._request(url, params)
        if not result.success:
            result.data_type = DataType.DAILY_KLINE
            return result
        
        try:
            data = result.data.json()
            if not data or not isinstance(data, list):
                return self._create_error_result(
                    self._create_error(ErrorType.DATA_ERROR, "未获取到K线数据"),
                    DataType.DAILY_KLINE,
                )
            
            klines = []
            for item in data:
                if isinstance(item, dict):
                    klines.append(
                        f"{item.get('day')},{item.get('open')},{item.get('close')},"
                        f"{item.get('high')},{item.get('low')},{item.get('volume')},"
                        f"{item.get('amount', 0)}"
                    )
            
            return self._create_result(klines, DataType.DAILY_KLINE,
                                       {'count': len(klines)})
        except Exception as e:
            return self._create_error_result(
                self._create_error(ErrorType.DATA_ERROR, f"K线数据解析失败: {e}"),
                DataType.DAILY_KLINE,
            )

    def fetch_minute_kline(self, code: str, klt: int = 5,
                           days: int = 5) -> ProviderResult:
        return self._create_error_result(
            self._create_error(ErrorType.INVALID_PARAMS,
                              "新浪财经不支持分钟K线数据"),
            DataType.MINUTE_KLINE,
        )

    def fetch_valuation(self, code: str) -> ProviderResult:
        return self._create_error_result(
            self._create_error(ErrorType.INVALID_PARAMS,
                              "新浪财经不支持估值数据，请使用东方财富"),
            DataType.VALUATION,
        )

    def fetch_fund_flow(self, code: str, days: int = 100) -> ProviderResult:
        return self._create_error_result(
            self._create_error(ErrorType.INVALID_PARAMS,
                              "新浪财经不支持资金流向数据，请使用东方财富"),
            DataType.FUND_FLOW,
        )

    def fetch_stock_list(self, board: str = 'a_share') -> ProviderResult:
        return self._create_error_result(
            self._create_error(ErrorType.INVALID_PARAMS,
                              "新浪财经不支持股票列表数据，请使用东方财富"),
            DataType.STOCK_LIST,
        )
