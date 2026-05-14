"""
Provider 层单元测试

使用 Mock 数据减少真实网络测试依赖
"""
import unittest
from unittest.mock import patch
from providers.base import ProviderResult, ProviderError, ErrorType
from providers.eastmoney import EastMoneyProvider
from providers.sina import SinaProvider
from providers.tencent import TencentProvider


class MockResponse:
    def __init__(self, json_data=None, text_data=None, status_code=200):
        self._json_data = json_data
        self._text_data = text_data
        self.status_code = status_code
        self.text = text_data or ''

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


class TestEastMoneyProvider(unittest.TestCase):
    def setUp(self):
        self.provider = EastMoneyProvider()

    def test_market_code_conversion(self):
        self.assertEqual(self.provider._get_market_code('600000'), '1.600000')
        self.assertEqual(self.provider._get_market_code('000001'), '0.000001')
        self.assertEqual(self.provider._get_market_code('300001'), '0.300001')
        self.assertEqual(self.provider._get_market_code('688001'), '1.688001')
        self.assertEqual(self.provider._get_market_code('430001'), '0.430001')
        self.assertEqual(self.provider._get_market_code('830001'), '0.830001')

    @patch('providers.base.requests.get')
    def test_fetch_realtime_success(self, mock_get):
        mock_response = MockResponse(json_data={
            'data': {
                'f43': 1000,
                'f44': 1010,
                'f45': 990,
                'f46': 1005,
                'f47': 1000000,
                'f48': 100000000,
                'f58': '测试股票',
                'f170': 20.5,
                'f152': 2,
                'f162': 1050,
                'f163': 980,
                'f167': 120,
                'f116': 10000000000,
            }
        })
        mock_get.return_value = mock_response

        result = self.provider.fetch_realtime('000001')
        self.assertTrue(result.success)
        self.assertEqual(result.data['price'], 10.00)
        self.assertEqual(result.data['pe_ttm'], 10.5)
        self.assertEqual(result.data['pe_lyr'], 9.8)
        self.assertEqual(result.data['pb'], 1.2)
        self.assertEqual(result.data['name'], '测试股票')

    @patch('providers.base.requests.get')
    def test_fetch_realtime_invalid_code(self, mock_get):
        mock_response = MockResponse(json_data={'data': None})
        mock_get.return_value = mock_response

        result = self.provider.fetch_realtime('999999')
        self.assertFalse(result.success)

    @patch('providers.base.requests.get')
    def test_fetch_stock_list_success(self, mock_get):
        mock_response = MockResponse(json_data={
            'data': {
                'diff': [
                    {'f12': '000001', 'f14': '平安银行'},
                    {'f12': '000002', 'f14': '万科A'},
                ]
            }
        })
        mock_get.return_value = mock_response

        result = self.provider.fetch_stock_list('main')
        self.assertTrue(result.success)
        self.assertEqual(len(result.data), 2)
        self.assertEqual(result.data[0]['code'], '000001')


class TestSinaProvider(unittest.TestCase):
    def setUp(self):
        self.provider = SinaProvider()

    def test_market_code_conversion(self):
        self.assertEqual(self.provider._get_market_code('600000'), 'sh600000')
        self.assertEqual(self.provider._get_market_code('000001'), 'sz000001')
        self.assertEqual(self.provider._get_market_code('300001'), 'sz300001')
        self.assertEqual(self.provider._get_market_code('688001'), 'sh688001')
        self.assertEqual(self.provider._get_market_code('430001'), 'bj430001')
        self.assertEqual(self.provider._get_market_code('830001'), 'bj830001')

    @patch('providers.base.requests.get')
    def test_fetch_realtime_success(self, mock_get):
        mock_response = MockResponse(text_data='var hq_str_sh600000="浦发银行,10.00,9.90,10.05,10.10,9.90,10.05,1000000,10000000,10.00,10.05,9.99,10.00,10.05,9.99,10.00,2024-01-01,10:00:00,20.5,2.0,10000000000,1000000000,1000000000,100000000,100000000,100000000,100000000,100000000,100000000,100000000,100000000,100000000";')
        mock_get.return_value = mock_response

        result = self.provider.fetch_realtime('600000')
        self.assertTrue(result.success)
        self.assertEqual(result.data['name'], '浦发银行')
        self.assertEqual(result.data['price'], 10.05)


class TestTencentProvider(unittest.TestCase):
    def setUp(self):
        self.provider = TencentProvider()

    def test_market_code_conversion(self):
        self.assertEqual(self.provider._get_market_code('600000'), 'sh600000')
        self.assertEqual(self.provider._get_market_code('000001'), 'sz000001')
        self.assertEqual(self.provider._get_market_code('300001'), 'sz300001')
        self.assertEqual(self.provider._get_market_code('688001'), 'sh688001')
        self.assertEqual(self.provider._get_market_code('430001'), 'bj430001')
        self.assertEqual(self.provider._get_market_code('830001'), 'bj830001')

    @patch('providers.base.requests.get')
    def test_fetch_realtime_success(self, mock_get):
        mock_response = MockResponse(text_data='v_sh600000="1~浦发银行~600000~10.05~10.00~9.90~10.10~1000000~10000000~~2024-01-01~10:00:00~0.15~1.50%~10.00~10.00~10.00~10000000000~1000000000~20.5~2.0~10000000000~1000000000~1000000000~100000000~100000000~100000000~100000000~100000000~100000000~100000000~100000000~1.50~10.10~9.90~10000000~20.5~2.0~10000000000~1000000000~1000000000~100000000~100000000~100000000~100000000~100000000~100000000~100000000~100000000~100000000";')
        mock_get.return_value = mock_response

        result = self.provider.fetch_realtime('600000')
        self.assertTrue(result.success)
        self.assertEqual(result.data['name'], '浦发银行')
        self.assertEqual(result.data['price'], 10.05)


class TestProviderResult(unittest.TestCase):
    def test_success_result(self):
        result = ProviderResult(success=True, data={'price': 10.0}, provider_name='test')
        self.assertTrue(result.success)
        self.assertEqual(result.data['price'], 10.0)
        self.assertEqual(result.provider_name, 'test')
        self.assertIsNone(result.error)

    def test_error_result(self):
        error = ProviderError(message="API Error", error_type=ErrorType.UNKNOWN, provider_name='test')
        result = ProviderResult(success=False, data=None, error=error, provider_name='test')
        self.assertFalse(result.success)
        self.assertEqual(result.error.message, "API Error")


if __name__ == '__main__':
    unittest.main()
