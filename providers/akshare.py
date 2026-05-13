import time
import random
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from .base import (
    BaseProvider, ProviderCapability, ProviderResult, DataType,
    ProviderError, ErrorType,
)

try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False


class AkShareProvider(BaseProvider):
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)

    @property
    def name(self) -> str:
        return 'akshare'

    @property
    def display_name(self) -> str:
        return 'AkShare'

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
            ProviderCapability.FINANCIAL,
            ProviderCapability.STOCK_LIST,
        ]

    @property
    def priority(self) -> int:
        return 3

    @property
    def is_configured(self) -> bool:
        return AKSHARE_AVAILABLE

    def _handle_api_error(self, e: Exception) -> ProviderError:
        error_msg = str(e).lower()
        if 'timeout' in error_msg:
            return self._create_error(ErrorType.TIMEOUT, f"请求超时: {e}")
        elif 'connection' in error_msg:
            return self._create_error(ErrorType.CONNECTION_ERROR, f"连接错误: {e}")
        elif 'limit' in error_msg:
            return self._create_error(ErrorType.RATE_LIMITED, f"请求限流: {e}")
        else:
            return self._create_error(ErrorType.UNKNOWN, f"未知错误: {e}")

    def fetch_realtime(self, code: str) -> ProviderResult:
        if not AKSHARE_AVAILABLE:
            return self._create_error_result(
                self._create_error(ErrorType.AUTH_ERROR,
                                  "AkShare未安装，请执行: pip install akshare"),
                DataType.REALTIME,
            )

        try:
            df = ak.stock_zh_a_spot_em()
            row = df[df['代码'] == code]
            
            if row.empty:
                return self._create_error_result(
                    self._create_error(ErrorType.DATA_ERROR, f"未找到股票: {code}"),
                    DataType.REALTIME,
                )

            r = row.iloc[0]
            realtime_data = {
                'code': code,
                'name': r.get('名称'),
                'price': r.get('最新价'),
                'open': r.get('今开'),
                'high': r.get('最高'),
                'low': r.get('最低'),
                'pre_close': r.get('昨收'),
                'volume': r.get('成交量'),
                'amount': r.get('成交额'),
                'change_pct': r.get('涨跌幅'),
                'pe_ttm': r.get('市盈率-动态'),
                'pb': r.get('市净率'),
                'market_cap': r.get('总市值'),
                'circ_market_cap': r.get('流通市值'),
                'data_source': self.name,
            }

            missing = [k for k, v in realtime_data.items()
                      if k not in ['data_source'] and v is None]
            realtime_data['missing_fields'] = missing
            realtime_data['data_quality'] = 'full' if not missing else 'partial'

            return self._create_result(realtime_data, DataType.REALTIME)
        except Exception as e:
            return self._create_error_result(
                self._handle_api_error(e),
                DataType.REALTIME,
            )

    def fetch_daily_kline(self, code: str, days: int = 250,
                          start_date: Optional[str] = None,
                          end_date: Optional[str] = None) -> ProviderResult:
        if not AKSHARE_AVAILABLE:
            return self._create_error_result(
                self._create_error(ErrorType.AUTH_ERROR,
                                  "AkShare未安装"),
                DataType.DAILY_KLINE,
            )

        try:
            df = ak.stock_zh_a_hist(symbol=code, period="daily",
                                    adjust="qfq")
            
            if df is None or df.empty:
                return self._create_error_result(
                    self._create_error(ErrorType.DATA_ERROR, "未获取到K线数据"),
                    DataType.DAILY_KLINE,
                )

            if start_date:
                df = df[df['日期'] >= start_date]
            if end_date:
                df = df[df['日期'] <= end_date]

            df = df.tail(days)

            klines = []
            for _, row in df.iterrows():
                klines.append(
                    f"{row['日期']},{row['开盘']},{row['收盘']},"
                    f"{row['最高']},{row['最低']},{row['成交量']},{row['成交额']}"
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
        if not AKSHARE_AVAILABLE:
            return self._create_error_result(
                self._create_error(ErrorType.AUTH_ERROR,
                                  "AkShare未安装"),
                DataType.MINUTE_KLINE,
            )

        try:
            period_map = {1: '1', 5: '5', 15: '15', 30: '30', 60: '60'}
            period = period_map.get(klt, '5')
            
            df = ak.stock_zh_a_hist_min_em(symbol=code, period=period,
                                           adjust="qfq")
            
            if df is None or df.empty:
                return self._create_error_result(
                    self._create_error(ErrorType.DATA_ERROR, "未获取到分钟K线数据"),
                    DataType.MINUTE_KLINE,
                )

            klines = []
            for _, row in df.iterrows():
                klines.append(
                    f"{row['时间']},{row['开盘']},{row['收盘']},"
                    f"{row['最高']},{row['最低']},{row['成交量']},{row['成交额']}"
                )

            return self._create_result(klines, DataType.MINUTE_KLINE,
                                       {'count': len(klines), 'klt': klt})
        except Exception as e:
            return self._create_error_result(
                self._handle_api_error(e),
                DataType.MINUTE_KLINE,
            )

    def fetch_valuation(self, code: str) -> ProviderResult:
        return self.fetch_realtime(code)

    def fetch_fund_flow(self, code: str, days: int = 100) -> ProviderResult:
        if not AKSHARE_AVAILABLE:
            return self._create_error_result(
                self._create_error(ErrorType.AUTH_ERROR,
                                  "AkShare未安装"),
                DataType.FUND_FLOW,
            )

        try:
            df = ak.stock_individual_fund_flow(stock=code, market="sh" if code.startswith('6') else ("bj" if code.startswith(('4', '8')) else "sz"))
            
            if df is None or df.empty:
                return self._create_error_result(
                    self._create_error(ErrorType.DATA_ERROR, "未获取到资金流向数据"),
                    DataType.FUND_FLOW,
                )

            df = df.head(days)
            fund_flows = []
            for _, row in df.iterrows():
                fund_flows.append({
                    'date': row.get('日期') or row.get('date'),
                    'main_net_inflow': row.get('主力净流入-净额') or row.get('main_net_inflow'),
                    'main_net_inflow_pct': row.get('主力净流入-净占比') or row.get('main_net_inflow_pct'),
                })

            return self._create_result(fund_flows, DataType.FUND_FLOW,
                                       {'count': len(fund_flows)})
        except Exception as e:
            return self._create_error_result(
                self._handle_api_error(e),
                DataType.FUND_FLOW,
            )

    def fetch_stock_list(self, board: str = 'a_share') -> ProviderResult:
        if not AKSHARE_AVAILABLE:
            return self._create_error_result(
                self._create_error(ErrorType.AUTH_ERROR,
                                  "AkShare未安装"),
                DataType.STOCK_LIST,
            )

        try:
            df = ak.stock_zh_a_spot_em()
            
            if df is None or df.empty:
                return self._create_error_result(
                    self._create_error(ErrorType.DATA_ERROR, "未获取到股票列表"),
                    DataType.STOCK_LIST,
                )

            stocks = []
            for _, row in df.iterrows():
                code = str(row['代码'])
                
                if board == 'main' and not (code.startswith('60') or code.startswith('000') or code.startswith('001')):
                    continue
                elif board == 'gem' and not code.startswith('300'):
                    continue
                elif board == 'star' and not code.startswith('688'):
                    continue
                elif board == 'bse' and not (code.startswith('4') or code.startswith('8')):
                    continue
                elif board == 'sh_main' and not code.startswith('60'):
                    continue
                elif board == 'sz_main' and not (code.startswith('000') or code.startswith('001')):
                    continue

                stocks.append({
                    'code': code,
                    'name': row['名称'],
                    'market': 'SH' if code.startswith('6') else 'SZ',
                })

            return self._create_result(stocks, DataType.STOCK_LIST,
                                       {'board': board, 'count': len(stocks)})
        except Exception as e:
            return self._create_error_result(
                self._handle_api_error(e),
                DataType.STOCK_LIST,
            )

    def fetch_financial(self, code: str, report_type: str = 'income') -> ProviderResult:
        if not AKSHARE_AVAILABLE:
            return self._create_error_result(
                self._create_error(ErrorType.AUTH_ERROR,
                                  "AkShare未安装"),
                DataType.FINANCIAL,
            )

        try:
            if report_type == 'income':
                df = ak.stock_financial_analysis_indicator(symbol=code)
            else:
                df = ak.stock_financial_analysis_indicator(symbol=code)

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
