import requests
import time
import random
from datetime import datetime
import sys
import builtins


def print(*args, **kwargs):
    """API 层日志统一输出到 stderr，避免 MCP stdout JSON-RPC 通道被污染。"""
    kwargs.setdefault('file', sys.stderr)
    return builtins.print(*args, **kwargs)

class StockAPIProvider:
    
    def __init__(self):
        self.timeout = 15
        self.max_retries = 3
        self.retry_delay = 1
        
        self.api_status = {
            'eastmoney': {'available': True, 'last_error': None, 'error_count': 0},
            'sina': {'available': True, 'last_error': None, 'error_count': 0},
            'tencent': {'available': True, 'last_error': None, 'error_count': 0},
            'netease': {'available': True, 'last_error': None, 'error_count': 0},
        }
        
        self.api_priority = ['eastmoney', 'sina', 'tencent', 'netease']
    
    def _get_headers(self, referer=None):
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
        }
        if referer:
            headers['Referer'] = referer
            headers['Origin'] = referer.rstrip('/') if referer else None
        return headers
    
    def _request_with_retry(self, url, params=None, headers=None, timeout=None):
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
                    raise Exception("Rate limited")
                else:
                    raise Exception(f"HTTP {response.status_code}")
            except requests.exceptions.Timeout:
                if attempt < self.max_retries - 1:
                    print(f"  超时，重试 {attempt + 2}/{self.max_retries}...")
                    continue
                raise Exception("Timeout")
            except requests.exceptions.ConnectionError:
                if attempt < self.max_retries - 1:
                    print(f"  连接错误，重试 {attempt + 2}/{self.max_retries}...")
                    continue
                raise Exception("Connection error")
            except Exception as e:
                raise e
        
        return None
    
    def _mark_api_error(self, api_name, error):
        self.api_status[api_name]['error_count'] += 1
        self.api_status[api_name]['last_error'] = str(error)
        
        if self.api_status[api_name]['error_count'] >= 3:
            self.api_status[api_name]['available'] = False
            print(f"  [API降级] {api_name} 暂时不可用: {error}")
    
    def _mark_api_success(self, api_name):
        self.api_status[api_name]['error_count'] = 0
        self.api_status[api_name]['available'] = True
    
    def get_available_api(self):
        for api_name in self.api_priority:
            if self.api_status[api_name]['available']:
                return api_name
        for api_name in self.api_priority:
            self.api_status[api_name]['available'] = True
            self.api_status[api_name]['error_count'] = 0
        return self.api_priority[0]
    
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
                        'data_source': 'eastmoney',
                        'data_quality': 'full',
                    }
                    
                    missing_fields = [k for k, v in result.items() 
                                    if k not in ['data_source', 'data_quality', 'missing_fields'] 
                                    and v is None]
                    result['missing_fields'] = missing_fields
                    if missing_fields:
                        result['data_quality'] = 'partial'
                    
                    return result
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
                                'data_source': 'sina',
                                'data_quality': 'partial',
                                'missing_fields': ['pe_ttm', 'pe_lyr', 'pb', 'market_cap', 'circ_market_cap'],
                            }
                            return result
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
                            'data_source': 'tencent',
                            'data_quality': 'partial',
                        }
                        
                        missing_fields = [k for k, v in result.items() 
                                        if k not in ['data_source', 'data_quality', 'missing_fields'] 
                                        and v is None]
                        result['missing_fields'] = missing_fields
                        if len(missing_fields) < 3:
                            result['data_quality'] = 'full'
                        
                        return result
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
                            'data_source': 'netease',
                            'data_quality': 'partial',
                        }
                        
                        missing_fields = [k for k, v in result.items() 
                                        if k not in ['data_source', 'data_quality', 'missing_fields'] 
                                        and v is None]
                        result['missing_fields'] = missing_fields
                        if len(missing_fields) < 3:
                            result['data_quality'] = 'full'
                        
                        return result
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
