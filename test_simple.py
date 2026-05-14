"""测试简化的股票池"""
from stock_pool_simple import StockDataPool

pool = StockDataPool()

# 测试获取时间
time_info = pool.get_current_time_info()
print('时间信息:', time_info.get('date'), time_info.get('trading_session'))

# 测试获取实时行情
print('\n测试实时行情...')
quotes = pool.get_realtime_quotes(['600000', '000001'])
for q in quotes:
    if q.get('success'):
        print(f"  {q['code']}: {q.get('name')} 价格={q.get('price')}")
    else:
        print(f"  {q['code']}: 错误 - {q.get('error')}")

# 测试获取股票列表
print('\n测试股票列表...')
stocks = pool.get_stock_list('main')
print(f'  获取到 {len(stocks)} 只主板股票')
if stocks:
    print(f'  前3只: {stocks[:3]}')

# 测试综合分析
print('\n测试综合分析...')
result = pool.analyze_stock('600000')
if result.get('success'):
    print(f"  {result['code']}: {result.get('name')}")
    print(f"  技术信号: {result.get('technical_signals', {}).get('overall_signal')}")
    print(f"  估值水平: {result.get('valuation', {}).get('valuation_level')}")
else:
    print(f"  错误: {result.get('error')}")

print('\n所有测试完成!')
