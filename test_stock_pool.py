import unittest
import os
import sys
import time
import sqlite3
import tempfile
import shutil
import json
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from stock_pool.stock_pool import StockDataPool
from stock_pool import mcp_server
from stock_pool.provider_manager import ProviderManager
from stock_pool.providers.base import ProviderResult


class TestProviderManager(unittest.TestCase):
    
    def setUp(self):
        self.manager = ProviderManager()
        self.test_codes = ['601138', '600487', '000333']
    
    def test_providers_loaded(self):
        print("\n[测试] 数据源加载")
        providers = self.manager.get_all_providers()
        self.assertGreater(len(providers), 0, "至少应加载一个数据源")
        for name, provider in providers.items():
            print(f"  {provider.display_name}: 优先级={provider.priority}, 能力={len(provider.capabilities)}")
    
    def test_capability_index(self):
        print("\n[测试] 能力索引")
        from stock_pool.providers.base import ProviderCapability
        for cap in ProviderCapability:
            providers = self.manager.get_providers_for_capability(cap)
            print(f"  {cap.value}: {providers}")
    
    def test_realtime_quote(self):
        print("\n[测试] 实时行情获取")
        for code in self.test_codes[:1]:
            result = self.manager.fetch_realtime(code)
            if result.success:
                print(f"  {code}: {result.data.get('name', 'N/A')}")
            else:
                print(f"  {code}: 获取失败 - {result.error.message if result.error else 'unknown'}")
            time.sleep(0.5)
    
    def test_daily_kline(self):
        print("\n[测试] 日K线获取")
        for code in self.test_codes[:1]:
            result = self.manager.fetch_daily_kline(code, days=10)
            if result.success:
                print(f"  {code}: {len(result.data)} 条K线")
            else:
                print(f"  {code}: 获取失败 - {result.error.message if result.error else 'unknown'}")
            time.sleep(0.5)


class TestMCPToolBoundaries(unittest.TestCase):

    def test_mcp_public_contract_hides_storage_internals(self):
        contract = json.dumps(mcp_server.TOOLS, ensure_ascii=False).lower()

        for forbidden in ('缓存', '数据库', 'cache', 'database', 'db', '内部', '快照', '已准备', '服务端'):
            self.assertNotIn(forbidden, contract)

        raw_result = {
            'success': True,
            'data': [{
                'code': '600000',
                'cache_used': False,
                'effective_price_source': 'cache',
            }],
            'skipped': {
                'no_cached_snapshot': 2,
            }
        }
        public_result = mcp_server._sanitize_for_agent(raw_result)
        public_text = json.dumps(public_result, ensure_ascii=False).lower()

        self.assertNotIn('cache', public_text)
        self.assertNotIn('缓存', public_text)
        self.assertNotIn('uses_prepared_data', public_text)
        self.assertNotIn('effective_price_source', public_text)
        self.assertNotIn('skipped', public_text)
        self.assertEqual(public_result['data'][0]['code'], '600000')
        print("  MCP对外契约未暴露存储实现细节")

    def test_mcp_tool_count(self):
        print("\n[测试] MCP工具数量")
        tool_names = [tool['name'] for tool in mcp_server.TOOLS]
        print(f"  当前工具数量: {len(tool_names)}")
        print(f"  工具列表: {tool_names}")
        
        self.assertIn('screen_market', tool_names)
        self.assertIn('get_current_time', tool_names)
        self.assertIn('get_realtime_quotes', tool_names)
        self.assertIn('analyze_stock', tool_names)
        
        self.assertNotIn('get_cache_stats', tool_names)
        self.assertNotIn('get_db_stats', tool_names)
        self.assertNotIn('start_market_sync', tool_names)
        self.assertNotIn('update_stocks', tool_names)
        print("  工具列表验证通过")

    def test_screen_market_requires_filter(self):
        print("\n[测试] 市场筛选需要条件")
        no_filter_screen = mcp_server.handle_tool_call('screen_market', {})
        self.assertFalse(no_filter_screen['success'])
        error_msg = no_filter_screen.get('error', {})
        if isinstance(error_msg, dict):
            self.assertIn('筛选条件', error_msg.get('message', ''))
        else:
            self.assertIn('筛选条件', str(error_msg))
        print("  无条件筛选被正确拒绝")

    def test_get_latest_data_limit(self):
        print("\n[测试] 批量数据限制")
        codes = [f'{i:06d}' for i in range(35)]
        result = mcp_server.handle_tool_call('get_latest_data', {'codes': codes})
        self.assertFalse(result['success'])
        error_msg = result.get('error', {})
        if isinstance(error_msg, dict):
            self.assertIn('最多', error_msg.get('message', ''))
        else:
            self.assertIn('最多', str(error_msg))

        json_codes = json.dumps([f'{i:06d}' for i in range(11)])
        json_result = mcp_server.handle_tool_call('get_latest_data', {'codes': json_codes})
        self.assertFalse(json_result['success'])

        realtime_codes = json.dumps([f'{i:06d}' for i in range(6)])
        realtime_result = mcp_server.handle_tool_call('get_realtime_quotes', {'codes': realtime_codes})
        self.assertFalse(realtime_result['success'])
        print("  超量请求被正确拒绝")

    def test_analyze_stock(self):
        print("\n[测试] 综合分析工具")
        result = mcp_server.handle_tool_call('analyze_stock', {'code': '601138'})
        self.assertIn('success', result)
        print(f"  分析结果: success={result.get('success')}")


