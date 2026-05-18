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
from providers.base import ProviderResult


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
    
    def test_cache_persistent(self):
        cache = SessionCache()
        
        cache.set('key1', 'value1', 'realtime')
        self.assertEqual(cache.get('key1', 'realtime'), 'value1')
    
    def test_cache_clear_all(self):
        cache = SessionCache()
        
        cache.set('key1', 'value1', 'kline')
        cache.set('key2', 'value2', 'kline')
        
        cache.clear()
        
        self.assertIsNone(cache.get('key1', 'kline'))
        self.assertIsNone(cache.get('key2', 'kline'))
    
    def test_cache_clear_pattern(self):
        cache = SessionCache()
        
        cache.set('kline_601138', 'data1', 'kline')
        cache.set('kline_600487', 'data2', 'kline')
        cache.set('realtime_601138', 'data3', 'realtime')
        
        cache.clear('kline_')
        
        self.assertIsNone(cache.get('kline_601138', 'kline'))
        self.assertIsNone(cache.get('kline_600487', 'kline'))
        self.assertEqual(cache.get('realtime_601138', 'realtime'), 'data3')
    
    def test_cache_stats(self):
        cache = SessionCache()
        
        cache.set('key1', 'value1', 'kline')
        cache.set('key2', 'value2', 'kline')
        
        stats = cache.get_stats()
        
        self.assertEqual(stats['total_items'], 2)
        self.assertIn('key1', stats['keys'])
        self.assertIn('key2', stats['keys'])


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

    def test_calculate_52w_position_from_kline(self):
        klines = [
            {'date': '2026-01-01', 'high': 11.0, 'low': 9.0},
            {'date': '2026-01-02', 'high': 12.0, 'low': 8.0},
            {'date': '2026-01-03', 'high': 10.0, 'low': 9.5},
        ]
        result = self.pool._calculate_52w_position('000001', price=10.0, klines=klines)

        self.assertEqual(result['high_52w'], 12.0)
        self.assertEqual(result['low_52w'], 8.0)
        self.assertEqual(result['position_pct'], 50.0)

    def test_analyze_position_uses_kline_when_realtime_lacks_52w(self):
        class FakeApi:
            def fetch_realtime(self, code):
                return ProviderResult(
                    success=True,
                    data={'code': code, 'name': 'Test Bank', 'price': 10.0},
                    provider_name='sina',
                )

        self.pool.api = FakeApi()
        self.pool.get_daily_kline = lambda code, days=250: {
            'success': True,
            'klines': [
                {'date': '2026-01-01', 'high': 11.0, 'low': 9.0},
                {'date': '2026-01-02', 'high': 12.0, 'low': 8.0},
            ],
        }

        result = self.pool.analyze_position(['000001'])
        position = result['results'][0]

        self.assertEqual(position['high_52w'], 12.0)
        self.assertEqual(position['low_52w'], 8.0)
        self.assertEqual(position['position_pct'], 50.0)

    def test_get_latest_data_enriches_missing_valuation_fields(self):
        class FakeApi:
            def fetch_realtime(self, code):
                return ProviderResult(
                    success=True,
                    data={'code': code, 'name': 'Test Bank', 'price': 10.0},
                    provider_name='sina',
                )

            def fetch_valuation(self, code):
                return ProviderResult(
                    success=True,
                    data={'pe_ttm': 6.5, 'pb': 0.7, 'market_cap': 10000000000},
                    provider_name='akshare',
                )

        self.pool.api = FakeApi()
        self.pool.get_daily_kline = lambda code, days=250: {
            'success': True,
            'klines': [
                {'date': '2026-01-01', 'high': 11.0, 'low': 9.0},
                {'date': '2026-01-02', 'high': 12.0, 'low': 8.0},
            ],
        }

        result = self.pool.get_latest_data(['000001'])
        latest = result['results'][0]

        self.assertEqual(latest['pe_ttm'], 6.5)
        self.assertEqual(latest['pb'], 0.7)
        self.assertEqual(latest['market_cap'], 10000000000)
        self.assertEqual(latest['position_pct'], 50.0)


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


class TestCacheManagement(unittest.TestCase):
    
    def setUp(self):
        self.pool = StockDataPool()
    
    def test_get_cache_stats(self):
        result = self.pool.get_cache_stats()
        
        self.assertTrue(result.get('success'))
        self.assertIn('total_items', result)
        self.assertIn('max_size', result)
        self.assertIn('usage_pct', result)
    
    def test_clear_cache_all(self):
        self.pool.cache.set('key1', 'value1', 'kline')
        self.pool.cache.set('key2', 'value2', 'kline')
        
        result = self.pool.clear_cache()
        
        self.assertTrue(result.get('success'))
        self.assertEqual(result['cleared_items'], 2)
    
    def test_clear_cache_pattern(self):
        self.pool.cache.set('kline_601138', 'data1', 'kline')
        self.pool.cache.set('kline_600487', 'data2', 'kline')
        self.pool.cache.set('realtime_601138', 'data3', 'realtime')
        
        result = self.pool.clear_cache('kline_')
        
        self.assertTrue(result.get('success'))
        self.assertEqual(result['pattern'], 'kline_')
    
    def test_mcp_clear_cache(self):
        result = handle_tool_call('clear_cache', {})
        
        self.assertTrue(result.get('success'))
    
    def test_mcp_get_cache_stats(self):
        result = handle_tool_call('get_cache_stats', {})
        
        self.assertTrue(result.get('success'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
