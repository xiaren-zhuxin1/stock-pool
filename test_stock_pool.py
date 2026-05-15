"""
StockDataPool v3 测试
"""
import unittest
import sys
import os

test_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(test_dir)
sys.path.insert(0, parent_dir)

from stock_pool import StockDataPool, RateLimiter, SessionCache
from mcp_server import StockPoolServer, handle_tool_call


class TestRateLimiter(unittest.TestCase):
    
    def test_rate_limiter_basic(self):
        limiter = RateLimiter(max_requests=3, window=1)
        
        ok1, _ = limiter.acquire(wait=False)
        self.assertTrue(ok1)
        
        ok2, _ = limiter.acquire(wait=False)
        self.assertTrue(ok2)
        
        ok3, _ = limiter.acquire(wait=False)
        self.assertTrue(ok3)
        
        ok4, _ = limiter.acquire(wait=False)
        self.assertFalse(ok4)
    
    def test_rate_limiter_wait(self):
        import time
        limiter = RateLimiter(max_requests=2, window=1)
        
        limiter.acquire(wait=True)
        limiter.acquire(wait=True)
        
        start = time.time()
        limiter.acquire(wait=True)
        elapsed = time.time() - start
        
        self.assertGreater(elapsed, 0.5)


class TestSessionCache(unittest.TestCase):
    
    def test_cache_basic(self):
        cache = SessionCache()
        
        cache.set('key1', 'value1', 'kline')
        self.assertEqual(cache.get('key1', 'kline'), 'value1')
    
    def test_cache_ttl(self):
        import time
        cache = SessionCache()
        cache._ttl['test'] = 0.1
        
        cache.set('key1', 'value1', 'test')
        self.assertEqual(cache.get('key1', 'test'), 'value1')
        
        time.sleep(0.2)
        self.assertIsNone(cache.get('key1', 'test'))
    
    def test_cache_no_ttl(self):
        cache = SessionCache()
        
        cache.set('key1', 'value1', 'realtime')
        self.assertIsNone(cache.get('key1', 'realtime'))
    
    def test_cache_clear(self):
        cache = SessionCache()
        
        cache.set('key1', 'value1', 'kline')
        cache.set('key2', 'value2', 'kline')
        
        cache.clear()
        
        self.assertIsNone(cache.get('key1', 'kline'))
        self.assertIsNone(cache.get('key2', 'kline'))


class TestStockDataPool(unittest.TestCase):
    
    def setUp(self):
        self.pool = StockDataPool()
        self.test_codes = ['601138', '600487']
    
    def test_get_current_time(self):
        result = self.pool.get_current_time_info()
        
        self.assertIn('timezone', result)
        self.assertIn('date', result)
        self.assertIn('is_trading_day', result)
        self.assertIn('trading_session', result)
    
    def test_get_realtime_quotes(self):
        result = self.pool.get_realtime_quotes(['601138'])
        
        self.assertIn('success', result)
        self.assertIn('results', result)
        self.assertIn('failed', result)
        self.assertIn('partial', result)
    
    def test_get_daily_kline(self):
        result = self.pool.get_daily_kline('601138', days=30)
        
        self.assertIn('success', result)
        if result.get('success'):
            self.assertIn('klines', result)
            self.assertIn('count', result)
    
    def test_analyze_position(self):
        result = self.pool.analyze_position(['601138'])
        
        self.assertIn('success', result)
        self.assertIn('results', result)
        self.assertIn('failed', result)
        self.assertIn('partial', result)
    
    def test_screen_market_requires_filter(self):
        result = self.pool.screen_market({})
        
        self.assertFalse(result.get('success'))
        self.assertIn('error', result)


class TestMCPServer(unittest.TestCase):
    
    def setUp(self):
        self.server = StockPoolServer()
    
    def test_get_current_time(self):
        result = handle_tool_call('get_current_time', {})
        
        self.assertTrue(result.get('success'))
        self.assertIn('data', result)
    
    def test_get_realtime_quotes_limit(self):
        codes = [f'{i:06d}' for i in range(25)]
        result = handle_tool_call('get_realtime_quotes', {'codes': codes})
        
        self.assertFalse(result.get('success'))
    
    def test_analyze_position_limit(self):
        codes = [f'{i:06d}' for i in range(25)]
        result = handle_tool_call('analyze_position', {'codes': codes})
        
        self.assertFalse(result.get('success'))
    
    def test_get_latest_data_limit(self):
        codes = [f'{i:06d}' for i in range(15)]
        result = handle_tool_call('get_latest_data', {'codes': codes})
        
        self.assertFalse(result.get('success'))
    
    def test_screen_market_requires_filter(self):
        result = handle_tool_call('screen_market', {})
        
        self.assertFalse(result.get('success'))
    
    def test_unknown_tool(self):
        result = handle_tool_call('unknown_tool', {})
        
        self.assertFalse(result.get('success'))
        self.assertIn('error', result)


class TestPartialSuccess(unittest.TestCase):
    
    def setUp(self):
        self.pool = StockDataPool()
    
    def test_partial_success_structure(self):
        result = self.pool.get_realtime_quotes(['601138', '999999'])
        
        self.assertIn('success', result)
        self.assertIn('results', result)
        self.assertIn('failed', result)
        self.assertIn('total', result)
        self.assertIn('success_count', result)
        self.assertIn('failed_count', result)
        self.assertIn('partial', result)


if __name__ == '__main__':
    unittest.main(verbosity=2)