class TestStockDataPool(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp()
        cls.db_path = os.path.join(cls.test_dir, 'test_stock_pool.db')
        print(f"\n[测试数据库] {cls.db_path}")
    
    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.test_dir):
            shutil.rmtree(cls.test_dir)
            print(f"\n[清理] 删除测试目录: {cls.test_dir}")
    
    def setUp(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        self.pool = StockDataPool(db_path=self.db_path)
        self.test_codes = ['601138', '600487']
    
    def test_database_initialization(self):
        print("\n[测试] 数据库初始化")
        self.assertTrue(os.path.exists(self.db_path))
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        
        expected_tables = ['stock_info', 'stock_daily', 'stock_valuation', 
                          'stock_finance', 'stock_fund_flow', 'stock_technical']
        
        for table in expected_tables:
            self.assertIn(table, tables, f"表 {table} 不存在")
        
        conn.close()
        print(f"  已创建表: {tables}")
    
    def test_update_single_stock(self):
        print("\n[测试] 更新单只股票")
        code = self.test_codes[0]
        
        self.pool.update_stock(code, days=30, delay=0.5)
        
        info = self.pool.get_stock_info(code)
        self.assertIsNotNone(info, "股票信息未保存")
        self.assertEqual(info['code'], code)
        print(f"  股票信息: {info['name']}")
        
        daily = self.pool.get_daily_data(code, limit=5)
        self.assertGreater(len(daily), 0, "日K线数据未保存")
        print(f"  日K线: {len(daily)} 条")
        
        technical = self.pool.get_technical_data(code, limit=1)
        self.assertGreater(len(technical), 0, "技术指标未计算")
        self.assertIsNotNone(technical[0]['position_pct'], "位置百分比未计算")
        print(f"  技术指标: 位置={technical[0]['position_pct']:.1f}%")
    
    def test_data_caching(self):
        print("\n[测试] 数据缓存")
        code = self.test_codes[0]
        
        self.pool.update_stock(code, days=30, delay=0.5)
        
        stats1 = self.pool.get_db_stats()
        count1 = stats1['daily_count']
        print(f"  第一次更新: {count1} 条K线")
        
        self.pool.update_stock(code, days=30, delay=0.5)
        
        stats2 = self.pool.get_db_stats()
        count2 = stats2['daily_count']
        print(f"  第二次更新: {count2} 条K线")
        
        self.assertEqual(count1, count2, "重复更新导致数据重复")
        print("  缓存验证通过: 数据未重复")
    
    def test_incremental_update(self):
        print("\n[测试] 增量更新")
        code = self.test_codes[1]
        
        self.pool.update_stock(code, days=10, delay=0.5)
        
        daily1 = self.pool.get_daily_data(code)
        dates1 = set(d['date'] for d in daily1)
        print(f"  初次更新: {len(dates1)} 个交易日")
        
        self.pool.update_stock(code, days=30, delay=0.5)
        
        daily2 = self.pool.get_daily_data(code)
        dates2 = set(d['date'] for d in daily2)
        print(f"  增量更新: {len(dates2)} 个交易日")
        
        self.assertGreaterEqual(len(dates2), len(dates1), "增量更新后数据应该更多")
        self.assertTrue(dates1.issubset(dates2), "原有数据应该保留")
        print("  增量验证通过: 新数据已追加")
    
    def test_check_missing_data(self):
        print("\n[测试] 缺失数据检查")
        codes = ['601138', '600487', '000333']
        
        self.pool.update_stock('601138', days=10, delay=0.5)
        
        missing = self.pool.check_missing_data(codes, '2025-01-01', '2026-12-31')
        
        self.assertIn('600487', missing, "未更新的股票应该被检测为缺失")
        self.assertIn('000333', missing, "未更新的股票应该被检测为缺失")
        self.assertNotIn('601138', missing, "已更新的股票不应该被检测为缺失")
        print(f"  缺失股票: {list(missing.keys())}")
    
    def test_batch_update(self):
        print("\n[测试] 批量更新")
        codes = ['601138', '600487']
        
        results = self.pool.update_stocks(codes, days=10, delay=0.5)
        
        for code in codes:
            self.assertEqual(results.get(code), 'success', f"{code} 更新失败")
        
        stats = self.pool.get_db_stats()
        self.assertEqual(stats['stock_count'], 2)
        print(f"  成功更新: {stats['stock_count']} 只股票")
        print(f"  K线总数: {stats['daily_count']} 条")
    
    def test_position_analysis(self):
        print("\n[测试] 位置分析")
        codes = ['601138', '600487']
        
        self.pool.update_stocks(codes, days=250, delay=0.5)
        
        result = self.pool.analyze_position(codes)
        
        total = len(result['low']) + len(result['mid']) + len(result['mid_high']) + len(result['high'])
        self.assertEqual(total, 2, "分析结果数量不正确")
        
        print(f"  低位: {len(result['low'])} 只")
        print(f"  中位: {len(result['mid'])} 只")
        print(f"  中高位: {len(result['mid_high'])} 只")
        print(f"  高位: {len(result['high'])} 只")
        
        for category in ['low', 'mid', 'mid_high', 'high']:
            for stock in result[category]:
                self.assertIn('position_pct', stock)
                self.assertIn('code', stock)
                self.assertIn('name', stock)
    
    def test_get_latest_data(self):
        print("\n[测试] 获取最新数据")
        codes = ['601138']
        
        self.pool.update_stocks(codes, days=30, delay=0.5)
        
        data = self.pool.get_latest_data(codes)
        
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['code'], '601138')
        self.assertIsNotNone(data[0]['name'])
        self.assertIsNotNone(data[0]['close'])
        self.assertIsNotNone(data[0]['position_pct'])
        
        print(f"  {data[0]['code']} {data[0]['name']}")
        print(f"  收盘价: {data[0]['close']}")
        print(f"  位置: {data[0]['position_pct']:.1f}%")

    def test_batch_latest_data_and_main_board_screen(self):
        print("\n[测试] 批量快照与全主板筛选")
        pool = StockDataPool(':memory:')

        class FakeAPI:
            def __init__(self):
                self.realtime_calls = []

            def fetch_stock_list(self, board='main', limit=None, page_size=100):
                stocks = [
                    {'code': '000001', 'name': '测试000001', 'market': 'SZ', 'close': 11, 'pe_ttm': 20, 'pb': 2.0, 'market_cap': 100000000000},
                    {'code': '000002', 'name': '测试000002', 'market': 'SZ', 'close': 8, 'pe_ttm': 9, 'pb': 0.9, 'market_cap': 50000000000},
                    {'code': '000003', 'name': '测试000003', 'market': 'SZ', 'close': 9, 'pe_ttm': 12, 'pb': 1.1, 'market_cap': 70000000000},
                ]
                if limit:
                    stocks = stocks[:limit]
                return ProviderResult(
                    success=True,
                    data=stocks,
                    provider_name='fake'
                )

            def fetch_realtime(self, code):
                self.realtime_calls.append(code)
                return ProviderResult(success=False, data=None, provider_name='fake')

        pool.api = FakeAPI()

        samples = {
            '000001': [
                '2024-01-01,10,10,10,10,100,1000',
                '2024-01-02,10,11,11,10,100,1100',
            ],
            '000002': [
                '2024-01-01,10,10,10,10,100,1000',
                '2024-01-02,10,8,10,8,100,800',
            ],
            '000003': [
                '2024-01-01,10,10,10,10,100,1000',
                '2024-01-02,10,9,10,8,100,900',
            ],
        }

        valuations = {
            '000001': {'pe_ttm': 20, 'pb': 2.0, 'market_cap': 1000},
            '000002': {'pe_ttm': 9, 'pb': 0.9, 'market_cap': 500},
            '000003': {'pe_ttm': 12, 'pb': 1.1, 'market_cap': 700},
        }

        for code, klines in samples.items():
            pool.save_stock_info(code, {'name': f'测试{code}', 'market': 'SZ'})
            pool.save_daily_data(code, klines)
            pool.calculate_technical(code)
            valuation = dict(valuations[code])
            valuation.update({'data_source': 'fake', 'data_quality': 'full', 'missing_fields': []})
            pool.save_valuation_data(code, valuation)

        latest = pool.get_latest_data(['000001', '000002', '000003'], include_realtime=False)
        self.assertEqual([item['code'] for item in latest], ['000001', '000002', '000003'])
        self.assertEqual(pool.api.realtime_calls, [])

        result = pool.screen_market({
            'board': 'gem',
            'pe_ttm_max': 10,
            'limit': 10,
            'include_realtime': False,
        })

        self.assertTrue(result['success'])
        self.assertEqual(result['board'], 'gem')
        self.assertEqual(result['matched_count'], 1)
        self.assertEqual(result['results'][0]['code'], '000002')
        self.assertEqual(pool.api.realtime_calls, [])

        ratio_result = pool.screen_market({
            'board': 'gem',
            'pb_max': 1.2,
            'limit': 10,
            'include_realtime': False,
        })
        self.assertEqual(ratio_result['matched_count'], 2)

        market_cap_result = pool.screen_market({
            'board': 'gem',
            'market_cap_min': 600,
            'limit': 10,
        })
        self.assertEqual([item['code'] for item in market_cap_result['results']], ['000003', '000001'])

        class FailingListAPI:
            realtime_calls = []

            def fetch_stock_list(self, board='a_share', limit=None, page_size=100):
                return ProviderResult(success=False, data=None, provider_name='fake')

            def fetch_realtime(self, code):
                self.realtime_calls.append(code)
                return ProviderResult(success=False, data=None, provider_name='fake')

        pool.api = FailingListAPI()
        unavailable_result = pool.screen_market({
            'board': 'a_share',
            'pe_ttm_max': 15,
            'limit': 10,
            'include_realtime': False,
        })
        self.assertFalse(unavailable_result['success'])
        self.assertEqual(unavailable_result['error_code'], 'UNIVERSE_UNAVAILABLE')

        unsupported_result = pool.screen_market({
            'board': 'a_share',
            'position_max': 30,
            'pe_ttm_max': 15,
            'limit': 10,
        })
        self.assertFalse(unsupported_result['success'])
        self.assertEqual(unsupported_result['error_code'], 'UNSUPPORTED_SCREEN_PARAMETER')
        print(f"  筛选命中: {[item['code'] for item in result['results']]}")

    def test_daily_refresh_uses_cache_gap(self):
        print("\n[测试] 日K刷新按缓存缺口增量拉取")
        today = '2026-05-07'

        no_data = StockDataPool._calculate_daily_fetch_days({'has_data': False}, 250, today=today)
        enough_fresh = StockDataPool._calculate_daily_fetch_days({
            'has_data': True,
            'latest_date': today,
            'row_count': 250,
            'is_today': True,
        }, 250, today=today)
        stale_thick = StockDataPool._calculate_daily_fetch_days({
            'has_data': True,
            'latest_date': '2026-05-05',
            'row_count': 250,
            'is_today': False,
        }, 250, today=today)
        stale_thin = StockDataPool._calculate_daily_fetch_days({
            'has_data': True,
            'latest_date': '2026-05-05',
            'row_count': 20,
            'is_today': False,
        }, 250, today=today)
        forced = StockDataPool._calculate_daily_fetch_days({
            'has_data': True,
            'latest_date': today,
            'row_count': 250,
            'is_today': True,
        }, 250, force=True, today=today)

        self.assertEqual(no_data, 250)
        self.assertEqual(enough_fresh, 0)
        self.assertLess(stale_thick, 250)
        self.assertGreaterEqual(stale_thick, 5)
        self.assertEqual(stale_thin, 250)
        self.assertEqual(forced, 250)
        print(f"  厚缓存过期2天仅拉取: {stale_thick} 天")

    def test_screen_market_rejects_refresh(self):
        print("\n[测试] 市场筛选拒绝刷新缓存")
        pool = StockDataPool(':memory:')
        calls = []

        class FakeAPI:
            def fetch_stock_list(self, board='a_share', limit=None, page_size=100):
                codes = [f'000{i:03d}' for i in range(250)]
                return ProviderResult(
                    success=True,
                    data=[{'code': code} for code in codes],
                    provider_name='fake'
                )

            def fetch_realtime(self, code):
                return ProviderResult(
                    success=True,
                    data={'name': code, 'price': 1},
                    provider_name='fake'
                )

        pool.api = FakeAPI()

        def fake_update_stock(code, days=250, delay=1.5, force=False):
            calls.append((code, days, force))

        pool.update_stock = fake_update_stock
        result = pool.screen_market({
            'pe_ttm_max': 30,
            'refresh': 'missing',
            'delay': 0,
            'allow_no_filters': False,
        })

        self.assertFalse(result['success'])
        self.assertEqual(result['error_code'], 'UNSUPPORTED_SCREEN_PARAMETER')
        self.assertEqual(len(calls), 0)
        print("  screen_market 未触发本地刷新")

    def test_fund_flow_saves_eastmoney_six_field_rows(self):
        print("\n[测试] 东方财富6字段资金流保存")
        pool = StockDataPool(':memory:')
        rows = [
            '2026-05-13,1000.0,-200.0,-800.0,300.0,700.0',
            '2026-05-14,-500.0,100.0,400.0,-200.0,-300.0',
        ]

        saved = pool.save_fund_flow_data('000001', rows)
        data = pool.get_fund_flow('000001', limit=10)

        self.assertEqual(saved, 2)
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]['data_date'], '2026-05-14')
        self.assertEqual(data[0]['main_net_inflow'], -500.0)
        self.assertIsNone(data[0]['main_net_inflow_pct'])
        print("  6字段资金流已保存")

    def test_sync_market_refreshes_only_needed_codes(self):
        print("\n[测试] 市场同步只刷新需要补齐的股票")
        pool = StockDataPool(':memory:')
        refreshed = []

        class FakeAPI:
            def fetch_stock_list(self, board='a_share', limit=None, page_size=100):
                return ProviderResult(
                    success=True,
                    data=[{'code': c} for c in ['000001', '000002', '000003']],
                    provider_name='fake'
                )

        pool.api = FakeAPI()

        def fake_freshness(code, data_type='daily'):
            if code == '000001':
                return {'has_data': True, 'latest_date': pool.get_current_time_info()['date'], 'row_count': 250, 'is_today': True}
            if code == '000002':
                return {'has_data': True, 'latest_date': '2026-05-05', 'row_count': 250, 'is_today': False}
            return {'has_data': False}

        def fake_update_stock(code, days=250, delay=1.5, force=False):
            refreshed.append((code, days, force))

        pool.check_data_freshness = fake_freshness
        pool.update_stock = fake_update_stock

        progress = []
        result = pool.sync_market(
            board='a_share',
            refresh='stale',
            days=250,
            delay=0,
            progress_callback=lambda item: progress.append(item),
        )

        self.assertTrue(result['success'])
        self.assertEqual(result['scanned'], 3)
        self.assertEqual(result['skipped_fresh'], 1)
        self.assertEqual(result['refreshed'], 2)
        self.assertEqual([item[0] for item in refreshed], ['000002', '000003'])
        self.assertGreaterEqual(len(progress), 2)
        print(f"  刷新: {[item[0] for item in refreshed]}")

    def test_sync_job_interrupted_on_restart(self):
        print("\n[测试] 未完成同步任务重启后标记中断")
        pool = StockDataPool(':memory:')
        job = {
            'job_id': 'test-job-1',
            'status': 'running',
            'args': {'board': 'a_share'},
            'progress': {'scanned': 1},
            'created_at': '2026-05-07T10:00:00+08:00',
            'updated_at': '2026-05-07T10:00:00+08:00',
        }
        pool.save_sync_job(job)
        pool.mark_running_sync_jobs_interrupted('2026-05-07T10:01:00+08:00')

        stored = pool.get_sync_job('test-job-1')
        self.assertEqual(stored['status'], 'interrupted')
        self.assertIn('中断', stored['error'])
        print(f"  任务状态: {stored['status']}")
    
    def test_realtime_price_bypasses_database_cache(self):
        print("\n[测试] 实时价格直连API且不使用数据库缓存")
        pool = StockDataPool(':memory:')
        calls = []

        class FakeAPI:
            def fetch_realtime(self, code):
                calls.append(code)
                return ProviderResult(
                    success=True,
                    data={
                        'name': '测试股票',
                        'price': 12.34,
                        'pe_ttm': 10.5,
                        'pb': 1.2,
                    },
                    provider_name='fake'
                )

        pool.api = FakeAPI()
        data = pool.get_realtime_price('000001')

        self.assertEqual(calls, ['000001'])
        self.assertTrue(data['success'])
        self.assertFalse(data['cache_used'])
        self.assertEqual(data['price'], 12.34)
        self.assertEqual(data['api_name'], 'fake')
        self.assertEqual(pool.get_db_stats()['stock_count'], 0)

        batch = pool.get_realtime_prices(['000001', '000002'], delay=0)
        self.assertEqual([item['code'] for item in batch], ['000001', '000002'])
        self.assertEqual(pool.get_db_stats()['stock_count'], 0)
        print("  实时价格未读取/写入数据库缓存")
    
    def test_technical_calculation(self):
        print("\n[测试] 技术指标计算")
        code = '601138'
        
        self.pool.update_stock(code, days=100, delay=0.5)
        
        technical = self.pool.get_technical_data(code, limit=10)
        
        self.assertGreater(len(technical), 0)
        
        latest = technical[0]
        self.assertIsNotNone(latest['ma5'], "MA5未计算")
        self.assertIsNotNone(latest['ma10'], "MA10未计算")
        self.assertIsNotNone(latest['ma20'], "MA20未计算")
        self.assertIsNotNone(latest['high_52w'], "52周最高未计算")
        self.assertIsNotNone(latest['low_52w'], "52周最低未计算")
        self.assertIsNotNone(latest['position_pct'], "位置百分比未计算")
        
        print(f"  MA5: {latest['ma5']:.2f}")
        print(f"  MA10: {latest['ma10']:.2f}")
        print(f"  MA20: {latest['ma20']:.2f}")
        print(f"  52周最高: {latest['high_52w']:.2f}")
        print(f"  52周最低: {latest['low_52w']:.2f}")
        print(f"  位置: {latest['position_pct']:.1f}%")

    def test_memory_database_and_limit_validation(self):
        print("\n[测试] 内存数据库与limit校验")
        pool = StockDataPool(':memory:')
        sample = [
            '2024-01-01,10,10.5,10.8,9.9,1000,10500',
            '2024-01-02,10.5,10.7,10.9,10.2,1200,12840',
            '2024-01-03,10.7,10.4,10.8,10.1,900,9360',
            '2024-01-04,10.4,10.9,11.0,10.3,1500,16350',
            '2024-01-05,10.9,11.2,11.4,10.8,2000,22400',
            '2024-01-08,11.2,11.5,11.6,11.0,1800,20700',
            '2024-01-09,11.5,11.1,11.7,11.0,1600,17760',
            '2024-01-10,11.1,11.8,12.0,11.0,2200,25960',
            '2024-01-11,11.8,12.1,12.2,11.7,2100,25410',
            '2024-01-12,12.1,12.3,12.5,12.0,2300,28290',
            '2024-01-15,12.3,12.0,12.4,11.9,1700,20400',
            '2024-01-16,12.0,12.6,12.8,11.9,2500,31500',
            '2024-01-17,12.6,12.9,13.0,12.4,2600,33540',
            '2024-01-18,12.9,13.1,13.2,12.8,2400,31440',
            '2024-01-19,13.1,13.4,13.5,13.0,2700,36180',
            '2024-01-22,13.4,13.2,13.6,13.1,2100,27720',
            '2024-01-23,13.2,13.8,14.0,13.1,3000,41400',
            '2024-01-24,13.8,14.1,14.3,13.7,3200,45120',
            '2024-01-25,14.1,14.0,14.2,13.8,2800,39200',
            '2024-01-26,14.0,14.5,14.6,13.9,3500,50750',
        ]

        self.assertEqual(pool.save_daily_data('000001', sample), len(sample))
        pool.calculate_technical('000001')
        technical = pool.get_technical_data('000001', limit=1)
        self.assertEqual(len(technical), 1)
        latest = technical[0]
        self.assertIsNotNone(latest['ma5'])
        self.assertIsNotNone(latest['macd'])
        self.assertIsNotNone(latest['rsi_6'])
        self.assertIsNotNone(latest['kdj_k'])
        self.assertIsNotNone(latest['boll_upper'])
        self.assertIsNotNone(latest['atr'])
        self.assertIsNotNone(latest['obv'])
        self.assertIsNotNone(latest['position_pct'])

        with self.assertRaises(ValueError):
            pool.get_daily_data('000001', limit='1;drop table stock_daily')

        print("  内存数据库、技术指标与limit校验通过")

    def test_save_data_skips_bad_rows(self):
        print("\n[测试] 坏K线数据跳过")
        pool = StockDataPool(':memory:')

        saved_daily = pool.save_daily_data('000001', [
            'bad,row',
            '2024-01-01,10,10.5,10.8,9.9,1000,10500',
        ])
        self.assertEqual(saved_daily, 1)
        self.assertEqual(len(pool.get_daily_data('000001')), 1)

        saved_minute = pool.save_minute_data('000001', [
            'bad,row',
            '2024-01-01 09:30,10,10,10,10,0,0',
        ], 5)
        self.assertEqual(saved_minute, 1)
        self.assertEqual(len(pool.get_minute_data('000001')), 1)

        print("  坏数据已跳过且有效数据保存成功")

    def test_update_minute_refreshes_stale_data_for_requested_klt(self):
        print("\n[测试] 分钟K线按klt检查新鲜度")
        pool = StockDataPool(':memory:')
        pool.save_minute_data('000001', ['2000-01-01 09:35,10,10,10,10,0,0'], 5)

        class FakeAPI:
            def __init__(self):
                self.calls = []

            def fetch_minute_kline(self, code, klt, days):
                self.calls.append((code, klt, days))
                return ProviderResult(
                    success=True,
                    data=['2026-05-08 09:35,11,12,13,10,100,1200'],
                    provider_name='fake',
                )

        fake_api = FakeAPI()
        pool.api = fake_api

        self.assertFalse(pool.check_data_freshness('000001', 'minute', klt=1)['has_data'])
        pool.update_minute_data('000001', klt=5, days=1, delay=0)

        self.assertEqual(fake_api.calls, [('000001', 5, 1)])
        self.assertEqual(len(pool.get_minute_data('000001', klt=5)), 2)

        print("  历史分钟数据不会阻止拉取，不同klt互不干扰")

    def test_update_minute_reports_requested_range_not_available(self):
        print("\n[测试] 分钟K线目标区间不可用时返回明确原因")
        pool = StockDataPool(':memory:')

        class FakeAPI:
            def fetch_minute_kline(self, code, klt, days):
                return ProviderResult(
                    success=True,
                    data=[
                        '2026-03-20 09:35,10,10,10,10,1,10',
                        '2026-05-08 15:00,11,11,11,11,1,11',
                    ],
                    provider_name='fake',
                )

        pool.api = FakeAPI()
        result = pool.update_minute_data(
            '603993',
            klt=5,
            days=5,
            delay=0,
            force=True,
            start_time='2026-03-10 09:30',
            end_time='2026-03-10 15:00',
        )

        self.assertFalse(result['success'])
        self.assertFalse(result['target_covered'])
        self.assertEqual(result['fetched_range']['start_time'], '2026-03-20 09:35')
        self.assertEqual(result['resolution']['action_required'], 'unavailable_from_provider')
        self.assertTrue(result['resolution']['do_not_retry_update'])

        print("  已识别外部分时接口范围不覆盖目标日期")

    def test_analyze_intraday_edge_cases(self):
        print("\n[测试] 日内分析边界场景")
        empty_pool = StockDataPool(':memory:')
        empty_result = empty_pool.analyze_intraday('000001', '2024-01-01')
        self.assertFalse(empty_result['success'])
        self.assertEqual(empty_result['requested_date'], '2024-01-01')
        self.assertTrue(empty_result['do_not_analyze_other_date'])
        self.assertIn('update_minute_data', empty_result['next_actions'])
        self.assertEqual(empty_result['resolution']['action_required'], 'call_tools')
        self.assertEqual(empty_result['resolution']['wait_seconds'], 0)
        self.assertEqual(empty_result['resolution']['required_calls'][0]['tool'], 'update_minute_data')
        self.assertEqual(empty_result['resolution']['retry_call']['arguments']['date'], '2024-01-01')

        pool = StockDataPool(':memory:')
        pool.save_daily_data('000001', ['2024-01-01,10,10,10,10,0,0'])
        pool.save_minute_data('000001', ['2024-01-01 09:30,10,10,10,10,0,0'], 5)

        result = pool.analyze_intraday('000001', '2024-01-01')
        self.assertTrue(result['success'])
        self.assertEqual(result['morning_review']['first_30min_vol_pct'], 0)
        self.assertEqual(result['morning_review']['last_30min_vol_pct'], 0)

        print("  无数据与零成交量场景处理正常")


