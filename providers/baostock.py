import time
import random
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from .base import (
    BaseProvider, ProviderCapability, ProviderResult, DataType,
    ProviderError, ErrorType,
)

try:
    import baostock as bs
    BAOSTOCK_AVAILABLE = True
except ImportError:
    BAOSTOCK_AVAILABLE = False


class BaostockProvider(BaseProvider):
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._logged_in = False

    @property
    def name(self) -> str:
        return 'baostock'

    @property
    def display_name(self) -> str:
        return 'Baostock'

    @property
    def is_free(self) -> bool:
        return True

    @property
    def capabilities(self) -> List[ProviderCapability]:
        return [
            ProviderCapability.DAILY_KLINE,
            ProviderCapability.MINUTE_KLINE,
            ProviderCapability.VALUATION,
            ProviderCapability.STOCK_LIST,
        ]

    @property
    def priority(self) -> int:
        return 6

    @property
    def is_configured(self) -> bool:
        return BAOSTOCK_AVAILABLE

    def _ensure_login(self) -> bool:
        if not BAOSTOCK_AVAILABLE:
            return False
        if not self._logged_in:
            try:
                lg = bs.login()
                self._logged_in = lg.error_code == '0'
            except Exception:
                self._logged_in = False
        return self._logged_in

    def _logout(self) -> None:
        if self._logged_in and BAOSTOCK_AVAILABLE:
            try:
                bs.logout()
            except Exception:
                pass
            self._logged_in = False

    def _get_bs_code(self, code: str) -> str:
        if code.startswith('6'):
            suffix = '.SH'
        elif code.startswith(('4', '8')):
            suffix = '.BJ'
        else:
            suffix = '.SZ'
        return f"{code}{suffix}"

    def _handle_api_error(self, e: Exception) -> ProviderError:
        error_msg = str(e).lower()
        if 'timeout' in error_msg:
            return self._create_error(ErrorType.TIMEOUT, f"请求超时: {e}")
        elif 'connection' in error_msg:
            return self._create_error(ErrorType.CONNECTION_ERROR, f"连接错误: {e}")
        else:
            return self._create_error(ErrorType.UNKNOWN, f"未知错误: {e}")

    def fetch_realtime(self, code: str) -> ProviderResult:
        return self._not_supported("实时行情", DataType.REALTIME)

    def fetch_daily_kline(self, code: str, days: int = 250,
                          start_date: Optional[str] = None,
                          end_date: Optional[str] = None) -> ProviderResult:
        if not self._ensure_login():
            return self._create_error_result(
                self._create_error(ErrorType.AUTH_ERROR,
                                  "Baostock未安装或登录失败，请执行: pip install baostock"),
                DataType.DAILY_KLINE,
            )
        try:
            bs_code = self._get_bs_code(code)
            if not end_date:
                end_date = datetime.now().strftime('%Y-%m-%d')
            if not start_date:
                start_date = (datetime.now() - timedelta(days=days * 2)).strftime('%Y-%m-%d')

            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,open,high,low,close,volume,amount",
                start_date=start_date,
                end_date=end_date,
                frequency="d",
                adjustflag="2",
            )

            klines = []
            while rs.error_code == '0' and rs.next():
                row = rs.get_row_data()
                if row and len(row) >= 7:
                    klines.append(','.join(row[:7]))

            if not klines:
                return self._create_error_result(
                    self._create_error(ErrorType.DATA_ERROR, "未获取到K线数据"),
                    DataType.DAILY_KLINE,
                )

            return self._create_result(klines, DataType.DAILY_KLINE,
                                       {'count': len(klines)})
        except Exception as e:
            return self._create_error_result(
                self._handle_api_error(e),
                DataType.DAILY_KLINE,
            )

    def fetch_minute_kline(self, code: str, klt: int = 5,
                           days: int = 5) -> ProviderResult:
        if not self._ensure_login():
            return self._create_error_result(
                self._create_error(ErrorType.AUTH_ERROR, "Baostock未安装或登录失败"),
                DataType.MINUTE_KLINE,
            )
        try:
            bs_code = self._get_bs_code(code)
            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

            frequency_map = {1: '5', 5: '5', 15: '15', 30: '30', 60: '60'}
            frequency = frequency_map.get(klt, '5')

            rs = bs.query_history_k_data_plus(
                bs_code,
                "time,open,high,low,close,volume,amount",
                start_date=start_date,
                end_date=end_date,
                frequency=frequency,
                adjustflag="2",
            )

            klines = []
            while rs.error_code == '0' and rs.next():
                row = rs.get_row_data()
                if row and len(row) >= 7:
                    klines.append(','.join(row[:7]))

            if not klines:
                return self._create_error_result(
                    self._create_error(ErrorType.DATA_ERROR, "未获取到分钟K线数据"),
                    DataType.MINUTE_KLINE,
                )

            return self._create_result(klines, DataType.MINUTE_KLINE,
                                       {'count': len(klines), 'klt': klt})
        except Exception as e:
            return self._create_error_result(
                self._handle_api_error(e),
                DataType.MINUTE_KLINE,
            )

    def fetch_valuation(self, code: str) -> ProviderResult:
        if not self._ensure_login():
            return self._create_error_result(
                self._create_error(ErrorType.AUTH_ERROR, "Baostock未安装或登录失败"),
                DataType.VALUATION,
            )
        try:
            bs_code = self._get_bs_code(code)
            trade_date = datetime.now().strftime('%Y-%m-%d')

            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,peTTM,pbMRQ,psTTM",
                start_date=trade_date,
                end_date=trade_date,
                frequency="d",
            )

            while rs.error_code == '0' and rs.next():
                row = rs.get_row_data()
                if row and len(row) >= 4:
                    valuation_data = {
                        'code': code,
                        'pe_ttm': float(row[1]) if row[1] else None,
                        'pb': float(row[2]) if row[2] else None,
                        'ps_ttm': float(row[3]) if row[3] else None,
                        'data_source': self.name,
                    }
                    return self._create_result(valuation_data, DataType.VALUATION)

            return self._create_error_result(
                self._create_error(ErrorType.DATA_ERROR, "未获取到估值数据"),
                DataType.VALUATION,
            )
        except Exception as e:
            return self._create_error_result(
                self._handle_api_error(e),
                DataType.VALUATION,
            )

    def fetch_fund_flow(self, code: str, days: int = 100) -> ProviderResult:
        return self._not_supported("资金流向", DataType.FUND_FLOW)

    def fetch_stock_list(self, board: str = 'a_share') -> ProviderResult:
        if not self._ensure_login():
            return self._create_error_result(
                self._create_error(ErrorType.AUTH_ERROR, "Baostock未安装或登录失败"),
                DataType.STOCK_LIST,
            )
        try:
            rs = bs.query_stock_basic()

            stocks = []
            while rs.error_code == '0' and rs.next():
                row = rs.get_row_data()
                if not row or len(row) < 4:
                    continue
                code = row[0]
                name = row[1]
                ipo_date = row[2] if len(row) > 2 else None
                out_date = row[3] if len(row) > 3 else None

                if out_date:
                    continue
                pure_code = code.split('.')[0]
                market = code.split('.')[1] if '.' in code else 'SH'

                if board == 'main' and not (pure_code.startswith('60') or pure_code.startswith('000') or pure_code.startswith('001')):
                    continue
                elif board == 'gem' and not pure_code.startswith('300'):
                    continue
                elif board == 'star' and not pure_code.startswith('688'):
                    continue
                elif board == 'sh_main' and market != 'SH':
                    continue
                elif board == 'sz_main' and market != 'SZ':
                    continue

                stocks.append({
                    'code': pure_code,
                    'name': name,
                    'market': market,
                })

            return self._create_result(stocks, DataType.STOCK_LIST,
                                       {'board': board, 'count': len(stocks)})
        except Exception as e:
            return self._create_error_result(
                self._handle_api_error(e),
                DataType.STOCK_LIST,
            )
