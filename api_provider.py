import requests
import time
import random
from datetime import datetime
import sys
import builtins
from typing import Optional, List, Dict, Any, Tuple
from enum import Enum


HARDCODED_MAIN_BOARD_STOCKS = [
    {'code': '600000', 'name': '浦发银行', 'market': 'SH'},
    {'code': '600004', 'name': '白云机场', 'market': 'SH'},
    {'code': '600006', 'name': '东风汽车', 'market': 'SH'},
    {'code': '600007', 'name': '中国国贸', 'market': 'SH'},
    {'code': '600008', 'name': '首创环保', 'market': 'SH'},
    {'code': '600009', 'name': '上海机场', 'market': 'SH'},
    {'code': '600010', 'name': '包钢股份', 'market': 'SH'},
    {'code': '600011', 'name': '华能国际', 'market': 'SH'},
    {'code': '600012', 'name': '皖通高速', 'market': 'SH'},
    {'code': '600015', 'name': '华夏银行', 'market': 'SH'},
    {'code': '600016', 'name': '民生银行', 'market': 'SH'},
    {'code': '600017', 'name': '日照港', 'market': 'SH'},
    {'code': '600018', 'name': '上港集团', 'market': 'SH'},
    {'code': '600019', 'name': '宝钢股份', 'market': 'SH'},
    {'code': '600020', 'name': '中原高速', 'market': 'SH'},
    {'code': '600021', 'name': '上海电力', 'market': 'SH'},
    {'code': '600022', 'name': '山东钢铁', 'market': 'SH'},
    {'code': '600023', 'name': '浙能电力', 'market': 'SH'},
    {'code': '600025', 'name': '华能水电', 'market': 'SH'},
    {'code': '600026', 'name': '中远海能', 'market': 'SH'},
    {'code': '600027', 'name': '华电国际', 'market': 'SH'},
    {'code': '600028', 'name': '中国石化', 'market': 'SH'},
    {'code': '600029', 'name': '南方航空', 'market': 'SH'},
    {'code': '600030', 'name': '中信证券', 'market': 'SH'},
    {'code': '600031', 'name': '三一重工', 'market': 'SH'},
    {'code': '600033', 'name': '福建高速', 'market': 'SH'},
    {'code': '600035', 'name': '楚天高速', 'market': 'SH'},
    {'code': '600036', 'name': '招商银行', 'market': 'SH'},
    {'code': '600037', 'name': '歌华有线', 'market': 'SH'},
    {'code': '600038', 'name': '中直股份', 'market': 'SH'},
    {'code': '600039', 'name': '四川路桥', 'market': 'SH'},
    {'code': '600048', 'name': '保利发展', 'market': 'SH'},
    {'code': '600050', 'name': '中国联通', 'market': 'SH'},
    {'code': '600104', 'name': '上汽集团', 'market': 'SH'},
    {'code': '600109', 'name': '国金证券', 'market': 'SH'},
    {'code': '600111', 'name': '北方稀土', 'market': 'SH'},
    {'code': '600115', 'name': '中国东航', 'market': 'SH'},
    {'code': '600118', 'name': '中国卫星', 'market': 'SH'},
    {'code': '600150', 'name': '中国船舶', 'market': 'SH'},
    {'code': '600183', 'name': '生益科技', 'market': 'SH'},
    {'code': '600196', 'name': '复星医药', 'market': 'SH'},
    {'code': '600276', 'name': '恒瑞医药', 'market': 'SH'},
    {'code': '600309', 'name': '万华化学', 'market': 'SH'},
    {'code': '600332', 'name': '白云山', 'market': 'SH'},
    {'code': '600346', 'name': '恒力石化', 'market': 'SH'},
    {'code': '600352', 'name': '浙江龙盛', 'market': 'SH'},
    {'code': '600438', 'name': '通威股份', 'market': 'SH'},
    {'code': '600486', 'name': '扬农化工', 'market': 'SH'},
    {'code': '600489', 'name': '中金黄金', 'market': 'SH'},
    {'code': '600498', 'name': '烽火通信', 'market': 'SH'},
    {'code': '600519', 'name': '贵州茅台', 'market': 'SH'},
    {'code': '600547', 'name': '山东黄金', 'market': 'SH'},
    {'code': '600570', 'name': '恒生电子', 'market': 'SH'},
    {'code': '600585', 'name': '海螺水泥', 'market': 'SH'},
    {'code': '600588', 'name': '用友网络', 'market': 'SH'},
    {'code': '600690', 'name': '海尔智家', 'market': 'SH'},
    {'code': '600703', 'name': '三安光电', 'market': 'SH'},
    {'code': '600809', 'name': '山西汾酒', 'market': 'SH'},
    {'code': '600837', 'name': '海通证券', 'market': 'SH'},
    {'code': '600845', 'name': '宝信软件', 'market': 'SH'},
    {'code': '600848', 'name': '上海临港', 'market': 'SH'},
    {'code': '600887', 'name': '伊利股份', 'market': 'SH'},
    {'code': '600893', 'name': '航发动力', 'market': 'SH'},
    {'code': '600900', 'name': '长江电力', 'market': 'SH'},
    {'code': '600918', 'name': '中泰证券', 'market': 'SH'},
    {'code': '600919', 'name': '江苏银行', 'market': 'SH'},
    {'code': '600926', 'name': '杭州银行', 'market': 'SH'},
    {'code': '600941', 'name': '中国移动', 'market': 'SH'},
    {'code': '600958', 'name': '东方证券', 'market': 'SH'},
    {'code': '600989', 'name': '宝丰能源', 'market': 'SH'},
    {'code': '601012', 'name': '隆基绿能', 'market': 'SH'},
    {'code': '601066', 'name': '中信建投', 'market': 'SH'},
    {'code': '601088', 'name': '中国神华', 'market': 'SH'},
    {'code': '601111', 'name': '中国国航', 'market': 'SH'},
    {'code': '601138', 'name': '工业富联', 'market': 'SH'},
    {'code': '601166', 'name': '兴业银行', 'market': 'SH'},
    {'code': '601225', 'name': '陕西煤业', 'market': 'SH'},
    {'code': '601236', 'name': '红塔证券', 'market': 'SH'},
    {'code': '601238', 'name': '广汽集团', 'market': 'SH'},
    {'code': '601288', 'name': '农业银行', 'market': 'SH'},
    {'code': '601318', 'name': '中国平安', 'market': 'SH'},
    {'code': '601319', 'name': '中国人保', 'market': 'SH'},
    {'code': '601328', 'name': '交通银行', 'market': 'SH'},
    {'code': '601336', 'name': '新华保险', 'market': 'SH'},
    {'code': '601390', 'name': '中国中铁', 'market': 'SH'},
    {'code': '601398', 'name': '工商银行', 'market': 'SH'},
    {'code': '601601', 'name': '中国太保', 'market': 'SH'},
    {'code': '601618', 'name': '中国中冶', 'market': 'SH'},
    {'code': '601628', 'name': '中国人寿', 'market': 'SH'},
    {'code': '601633', 'name': '长城汽车', 'market': 'SH'},
    {'code': '601668', 'name': '中国建筑', 'market': 'SH'},
    {'code': '601669', 'name': '中国电建', 'market': 'SH'},
    {'code': '601688', 'name': '华泰证券', 'market': 'SH'},
    {'code': '601728', 'name': '中国电信', 'market': 'SH'},
    {'code': '601766', 'name': '中国中车', 'market': 'SH'},
    {'code': '601788', 'name': '光大证券', 'market': 'SH'},
    {'code': '601800', 'name': '中国交建', 'market': 'SH'},
    {'code': '601818', 'name': '光大银行', 'market': 'SH'},
    {'code': '601857', 'name': '中国石油', 'market': 'SH'},
    {'code': '601877', 'name': '正泰电器', 'market': 'SH'},
    {'code': '601878', 'name': '浙商证券', 'market': 'SH'},
    {'code': '601881', 'name': '中国银河', 'market': 'SH'},
    {'code': '601888', 'name': '中国中免', 'market': 'SH'},
    {'code': '601899', 'name': '紫金矿业', 'market': 'SH'},
    {'code': '601901', 'name': '方正证券', 'market': 'SH'},
    {'code': '601919', 'name': '中远海控', 'market': 'SH'},
    {'code': '601933', 'name': '永辉超市', 'market': 'SH'},
    {'code': '601939', 'name': '建设银行', 'market': 'SH'},
    {'code': '601985', 'name': '中国核电', 'market': 'SH'},
    {'code': '601988', 'name': '中国银行', 'market': 'SH'},
    {'code': '601989', 'name': '中国重工', 'market': 'SH'},
    {'code': '601995', 'name': '中金公司', 'market': 'SH'},
    {'code': '601998', 'name': '中信银行', 'market': 'SH'},
    {'code': '000001', 'name': '平安银行', 'market': 'SZ'},
    {'code': '000002', 'name': '万科A', 'market': 'SZ'},
    {'code': '000063', 'name': '中兴通讯', 'market': 'SZ'},
    {'code': '000069', 'name': '华侨城A', 'market': 'SZ'},
    {'code': '000100', 'name': 'TCL科技', 'market': 'SZ'},
    {'code': '000157', 'name': '中联重科', 'market': 'SZ'},
    {'code': '000333', 'name': '美的集团', 'market': 'SZ'},
    {'code': '000338', 'name': '潍柴动力', 'market': 'SZ'},
    {'code': '000425', 'name': '徐工机械', 'market': 'SZ'},
    {'code': '000568', 'name': '泸州老窖', 'market': 'SZ'},
    {'code': '000596', 'name': '古井贡酒', 'market': 'SZ'},
    {'code': '000625', 'name': '长安汽车', 'market': 'SZ'},
    {'code': '000651', 'name': '格力电器', 'market': 'SZ'},
    {'code': '000656', 'name': '金科股份', 'market': 'SZ'},
    {'code': '000661', 'name': '长春高新', 'market': 'SZ'},
    {'code': '000703', 'name': '建发股份', 'market': 'SZ'},
    {'code': '000708', 'name': '中信特钢', 'market': 'SZ'},
    {'code': '000725', 'name': '京东方A', 'market': 'SZ'},
    {'code': '000768', 'name': '中航西飞', 'market': 'SZ'},
    {'code': '000776', 'name': '广发证券', 'market': 'SZ'},
    {'code': '000783', 'name': '长江证券', 'market': 'SZ'},
    {'code': '000786', 'name': '北新建材', 'market': 'SZ'},
    {'code': '000858', 'name': '五粮液', 'market': 'SZ'},
    {'code': '000876', 'name': '新希望', 'market': 'SZ'},
    {'code': '000895', 'name': '双汇发展', 'market': 'SZ'},
    {'code': '000938', 'name': '紫光股份', 'market': 'SZ'},
    {'code': '000963', 'name': '华东医药', 'market': 'SZ'},
    {'code': '001979', 'name': '招商蛇口', 'market': 'SZ'},
    {'code': '002001', 'name': '新和成', 'market': 'SZ'},
    {'code': '002007', 'name': '华兰生物', 'market': 'SZ'},
    {'code': '002008', 'name': '大族激光', 'market': 'SZ'},
    {'code': '002024', 'name': '苏宁易购', 'market': 'SZ'},
    {'code': '002027', 'name': '分众传媒', 'market': 'SZ'},
    {'code': '002049', 'name': '紫光国微', 'market': 'SZ'},
    {'code': '002050', 'name': '三花智控', 'market': 'SZ'},
    {'code': '002129', 'name': '中环股份', 'market': 'SZ'},
    {'code': '002142', 'name': '宁波银行', 'market': 'SZ'},
    {'code': '002230', 'name': '科大讯飞', 'market': 'SZ'},
    {'code': '002236', 'name': '大华股份', 'market': 'SZ'},
    {'code': '002241', 'name': '歌尔股份', 'market': 'SZ'},
    {'code': '002304', 'name': '洋河股份', 'market': 'SZ'},
    {'code': '002311', 'name': '海大集团', 'market': 'SZ'},
    {'code': '002352', 'name': '顺丰控股', 'market': 'SZ'},
    {'code': '002384', 'name': '东山精密', 'market': 'SZ'},
    {'code': '002410', 'name': '广联达', 'market': 'SZ'},
    {'code': '002415', 'name': '海康威视', 'market': 'SZ'},
    {'code': '002460', 'name': '赣锋锂业', 'market': 'SZ'},
    {'code': '002475', 'name': '立讯精密', 'market': 'SZ'},
    {'code': '002493', 'name': '荣盛石化', 'market': 'SZ'},
    {'code': '002594', 'name': '比亚迪', 'market': 'SZ'},
    {'code': '002601', 'name': '龙蟒佰利', 'market': 'SZ'},
    {'code': '002607', 'name': '中公教育', 'market': 'SZ'},
    {'code': '002648', 'name': '卫星石化', 'market': 'SZ'},
    {'code': '002690', 'name': '美年健康', 'market': 'SZ'},
    {'code': '002714', 'name': '牧原股份', 'market': 'SZ'},
    {'code': '002812', 'name': '恩捷股份', 'market': 'SZ'},
    {'code': '002841', 'name': '视源股份', 'market': 'SZ'},
]


