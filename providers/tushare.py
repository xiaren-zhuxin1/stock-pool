import time
import random
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from .base import (
    BaseProvider, ProviderCapability, ProviderResult, DataType,
    ProviderError, ErrorType,
)

try:
    import tushare as ts
    TUSHARE_AVAILABLE = True
except ImportError:
    TUSHARE_AVAILABLE = False


class TuShareProvider(BaseProvider):
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._token = (config or {}).get('token')
        self._pro = None
        if TUSHARE_AVAILABLE and self._token:
            try:
                ts.set_token(self._token)
                self._pro = ts.pro_api()
            except Exception:
                pass

    @property
    def name(self) -> str:
        return 'tushare'

    @property
    def display_name(self) -> str:
        return 'TuShare Pro'

    @property
    def is_free(self) -> bool:
        return False

    @property
    def capabilities(self) -> List[ProviderCapability]:
        return [
            ProviderCapability.DAILY_KLINE,
            ProviderCapability.MINUTE_KLINE,
            ProviderCapability.VALUATION,
            ProviderCapability.FINANCIAL,
            ProviderCapability.STOCK_LIST,
        ]

    @property
    def priority(self) -> int:
        return 10

    @property
    def requires_auth(self) -> bool:
        return True

    @property
    def is_configured(self) -> bool:
        return TUSHARE_AVAILABLE and self._token is not None and self._pro is not None

    def _get_ts_code(self, code: str) -> str:
        suffix = 'SH' if code.startswith('6') else 'SZ'
        return f"{code}.{suffix}"

    def _handle_api_error(self, e: Exception) -> ProviderError:
        error_msg = str(e).lower()
        if 'timeout' in error_msg:
            return self._create_error(ErrorType.TIMEOUT, f"请求超时: {e}")
        elif 'connection' in error_msg:
            return self._create_error(ErrorType.CONNECTION_ERROR, f"连接错误: {e}")
        elif 'limit' in error_msg or 'quota' in error_msg:
            return self._create_error(ErrorType.QUOTA_EXCEEDED, f"额度不足: {e}")
        elif 'auth' in error_msg or 'token' in error_msg:
            return self._create_error(ErrorType.AUTH_ERROR, f"认证失败: {e}")
        else:
            return self._create_error(ErrorType.UNKNOWN, f"未知错误: {e}")

    def fetch_realtime(self, code: str) -> ProviderResult:
        return self._create_error_result(
            self._create_error(ErrorType.INVALID_PARAMS,
                              "TuShare不支持实时行情，请使用东方财富或新浪"),
            DataType.REALTIME,
        )

    def fetch_daily_kline(self, code: str, days: int = 250,
                          start_date: Optional[str] = None,
                          end_date: Optional[str] = None) -> ProviderResult:
        if not self.is_configured:
            return self._create_error_result(
                self._create_error(ErrorType.AUTH_ERROR,
                                  "TuShare未配置Token，请设置TUSHARE_TOKEN环境变量"),
                DataType.DAILY_KLINE,
            )

        ts_code = self._get_ts_code(code)
        
        if not end_date:
            end_date = datetime.now().strftime('%Y%m%d')
        if not start_date:
            start_date = (datetime.now() - timedelta(days=days * 2)).strftime('%Y%m%d')

        try:
            df = self._pro.daily(ts_code=ts_code, start_date=start_date,
                                end_date=end_date)
            
            if df is None or df.empty:
                return self._create_error_result(
                    self._create_error(ErrorType.DATA_ERROR, "未获取到K线数据"),
                    DataType.DAILY_KLINE,
                )

            df = df.sort_values('trade_date')
            klines = []
            for _, row in df.iterrows():
                klines.append(
                    f"{row['trade_date']},{row['open']},{row['close']},"
                    f"{row['high']},{row['low']},{row['vol']},{row['amount']}"
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
        if not self.is_configured:
            return self._create_error_result(
                self._create_error(ErrorType.AUTH_ERROR,
                                  "TuShare未配置Token"),
                DataType.MINUTE_KLINE,
            )

        ts_code = self._get_ts_code(code)
        end_date = datetime.now().strftime('%Y%m%d %H:%M')
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d %H:%M')

        try:
            df = ts.pro_bar(ts_code=ts_code, freq=f'{klt}min',
                           start_date=start_date, end_date=end_date)
            
            if df is None or df.empty:
                return self._create_error_result(
                    self._create_error(ErrorType.DATA_ERROR, "未获取到分钟K线数据"),
                    DataType.MINUTE_KLINE,
                )

            df = df.sort_values('trade_time')
            klines = []
            for _, row in df.iterrows():
                klines.append(
                    f"{row['trade_time']},{row['open']},{row['close']},"
                    f"{row['high']},{row['low']},{row['vol']},{row['amount']}"
                )

            return self._create_result(klines, DataType.MINUTE_KLINE,
                                       {'count': len(klines), 'klt': klt})
        except Exception as e:
            return self._create_error_result(
                self._handle_api_error(e),
                DataType.MINUTE_KLINE,
            )

    def fetch_valuation(self, code: str) -> ProviderResult:
        if not self.is_configured:
            return self._create_error_result(
                self._create_error(ErrorType.AUTH_ERROR,
                                  "TuShare未配置Token"),
                DataType.VALUATION,
            )

        ts_code = self._get_ts_code(code)
        trade_date = datetime.now().strftime('%Y%m%d')

        try:
            df = self._pro.daily_basic(ts_code=ts_code, trade_date=trade_date,
                                       fields='pe_ttm,pb,ps_ttm,total_mv,circ_mv')
            
            if df is None or df.empty:
                return self._create_error_result(
                    self._create_error(ErrorType.DATA_ERROR, "未获取到估值数据"),
                    DataType.VALUATION,
                )

            row = df.iloc[0]
            valuation_data = {
                'code': code,
                'pe_ttm': row.get('pe_ttm'),
                'pb': row.get('pb'),
                'ps_ttm': row.get('ps_ttm'),
                'market_cap': row.get('total_mv'),
                'circ_market_cap': row.get('circ_mv'),
                'data_source': self.name,
            }

            return self._create_result(valuation_data, DataType.VALUATION)
        except Exception as e:
            return self._create_error_result(
                self._handle_api_error(e),
                DataType.VALUATION,
            )

    def fetch_fund_flow(self, code: str, days: int = 100) -> ProviderResult:
        return self._create_error_result(
            self._create_error(ErrorType.INVALID_PARAMS,
                              "TuShare基础版不支持资金流向数据"),
            DataType.FUND_FLOW,
        )

    def fetch_stock_list(self, board: str = 'a_share') -> ProviderResult:
        if not self.is_configured:
            return self._create_error_result(
                self._create_error(ErrorType.AUTH_ERROR,
                                  "TuShare未配置Token"),
                DataType.STOCK_LIST,
            )

        try:
            df = self._pro.stock_basic(exchange='', list_status='L',
                                       fields='ts_code,symbol,name,area,industry,market,list_date')
            
            if df is None or df.empty:
                return self._create_error_result(
                    self._create_error(ErrorType.DATA_ERROR, "未获取到股票列表"),
                    DataType.STOCK_LIST,
                )

            stocks = []
            for _, row in df.iterrows():
                ts_code = row['ts_code']
                code = ts_code.split('.')[0]
                market = ts_code.split('.')[1]
                
                if board == 'main' and market not in ('SH', 'SZ'):
                    continue
                elif board == 'sh_main' and market != 'SH':
                    continue
                elif board == 'sz_main' and market != 'SZ':
                    continue
                elif board == 'gem' and not code.startswith('300'):
                    continue
                elif board == 'star' and not code.startswith('688'):
                    continue

                stocks.append({
                    'code': code,
                    'name': row['name'],
                    'market': market,
                    'industry': row.get('industry'),
                })

            return self._create_result(stocks, DataType.STOCK_LIST,
                                       {'board': board, 'count': len(stocks)})
        except Exception as e:
            return self._create_error_result(
                self._handle_api_error(e),
                DataType.STOCK_LIST,
            )

    def fetch_financial(self, code: str, report_type: str = 'income') -> ProviderResult:
        if not self.is_configured:
            return self._create_error_result(
                self._create_error(ErrorType.AUTH_ERROR,
                                  "TuShare未配置Token"),
                DataType.FINANCIAL,
            )

        ts_code = self._get_ts_code(code)

        try:
            if report_type == 'income':
                df = self._pro.income(ts_code=ts_code, fields='ann_date,f_ann_date,end_date,revenue,n_income')
            elif report_type == 'balance':
                df = self._pro.balancesheet(ts_code=ts_code)
            elif report_type == 'cashflow':
                df = self._pro.cashflow(ts_code=ts_code)
            else:
                df = self._pro.income(ts_code=ts_code)

            if df is None or df.empty:
                return self._create_error_result(
                    self._create_error(ErrorType.DATA_ERROR, "未获取到财务数据"),
                    DataType.FINANCIAL,
                )

            records = df.to_dict('records')
            return self._create_result(records, DataType.FINANCIAL,
                                       {'report_type': report_type})
        except Exception as e:
            return self._create_error_result(
                self._handle_api_error(e),
                DataType.FINANCIAL,
            )
