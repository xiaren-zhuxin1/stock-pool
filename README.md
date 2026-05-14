# 股票数据池

股票数据获取和分析服务，支持MCP协议。

## 功能

- **多数据源降级**：支持7个数据源，自动降级和冷却恢复
- **智能缓存**：LRU缓存 + 数据库缓存，减少API调用
- **自动刷新**：数据过期自动拉取，无需手动更新
- **专业分析**：技术指标、风险指标、主力资金、支撑压力位
- **市场筛选**：按在线估值、市值筛选全市场股票，不使用本地缓存子集
- **MCP协议**：支持AI模型直接调用

## 数据源

| 数据源 | 类型 | 优先级 | 能力 |
|--------|------|--------|------|
| 东方财富 | 免费 | 1 | 全能（行情、K线、估值、资金流） |
| 新浪财经 | 免费 | 2 | 行情、K线 |
| AkShare | 免费 | 3 | 全能 |
| 腾讯财经 | 免费 | 4 | 行情、K线 |
| 网易财经 | 免费 | 5 | 行情、K线 |
| Baostock | 免费 | 6 | K线 |
| TuShare Pro | 付费 | 10 | 全能+财务数据 |

### 降级机制

1. 按优先级依次尝试数据源
2. 单个数据源失败后进入5分钟冷却期
3. 冷却期后自动恢复
4. 所有数据源失败时返回明确错误

## MCP工具列表 (13个)

### 系统工具

| 工具 | 说明 |
|------|------|
| get_current_time | 获取北京时间、交易日、交易时段。**分析前必须调用** |

### 行情工具

| 工具 | 说明 | 限制 |
|------|------|------|
| get_realtime_quotes | 获取实时行情（支持单只或小批量） | 最多5只 |
| get_daily_kline | 获取日K线数据 | 自动刷新 |
| get_minute_kline | 获取分钟K线数据 | 支持1/5/15/30/60分钟 |

### 分析工具

| 工具 | 说明 |
|------|------|
| analyze_stock | **综合分析**：技术信号+风险指标+量价+支撑压力+主力资金+估值 |
| analyze_position | 分析52周位置，判断高低位 |
| analyze_intraday | 日内走势分析（仅交易时间） |

### 数据工具

| 工具 | 说明 |
|------|------|
| get_fund_flow | 获取资金流向+主力资金分析 |
| get_financial_data | 获取财务数据（利润表、资产负债表、现金流量表） |
| get_latest_data | 小批量获取综合数据（行情+估值+位置） |
| get_stock_detail | 获取股票详情（基本信息+行情+资金流） |

### 筛选工具

| 工具 | 说明 |
|------|------|
| screen_market | 按在线估值、市值筛选全市场股票 |
| screen_position | 覆盖率达标后按本地52周位置筛选 |
| get_data_coverage | 查看日K、技术指标、52周位置覆盖率 |
| sync_history_batch | 小批量补全历史日K和技术指标，支持断点续跑 |
| get_stock_list | 分页获取板块股票列表 |

## 使用示例

### Python API

```python
from stock_pool import StockDataPool

pool = StockDataPool()

# 获取实时行情
quote = pool.get_realtime_price('601138')

# 获取日K线
kline = pool.get_daily_data('601138', days=250)

# 分析52周位置
position = pool.analyze_position(['601138', '600487'])

# 市场筛选
result = pool.screen_market({
    'board': 'a_share',
    'pe_ttm_max': 20,      # PE上限20倍
    'market_cap_min': 100, # 总市值下限100亿
    'limit': 20,
})
```

### MCP调用示例

```json
// 获取当前时间
{"name": "get_current_time", "arguments": {}}

// 综合分析股票
{"name": "analyze_stock", "arguments": {"code": "601138"}}

// 市场筛选
{"name": "screen_market", "arguments": {
    "board": "a_share",
    "pe_ttm_max": 20,
    "market_cap_min": 100,
    "limit": 20
}}

// 查看历史数据覆盖率
{"name": "get_data_coverage", "arguments": {
    "board": "a_share",
    "min_daily_rows": 240
}}

// 小批量补历史数据；大量补全按 next_offset 续跑
{"name": "sync_history_batch", "arguments": {
    "board": "a_share",
    "max_codes": 20,
    "days": 250
}}
```

## Agent使用规则

1. **必须先调用 `get_current_time`**：确定分析截止日期和交易时段
2. **全市场估值/市值筛选用 `screen_market`**：并提供至少一个筛选条件；52周位置优先对候选股用 `analyze_position`
3. **个股分析用 `analyze_stock`**：一次调用获取完整分析
4. **小批量获取用 `get_latest_data`**：最多10只，大量由agent分批遍历
5. **全市场52周位置筛选先看 `get_data_coverage`**：覆盖率不足时用 `sync_history_batch` 小批量补全；在线股票列表不可用时不得把本地股票池当全市场

### 推荐流程

```
1. get_current_time     # 确定时间
2. screen_market        # 筛选候选
3. analyze_stock        # 逐只分析
```

## 文件结构

```
stock_pool/
├── mcp_server.py        # MCP服务器
├── mcp_tools.py         # MCP工具定义
├── stock_pool.py        # 核心功能类
├── provider_manager.py  # 数据源管理
├── storage.py           # 数据库存储
├── indicators.py        # 技术指标计算
├── errors.py            # 错误处理
├── providers/           # 数据源实现
│   ├── base.py          # 基类
│   ├── eastmoney.py     # 东方财富
│   ├── sina.py          # 新浪财经
│   ├── tencent.py       # 腾讯财经
│   ├── netease.py       # 网易财经
│   ├── akshare.py       # AkShare
│   ├── baostock.py      # Baostock
│   └── tushare.py       # TuShare Pro
└── README.md
```

## 配置

### TuShare Pro（可选）

```bash
export TUSHARE_TOKEN=your_token
```

### MCP配置

```json
{
  "mcpServers": {
    "stock-pool": {
      "command": "python",
      "args": ["mcp_server.py"],
      "cwd": "/path/to/stock_pool"
    }
  }
}
```

## 注意事项

1. API有调用限制，建议设置适当延迟
2. 52周位置依赖历史K线；不要用 `screen_market` 做全市场52周位置筛选，先筛候选再调用 `analyze_position`
3. TuShare为付费服务，需配置Token
4. 项目日志输出到stderr，不影响MCP通信