class APIErrorType(Enum):
    TIMEOUT = "timeout"
    CONNECTION_ERROR = "connection_error"
    RATE_LIMITED = "rate_limited"
    HTTP_ERROR = "http_error"
    DATA_ERROR = "data_error"
    UNKNOWN = "unknown"


class APIError(Exception):
    def __init__(self, error_type: APIErrorType, message: str, api_name: Optional[str] = None):
        self.error_type = error_type
        self.api_name = api_name
        super().__init__(message)


def print(*args, **kwargs):
    """API 层日志统一输出到 stderr，避免 MCP stdout JSON-RPC 通道被污染。"""
    kwargs.setdefault('file', sys.stderr)
    return builtins.print(*args, **kwargs)

class StockAPIProvider:
    
    def __init__(self) -> None:
        self.timeout: int = 15
        self.max_retries: int = 3
        self.retry_delay: int = 1
        
        self.api_status: Dict[str, Dict[str, Any]] = {
            'eastmoney': {'available': True, 'last_error': None, 'error_count': 0},
            'sina': {'available': True, 'last_error': None, 'error_count': 0},
            'tencent': {'available': True, 'last_error': None, 'error_count': 0},
            'netease': {'available': True, 'last_error': None, 'error_count': 0},
        }
        
        self.api_priority: List[str] = ['eastmoney', 'sina', 'tencent', 'netease']
    
    def _get_headers(self, referer: Optional[str] = None) -> Dict[str, str]:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            # requests may not have brotli support in the MCP runtime; asking
            # Eastmoney for br can leave response.json() with compressed bytes.
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
        }
        if referer:
            headers['Referer'] = referer
            headers['Origin'] = referer.rstrip('/') if referer else None
        return headers
    
    def _request_with_retry(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
    ) -> Optional[requests.Response]:
        timeout = timeout or self.timeout
        
        for attempt in range(self.max_retries):
            try:
                if attempt > 0:
                    delay = self.retry_delay * (2 ** attempt) + random.uniform(0, 1)
                    time.sleep(delay)
                
                response = requests.get(url, params=params, headers=headers, timeout=timeout)
                if response.status_code == 200:
                    return response
                elif response.status_code == 429:
                    wait_time = 60 + random.uniform(0, 10)
                    print(f"  限流，等待 {wait_time:.1f} 秒...")
                    time.sleep(wait_time)
                    raise APIError(APIErrorType.RATE_LIMITED, f"API限流，已等待{wait_time:.1f}秒")
                else:
                    raise APIError(APIErrorType.HTTP_ERROR, f"HTTP错误: {response.status_code}")
            except requests.exceptions.Timeout:
                if attempt < self.max_retries - 1:
                    print(f"  超时，重试 {attempt + 2}/{self.max_retries}...")
                    continue
                raise APIError(APIErrorType.TIMEOUT, "请求超时")
            except requests.exceptions.ConnectionError:
                if attempt < self.max_retries - 1:
                    print(f"  连接错误，重试 {attempt + 2}/{self.max_retries}...")
                    continue
                raise APIError(APIErrorType.CONNECTION_ERROR, "连接错误")
            except APIError:
                raise
            except Exception as e:
                raise APIError(APIErrorType.UNKNOWN, f"未知错误: {str(e)}")
        
        return None
    
    def _mark_api_error(self, api_name: str, error: Any) -> None:
        self.api_status[api_name]['error_count'] += 1
        self.api_status[api_name]['last_error'] = str(error)
        
        if self.api_status[api_name]['error_count'] >= 3:
            self.api_status[api_name]['available'] = False
            print(f"  [API降级] {api_name} 暂时不可用: {error}")
    
    def _mark_api_success(self, api_name: str) -> None:
        self.api_status[api_name]['error_count'] = 0
        self.api_status[api_name]['available'] = True
    
    def get_available_api(self) -> str:
        for api_name in self.api_priority:
            if self.api_status[api_name]['available']:
                return api_name
        for api_name in self.api_priority:
            self.api_status[api_name]['available'] = True
            self.api_status[api_name]['error_count'] = 0
        return self.api_priority[0]
    
    def _normalize_realtime_data(self, result: Dict[str, Any], data_source: str, allow_partial_full: bool = False) -> Dict[str, Any]:
        result['data_source'] = data_source

        missing_fields = [
            k for k, v in result.items()
            if k not in ['data_source', 'data_quality', 'missing_fields'] and v is None
        ]
        result['missing_fields'] = missing_fields
        result['data_quality'] = 'full' if not missing_fields or (allow_partial_full and len(missing_fields) < 3) else 'partial'
        return result

    def fetch_kline_eastmoney(self, code, days=250):
        try:
            market = '1' if code.startswith('6') else '0'
            url = "http://push2his.eastmoney.com/api/qt/stock/kline/get"
            params = {
                'secid': f"{market}.{code}",
                'fields1': 'f1,f2,f3,f4,f5,f6',
                'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62',
                'klt': '101',
                'fqt': '1',
                'end': '20500101',
                'lmt': str(days)
            }
            
            response = self._request_with_retry(
                url, 
                params=params, 
                headers=self._get_headers('http://quote.eastmoney.com/')
            )
            
            if response:
                data = response.json()
                if data and 'data' in data and data['data'] and 'klines' in data['data']:
                    self._mark_api_success('eastmoney')
                    return data['data']['klines']
        except Exception as e:
            self._mark_api_error('eastmoney', e)
        return None
    
    def fetch_kline_sina(self, code, days=250):
        try:
            market = 'sh' if code.startswith('6') else 'sz'
            url = f"https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData"
            params = {
                'symbol': f"{market}{code}",
                'scale': '240',
                'ma': 'no',
                'datalen': str(days)
            }
            
            response = self._request_with_retry(
                url,
                params=params,
                headers=self._get_headers('https://finance.sina.com.cn/')
            )
            
            if response:
                data = response.json()
                if data and isinstance(data, list):
                    result = []
                    for item in data:
                        if isinstance(item, dict):
                            result.append(f"{item.get('day')},{item.get('open')},{item.get('close')},{item.get('high')},{item.get('low')},{item.get('volume')},{item.get('amount', 0)}")
                    self._mark_api_success('sina')
                    return result
        except Exception as e:
            self._mark_api_error('sina', e)
        return None
    
    def fetch_kline_tencent(self, code, days=250):
        try:
            market = 'sh' if code.startswith('6') else 'sz'
            url = "https://web.sqt.gtimg.cn/q=r_" + f"{market}{code}"
            
            response = self._request_with_retry(
                url,
                headers=self._get_headers('https://gu.qq.com/')
            )
            
            if response:
                text = response.text
                if text and '~' in text:
                    parts = text.split('~')
                    if len(parts) > 30:
                        self._mark_api_success('tencent')
                        return None
        except Exception as e:
            self._mark_api_error('tencent', e)
        return None
    
    def fetch_kline_netease(self, code, days=250):
        try:
            market = '0' if code.startswith('6') else '1'
            url = f"http://api.money.126.net/data/feed/{market}{code}"
            
            response = self._request_with_retry(
                url,
                headers=self._get_headers('https://money.163.com/')
            )
            
            if response:
                self._mark_api_success('netease')
                return None
        except Exception as e:
            self._mark_api_error('netease', e)
        return None
    
    def fetch_kline(self, code, days=250):
        api_order = ['eastmoney', 'sina']
        
        for api_name in api_order:
            if not self.api_status[api_name]['available']:
                continue
            
            try:
                if api_name == 'eastmoney':
                    result = self.fetch_kline_eastmoney(code, days)
                elif api_name == 'sina':
                    result = self.fetch_kline_sina(code, days)
                else:
                    continue
                
                if result:
                    return result, api_name
            except Exception as e:
                print(f"  [{api_name}] 失败: {e}")
                continue
        
        return None, None

    def fetch_stock_universe_eastmoney(self, board='main', limit=None, page_size=100, page=None):
        """从东方财富列表接口获取候选股票池，不使用本地缓存数据库。"""
        board_fs = {
            'a_share': 'm:1+t:2,m:1+t:23,m:0+t:6,m:0+t:80,m:0+t:81+s:2048',
            'all_a': 'm:1+t:2,m:1+t:23,m:0+t:6,m:0+t:80,m:0+t:81+s:2048',
            'all': 'm:1+t:2,m:1+t:23,m:0+t:6,m:0+t:80,m:0+t:81+s:2048',
            '全A': 'm:1+t:2,m:1+t:23,m:0+t:6,m:0+t:80,m:0+t:81+s:2048',
            '全A股': 'm:1+t:2,m:1+t:23,m:0+t:6,m:0+t:80,m:0+t:81+s:2048',
            '全市场': 'm:1+t:2,m:1+t:23,m:0+t:6,m:0+t:80,m:0+t:81+s:2048',
            'hs_a': 'm:1+t:2,m:1+t:23,m:0+t:6,m:0+t:80',
            '沪深A股': 'm:1+t:2,m:1+t:23,m:0+t:6,m:0+t:80',
            'main': 'm:1+t:2,m:0+t:6',
            'main_board': 'm:1+t:2,m:0+t:6',
            '主板': 'm:1+t:2,m:0+t:6',
            'sh_main': 'm:1+t:2',
            '沪主板': 'm:1+t:2',
            'sz_main': 'm:0+t:6',
            '深主板': 'm:0+t:6',
            'gem': 'm:0+t:80',
            'chinext': 'm:0+t:80',
            '创业板': 'm:0+t:80',
            'star': 'm:1+t:23',
            'star_market': 'm:1+t:23',
            '科创板': 'm:1+t:23',
            'bse': 'm:0+t:81+s:2048',
            '北交所': 'm:0+t:81+s:2048',
        }
        fs = board_fs.get(board)
        if not fs:
            raise ValueError(f"不支持的股票池: {board}")

        try:
            page_size = max(1, min(int(page_size), 100))
        except (TypeError, ValueError):
            page_size = 100

        if page is not None:
            try:
                page = max(1, int(page))
            except (TypeError, ValueError):
                page = 1

        if limit is not None:
            try:
                limit = max(0, int(limit))
            except (TypeError, ValueError):
                limit = None
            if limit == 0:
                return {
                    'board': board,
                    'source': 'eastmoney',
                    'total': None,
                    'returned': 0,
                    'page': page,
                    'page_size': page_size,
                    'has_more': False,
                    'stocks': [],
                    'codes': [],
                }

        url = "http://80.push2.eastmoney.com/api/qt/clist/get"
        results = []
        total = None
        current_page = page or 1

        try:
            while True:
                params = {
                    'pn': str(current_page),
                    'pz': str(page_size),
                    'po': '1',
                    'np': '1',
                    'fltt': '2',
                    'invt': '2',
                    'fid': 'f3',
                    'fs': fs,
                    'fields': 'f12,f13,f14,f20,f21,f100',
                }
                headers = self._get_headers('http://quote.eastmoney.com/')
                headers['Accept-Encoding'] = 'gzip, deflate'
                response = self._request_with_retry(
                    url,
                    params=params,
                    headers=headers,
                    timeout=20
                )
                if not response:
                    break

                data = response.json()
                payload = data.get('data') if isinstance(data, dict) else None
                if not payload:
                    break

                total = payload.get('total', total)
                rows = payload.get('diff') or []
                if not rows:
                    break

                for row in rows:
                    code = row.get('f12')
                    if not code:
                        continue
                    market_id = row.get('f13')
                    if code.startswith(('4', '8', '9')):
                        market = 'BJ'
                    elif market_id == 1:
                        market = 'SH'
                    elif market_id == 0:
                        market = 'SZ'
                    else:
                        market = str(market_id)
                    results.append({
                        'code': code,
                        'name': row.get('f14') or '',
                        'market': market,
                        'board': board,
                        'industry': row.get('f100') or '',
                        'market_cap': row.get('f20'),
                        'circ_market_cap': row.get('f21'),
                    })
                    if limit is not None and len(results) >= limit:
                        self._mark_api_success('eastmoney')
                        return {
                            'board': board,
                            'source': 'eastmoney',
                            'total': total,
                            'returned': len(results),
                            'page': page,
                            'page_size': page_size,
                            'has_more': total is not None and current_page * page_size < total,
                            'stocks': results,
                            'codes': [item['code'] for item in results],
                        }

                if total is not None and current_page * page_size >= total:
                    break
                if page is not None:
                    break
                current_page += 1
                time.sleep(random.uniform(0.05, 0.15))

            self._mark_api_success('eastmoney')
            return {
                'board': board,
                'source': 'eastmoney',
                'total': total,
                'returned': len(results),
                'page': page,
                'page_size': page_size,
                'has_more': total is not None and current_page * page_size < total,
                'stocks': results,
                'codes': [item['code'] for item in results],
            }
        except Exception as e:
            self._mark_api_error('eastmoney', e)
            return {
                'board': board,
                'source': 'eastmoney',
                'total': total,
                'returned': len(results),
                'page': page,
                'page_size': page_size,
                'has_more': total is not None and current_page * page_size < total,
                'stocks': results,
                'codes': [item['code'] for item in results],
                'error': str(e),
            }

    def fetch_stock_universe(self, board='main', limit=None, page_size=100, page=None):
        """获取股票列表，支持多API自动降级
        
        降级顺序：
        1. 东方财富API（主要）
        2. 新浪财经API（备用1）
        3. 腾讯财经API（备用2）
        4. 硬编码备用列表（最后备用）
        """
        errors = []
        
        # 尝试东方财富API
        print(f"  [尝试1] 东方财富API...")
        result = self.fetch_stock_universe_eastmoney(board, limit=limit, page_size=page_size, page=page)
        if not result.get('error'):
            return result
        errors.append(f"东方财富: {result.get('error')}")
        
        # 尝试新浪财经API
        print(f"  [尝试2] 新浪财经API...")
        result = self._fetch_stock_universe_sina(board, limit=limit)
        if not result.get('error'):
            return result
        errors.append(f"新浪: {result.get('error')}")
        
        # 尝试腾讯财经API
        print(f"  [尝试3] 腾讯财经API...")
        result = self._fetch_stock_universe_tencent(board, limit=limit)
        if not result.get('error'):
            return result
        errors.append(f"腾讯: {result.get('error')}")
        
        # 使用硬编码备用列表
        if board in ['main', 'main_board', '主板']:
            print(f"  [备用] 使用硬编码备用列表...")
            stocks = HARDCODED_MAIN_BOARD_STOCKS.copy()
            
            if limit is not None and limit > 0:
                stocks = stocks[:limit]
            
            return {
                'board': board,
                'source': 'hardcoded',
                'total': len(HARDCODED_MAIN_BOARD_STOCKS),
                'returned': len(stocks),
                'page': page,
                'page_size': page_size,
                'has_more': len(stocks) < len(HARDCODED_MAIN_BOARD_STOCKS),
                'stocks': stocks,
                'codes': [item['code'] for item in stocks],
                'warning': f'所有API连接失败，使用硬编码备用列表。失败原因: {"; ".join(errors)}'
            }
        
        return {
            'board': board,
            'source': 'none',
            'total': 0,
            'returned': 0,
            'page': page,
            'page_size': page_size,
            'has_more': False,
            'stocks': [],
            'codes': [],
            'error': f'所有API连接失败: {"; ".join(errors)}'
        }
    
    def _fetch_stock_universe_sina(self, board='main', limit=None):
        """从新浪财经获取股票列表（备用API）"""
        try:
            url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
            params = {
                'page': 1,
                'num': limit or 1000,
                'sort': 'symbol',
                'asc': 1,
                'node': 'hs_a' if board in ['a_share', 'hs_a'] else 'sh_a' if board in ['main', 'sh_main'] else 'sz_a'
            }
            
            response = self._request_with_retry(url, params=params, timeout=15)
            if not response:
                return {'board': board, 'source': 'sina', 'total': 0, 'returned': 0, 'stocks': [], 'codes': [], 'error': '连接失败'}
            
            data = response.json()
            if not data or not isinstance(data, list):
                return {'board': board, 'source': 'sina', 'total': 0, 'returned': 0, 'stocks': [], 'codes': [], 'error': '数据格式错误'}
            
            stocks = []
            for item in data[:limit] if limit else data:
                code = item.get('code')
                if not code:
                    continue
                stocks.append({
                    'code': code,
                    'name': item.get('name', ''),
                    'market': 'SH' if code.startswith('6') else 'SZ',
                    'board': board,
                })
            
            return {
                'board': board,
                'source': 'sina',
                'total': len(data),
                'returned': len(stocks),
                'stocks': stocks,
                'codes': [item['code'] for item in stocks],
            }
        except Exception as e:
            return {'board': board, 'source': 'sina', 'total': 0, 'returned': 0, 'stocks': [], 'codes': [], 'error': str(e)}
    
    def _fetch_stock_universe_tencent(self, board='main', limit=None):
        """从腾讯财经获取股票列表（备用API）"""
        try:
            url = "https://web.sqt.gtimg.cn/q="
            market = 'sh' if board in ['main', 'sh_main'] else 'sz' if board == 'sz_main' else 'sh'
            
            # 腾讯API需要具体的股票代码，这里使用硬编码的主要股票
            if board in ['main', 'main_board', '主板']:
                stocks = HARDCODED_MAIN_BOARD_STOCKS[:limit] if limit else HARDCODED_MAIN_BOARD_STOCKS
                return {
                    'board': board,
                    'source': 'tencent',
                    'total': len(HARDCODED_MAIN_BOARD_STOCKS),
                    'returned': len(stocks),
                    'stocks': stocks,
                    'codes': [item['code'] for item in stocks],
                }
            
            return {'board': board, 'source': 'tencent', 'total': 0, 'returned': 0, 'stocks': [], 'codes': [], 'error': '不支持该板块'}
        except Exception as e:
            return {'board': board, 'source': 'tencent', 'total': 0, 'returned': 0, 'stocks': [], 'codes': [], 'error': str(e)}

    def fetch_realtime_eastmoney(self, code):
        try:
            time.sleep(random.uniform(0.5, 1.5))
            
            market = '1' if code.startswith('6') else '0'
            url = "http://push2.eastmoney.com/api/qt/stock/get"
            params = {
                'secid': f"{market}.{code}",
                'fields': 'f43,f50,f51,f52,f55,f57,f58,f60,f116,f117,f162',
                'cb': f"jQuery{random.randint(100000, 999999)}_{int(time.time() * 1000)}",
                '_': str(int(time.time() * 1000))
            }
            
            response = self._request_with_retry(
                url,
                params=params,
                headers=self._get_headers('http://quote.eastmoney.com/'),
                timeout=20
            )
            
            if response:
                data = response.json()
                if data and 'data' in data and data['data']:
                    d = data['data']
                    self._mark_api_success('eastmoney')
                    
                    result = {
                        'name': d.get('f58', ''),
                        'price': d.get('f43', 0) / 100 if d.get('f43') else None,
                        'pe_ttm': d.get('f162', 0) / 100 if d.get('f162') else None,
                        'pe_lyr': d.get('f50', 0) / 100 if d.get('f50') else None,
                        'pb': d.get('f51', 0) / 100 if d.get('f51') else None,
                        'market_cap': d.get('f116', 0) if d.get('f116') else None,
                        'circ_market_cap': d.get('f117', 0) if d.get('f117') else None,
                    }
                    
                    return self._normalize_realtime_data(result, 'eastmoney')
        except Exception as e:
            self._mark_api_error('eastmoney', e)
        return None
    
    def fetch_realtime_sina(self, code):
        try:
            market = 'sh' if code.startswith('6') else 'sz'
            url = f"http://hq.sinajs.cn/list={market}{code}"
            
            response = self._request_with_retry(
                url,
                headers=self._get_headers('https://finance.sina.com.cn/')
            )
            
            if response:
                text = response.text
                if text and '=' in text:
                    data_str = text.split('"')[1]
                    if data_str:
                        parts = data_str.split(',')
                        if len(parts) >= 30:
                            self._mark_api_success('sina')
                            result = {
                                'name': parts[0],
                                'price': float(parts[3]) if parts[3] else None,
                                'pe_ttm': None,
                                'pe_lyr': None,
                                'pb': None,
                                'market_cap': None,
                                'circ_market_cap': None,
                            }
                            return self._normalize_realtime_data(result, 'sina')
        except Exception as e:
            self._mark_api_error('sina', e)
        return None
    
    def fetch_realtime_tencent(self, code):
        try:
            market = 'sh' if code.startswith('6') else 'sz'
            url = f"https://web.sqt.gtimg.cn/q={market}{code}"
            
            response = self._request_with_retry(
                url,
                headers=self._get_headers('https://gu.qq.com/')
            )
            
            if response:
                text = response.text
                if text and '~' in text:
                    parts = text.split('~')
                    if len(parts) >= 45:
                        self._mark_api_success('tencent')
                        result = {
                            'name': parts[1],
                            'price': float(parts[3]) if parts[3] else None,
                            'pe_ttm': float(parts[39]) if len(parts) > 39 and parts[39] else None,
                            'pe_lyr': None,
                            'pb': float(parts[46]) if len(parts) > 46 and parts[46] else None,
                            'market_cap': float(parts[45]) * 100000000 if len(parts) > 45 and parts[45] else None,
                            'circ_market_cap': None,
                        }
                        
                        return self._normalize_realtime_data(result, 'tencent', allow_partial_full=True)
        except Exception as e:
            self._mark_api_error('tencent', e)
        return None
    
    def fetch_realtime_netease(self, code):
        try:
            market = '0' if code.startswith('6') else '1'
            url = f"http://api.money.126.net/data/feed/{market}{code}"
            
            response = self._request_with_retry(
                url,
                headers=self._get_headers('https://money.163.com/')
            )
            
            if response:
                text = response.text
                if text and '{' in text:
                    import json
                    json_str = text[text.find('{'):text.rfind('}')+1]
                    data = json.loads(json_str)
                    if data and f"{market}{code}" in data:
                        stock_data = data[f"{market}{code}"]
                        self._mark_api_success('netease')
                        result = {
                            'name': stock_data.get('name'),
                            'price': stock_data.get('price'),
                            'pe_ttm': stock_data.get('pe_ttm'),
                            'pe_lyr': stock_data.get('pe_lyr'),
                            'pb': stock_data.get('pb'),
                            'market_cap': stock_data.get('market_cap'),
                            'circ_market_cap': None,
                        }
                        
                        return self._normalize_realtime_data(result, 'netease', allow_partial_full=True)
        except Exception as e:
            self._mark_api_error('netease', e)
        return None
    
    def fetch_realtime(self, code):
        api_order = ['eastmoney', 'tencent', 'sina', 'netease']
        
        for api_name in api_order:
            if not self.api_status[api_name]['available']:
                continue
            
            try:
                if api_name == 'eastmoney':
                    result = self.fetch_realtime_eastmoney(code)
                elif api_name == 'tencent':
                    result = self.fetch_realtime_tencent(code)
                elif api_name == 'sina':
                    result = self.fetch_realtime_sina(code)
                elif api_name == 'netease':
                    result = self.fetch_realtime_netease(code)
                else:
                    continue
                
                if result:
                    return result, api_name
            except Exception as e:
                print(f"  [{api_name}] 实时数据失败: {e}")
                continue
        
        return None, None
    
    def fetch_minute_kline_eastmoney(self, code, klt=5, days=5):
        try:
            market = '1' if code.startswith('6') else '0'
            url = "http://push2his.eastmoney.com/api/qt/stock/kline/get"
            params = {
                'secid': f"{market}.{code}",
                'fields1': 'f1,f2,f3,f4,f5,f6',
                'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62',
                'klt': str(klt),
                'fqt': '1',
                'end': '20500101',
                'lmt': str(days * 240 if klt == 1 else days * 48 if klt == 5 else days * 16 if klt == 15 else days * 8 if klt == 30 else days * 4)
            }
            
            response = self._request_with_retry(
                url, 
                params=params, 
                headers=self._get_headers('http://quote.eastmoney.com/')
            )
            
            if response:
                data = response.json()
                if data and 'data' in data and data['data'] and 'klines' in data['data']:
                    self._mark_api_success('eastmoney')
                    return data['data']['klines']
        except Exception as e:
            self._mark_api_error('eastmoney', e)
        return None
    
    def fetch_minute_kline(self, code, klt=5, days=5):
        if self.api_status['eastmoney']['available']:
            result = self.fetch_minute_kline_eastmoney(code, klt, days)
            if result:
                return result, 'eastmoney'
        return None, None
    
    def fetch_fund_flow_history_eastmoney(self, code, days=100):
        try:
            market = '1' if code.startswith('6') else '0'
            url = "http://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
            params = {
                'lmt': str(days),
                'klt': '101',
                'secid': f"{market}.{code}",
                'fields1': 'f1,f2,f3,f7',
                'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63'
            }
            
            response = self._request_with_retry(
                url,
                params=params,
                headers=self._get_headers('http://quote.eastmoney.com/')
            )
            
            if response:
                data = response.json()
                if data and 'data' in data and data['data'] and 'klines' in data['data']:
                    self._mark_api_success('eastmoney')
                    return data['data']['klines']
        except Exception as e:
            self._mark_api_error('eastmoney', e)
        return None
    
    def fetch_fund_flow_intraday_eastmoney(self, code, klt=1):
        try:
            market = '1' if code.startswith('6') else '0'
            url = "http://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
            params = {
                'lmt': '0',
                'klt': str(klt),
                'secid': f"{market}.{code}",
                'fields1': 'f1,f2,f3,f7',
                'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63'
            }
            
            response = self._request_with_retry(
                url,
                params=params,
                headers=self._get_headers('http://quote.eastmoney.com/')
            )
            
            if response:
                data = response.json()
                if data and 'data' in data and data['data'] and 'klines' in data['data']:
                    self._mark_api_success('eastmoney')
                    return data['data']['klines']
        except Exception as e:
            self._mark_api_error('eastmoney', e)
        return None
    
    def fetch_fund_flow_ranking_eastmoney(self, board='a_share', sort_by='f62', sort_order='desc', limit=50):
        try:
            url = "http://push2.eastmoney.com/api/qt/clist/get"
            
            board_map = {
                'a_share': 'm:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23',
                'main': 'm:1+t:2,m:1+t:23',
                'gem': 'm:0+t:80',
                'star': 'm:1+t:23',
            }
            
            fs = board_map.get(board, board_map['a_share'])
            
            params = {
                'fid': sort_by,
                'po': '1' if sort_order == 'asc' else '0',
                'pz': str(limit),
                'pn': '1',
                'np': '1',
                'fltt': '2',
                'invt': '2',
                'ut': 'b2884a393a59ad64002292a3e90d46a5',
                'fs': fs,
                'fields': 'f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87'
            }
            
            response = self._request_with_retry(
                url,
                params=params,
                headers=self._get_headers('http://quote.eastmoney.com/')
            )
            
            if response:
                data = response.json()
                if data and 'data' in data and data['data'] and 'diff' in data['data']:
                    self._mark_api_success('eastmoney')
                    return data['data']['diff']
        except Exception as e:
            self._mark_api_error('eastmoney', e)
        return None
    
    def fetch_fund_flow_history(self, code, days=100):
        if self.api_status['eastmoney']['available']:
            result = self.fetch_fund_flow_history_eastmoney(code, days)
            if result:
                return result, 'eastmoney'
        return None, None
    
    def fetch_fund_flow_intraday(self, code, klt=1):
        if self.api_status['eastmoney']['available']:
            result = self.fetch_fund_flow_intraday_eastmoney(code, klt)
            if result:
                return result, 'eastmoney'
        return None, None
    
    def fetch_fund_flow_ranking(self, board='a_share', sort_by='f62', sort_order='desc', limit=50):
        if self.api_status['eastmoney']['available']:
            result = self.fetch_fund_flow_ranking_eastmoney(board, sort_by, sort_order, limit)
            if result:
                return result, 'eastmoney'
        return None, None
    
    def get_api_status(self):
        return self.api_status.copy()


if __name__ == '__main__':
    api = StockAPIProvider()
    
    print("测试K线数据获取:")
    print("-" * 50)
    
    codes = ['601138', '600487', '000333']
    for code in codes:
        print(f"\n获取 {code}...")
        klines, api_name = api.fetch_kline(code, days=10)
        if klines:
            print(f"  成功 [{api_name}]: {len(klines)} 条")
        else:
            print(f"  失败")
        
        realtime, api_name2 = api.fetch_realtime(code)
        if realtime:
            print(f"  实时数据 [{api_name2}]: {realtime.get('name')}, 价格={realtime.get('price')}")
        
        time.sleep(1)
    
    print("\n\nAPI状态:")
    print("-" * 50)
    for name, status in api.get_api_status().items():
        print(f"  {name}: {'可用' if status['available'] else '不可用'}, 错误次数={status['error_count']}")