class TestDatabaseIntegrity(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp()
        cls.db_path = os.path.join(cls.test_dir, 'test_integrity.db')
    
    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.test_dir):
            shutil.rmtree(cls.test_dir)
    
    def setUp(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        self.pool = StockDataPool(db_path=self.db_path)
    
    def test_unique_constraint_daily(self):
        print("\n[测试] 日K线唯一约束")
        code = '601138'
        
        self.pool.update_stock(code, days=10, delay=0.5)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM stock_daily WHERE code = ?", (code,))
        count1 = cursor.fetchone()[0]
        
        cursor.execute("SELECT data_date FROM stock_daily WHERE code = ? ORDER BY data_date DESC LIMIT 1", (code,))
        last_date = cursor.fetchone()[0]
        conn.close()
        
        duplicate_kline = f"{last_date},10.0,10.5,11.0,9.5,1000000,10000000"
        self.pool.save_daily_data(code, [duplicate_kline])
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM stock_daily WHERE code = ?", (code,))
        count2 = cursor.fetchone()[0]
        conn.close()
        
        print(f"  插入前: {count1} 条, 插入后: {count2} 条")
        self.assertEqual(count1, count2, "重复数据未被正确处理: 相同日期的数据应该被覆盖而非新增")
    
    def test_data_consistency(self):
        print("\n[测试] 数据一致性")
        code = '601138'
        
        self.pool.update_stock(code, days=50, delay=0.5)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM stock_daily WHERE code = ?", (code,))
        daily_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM stock_technical WHERE code = ?", (code,))
        technical_count = cursor.fetchone()[0]
        
        conn.close()
        
        print(f"  日K线: {daily_count} 条")
        print(f"  技术指标: {technical_count} 条")
        
        self.assertEqual(daily_count, technical_count, "日K线与技术指标数量不一致")


def run_tests():
    print("=" * 60)
    print("股票数据池自动化测试")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestProviderManager))
    suite.addTests(loader.loadTestsFromTestCase(TestMCPToolBoundaries))
    suite.addTests(loader.loadTestsFromTestCase(TestStockDataPool))
    suite.addTests(loader.loadTestsFromTestCase(TestDatabaseIntegrity))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    print(f"运行测试: {result.testsRun}")
    print(f"成功: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"失败: {len(result.failures)}")
    print(f"错误: {len(result.errors)}")
    
    if result.failures:
        print("\n失败的测试:")
        for test, traceback in result.failures:
            print(f"  - {test}")
    
    if result.errors:
        print("\n出错的测试:")
        for test, traceback in result.errors:
            print(f"  - {test}")
    
    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)
