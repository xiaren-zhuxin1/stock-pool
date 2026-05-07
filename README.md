# 股票数据池

股票数据缓存和分析服务，支持MCP协议。

## 功能

- 使用内部缓存减少重复API调用
- 多表设计：基本信息、日K线、估值、财务、资金流向、技术指标、分钟K线
- 自动检查数据完整性，只拉取缺失数据
- 实时行情工具直接调用外部API，不使用服务缓存
- 提供当前时间工具，便于AI Agent确定数据分析截止日期
- 支持52周滚动位置分析、估值分析
- 支持常用技术指标：MA、EMA、MACD、RSI、KDJ、BOLL、ATR、OBV
- 提供MCP服务器，支持AI模型直接调用
- 当前 MCP 工具以“给定股票代码/代码列表”为输入，不提供全市场或全主板自动枚举与筛选能力
- **多API源降级机制**
- 查询 LIMIT 参数强制校验，降低 SQL 拼接风险
- 项目日志默认输出到 stderr，避免污染 MCP JSON-RPC stdout 通道

## API降级机制

### 支持的API源

| API | 说明 | 优先级 |
|-----|------|--------|
| 东方财富 | 数据最全，K线+估值 | 1 |
| 新浪财经 | 备用，实时行情 | 2 |
| 腾讯财经 | 实时行情备用 | 3 |
| 网易财经 | 实时行情备用 | 4 |

### 降级逻辑

```
1. 优先使用东方财富API
2. 日K线当前主要在东方财富和新浪之间降级
3. 实时行情/估值在东方财富、腾讯、新浪、网易之间降级
4. 分钟K线当前主要使用东方财富
5. 每个API连续失败3次后，暂时标记为不可用
6. 所有API不可用时，重置状态重新尝试
```

### 错误处理

| 错误类型 | 处理方式 |
|----------|----------|
| 超时 | 重试3次，间隔递增 |
| 连接错误 | 重试3次 |
| 429限流 | 立即切换API |
| 数据异常 | 切换API |

## 内部缓存设计

> 说明：SQLite 只是服务内部缓存实现，用于减少外部 API 调用和加速重复分析；对 Agent 暴露的是“股票数据服务”能力，而不是数据库操作能力。

### 表结构

| 表名 | 说明 | 主键 |
|------|------|------|
| stock_info | 股票基本信息 | code |
| stock_daily | 日K线数据 | code + data_date |
| stock_valuation | 估值指标 | code + data_date |
| stock_finance | 财务数据 | code + report_date |
| stock_fund_flow | 资金流向 | code + data_date |
| stock_technical | 技术指标 | code + data_date |
| stock_minute | 分钟K线 | code + data_time + klt |

### 字段说明

#### stock_info
| 字段 | 类型 | 说明 |
|------|------|------|
| code | TEXT | 股票代码 |
| name | TEXT | 股票名称 |
| market | TEXT | 市场（SH/SZ） |
| sector | TEXT | 板块 |
| industry | TEXT | 行业 |

#### stock_daily
| 字段 | 类型 | 说明 |
|------|------|------|
| code | TEXT | 股票代码 |
| data_date | TEXT | 日期 |
| open | REAL | 开盘价 |
| high | REAL | 最高价 |
| low | REAL | 最低价 |
| close | REAL | 收盘价 |
| volume | REAL | 成交量 |
| amount | REAL | 成交额 |

#### stock_valuation
| 字段 | 类型 | 说明 |
|------|------|------|
| code | TEXT | 股票代码 |
| data_date | TEXT | 日期 |
| pe_ttm | REAL | 市盈率TTM |
| pe_lyr | REAL | 市盈率LYR |
| pb | REAL | 市净率 |
| market_cap | REAL | 总市值 |

#### stock_technical
| 字段 | 类型 | 说明 |
|------|------|------|
| code | TEXT | 股票代码 |
| data_date | TEXT | 日期 |
| ma5/ma10/ma20/ma60 | REAL | 均线 |
| ema12/ema26 | REAL | EMA |
| macd/macd_signal/macd_hist | REAL | MACD/DIF、DEA、柱线 |
| rsi_6/rsi_12/rsi_24 | REAL | RSI |
| kdj_k/kdj_d/kdj_j | REAL | KDJ |
| boll_upper/boll_mid/boll_lower | REAL | BOLL |
| atr | REAL | 平均真实波幅 |
| obv | REAL | 能量潮 |
| high_52w | REAL | 52周最高 |
| low_52w | REAL | 52周最低 |
| position_pct | REAL | 滚动52周位置百分比 |

## 使用方式

### Python API

```python
from stock_pool import StockDataPool

pool = StockDataPool()

# 更新数据
pool.update_stocks(['601138', '600487'], days=250)

# 获取最新数据（服务优先使用缓存）
data = pool.get_latest_data(['601138', '600487'])

# 分析位置
result = pool.analyze_position(['601138', '600487'])

# 查看API状态
status = pool.get_api_status()
```

### MCP服务器

启动MCP服务器：

```bash
python mcp_server.py
```

配置文件：`mcp_config.json`

#### 能力边界

- `update_stock` / `update_stocks` / `update_minute_data`：按用户或 Agent 提供的股票代码更新服务缓存，必要时从外部 API 拉取数据。
- `get_daily_data` / `get_valuation_data` / `get_technical_data` / `get_latest_data` / `analyze_position` / `analyze_intraday`：面向调用方表现为获取/分析股票数据；服务内部会优先使用缓存，避免重复 API 调用。
- `get_realtime_price` / `get_realtime_prices`：按给定股票代码直连外部 API 获取实时行情，不使用服务缓存，但也不负责发现股票代码。
- 当前服务**不是全市场/全主板选股器**：如果要“在整个主板找股票”，需要先提供候选股票代码列表，或后续新增“获取主板股票列表/全市场股票池”的工具，再配合批量更新与分析工具使用。

#### MCP工具列表

| 工具 | 说明 |
|------|------|
| get_current_time | 获取当前北京时间（Asia/Shanghai），用于确定分析截止日期 |
| update_stock | 按给定代码更新单只股票服务缓存，不自动枚举全市场 |
| update_stocks | 按给定代码列表批量更新股票服务缓存，不自动枚举全市场 |
| get_stock_info | 获取股票基本信息，服务优先使用缓存 |
| get_daily_data | 获取日K线，服务优先使用缓存 |
| get_valuation_data | 获取估值数据，服务优先使用缓存 |
| get_technical_data | 获取技术指标，服务优先使用缓存 |
| get_latest_data | 获取给定代码列表的最新数据，服务优先使用缓存 |
| get_realtime_price | 实时获取单只股票当前价格，直连外部API，不使用服务缓存 |
| get_realtime_prices | 批量实时获取股票当前价格，直连外部API，不使用服务缓存 |
| analyze_position | 基于给定代码列表的可用历史数据分析52周位置，不是全市场筛选器 |
| check_missing_data | 检查给定代码列表在服务缓存中的缺失数据 |
| get_cache_stats | 获取服务内部缓存统计 |
| update_minute_data | 按给定代码更新分钟K线缓存 |
| get_minute_data | 获取分钟K线，服务优先使用缓存 |
| analyze_intraday | 基于可用日K、技术指标和分钟K线做日内走势分析 |

## 分析逻辑

### 52周位置

```
position_pct = (当前价 - 52周最低) / (52周最高 - 52周最低) * 100
```

当前实现使用每个交易日向前最多250个交易日的滚动窗口，避免历史指标使用未来高低点。

| 位置 | 百分比 | 风险 |
|------|--------|------|
| 低位 | < 30% | 低 |
| 中位 | 30-70% | 中 |
| 中高位 | 70-90% | 中高 |
| 高位 | >= 90% | 高 |

## 文件说明

```
stock_pool/
├── __init__.py       # 模块入口
├── stock_pool.py     # 核心代码
├── api_provider.py   # API提供者（降级机制）
├── mcp_server.py     # MCP服务器
├── mcp_config.json   # MCP配置
├── stock_pool.db     # 内部缓存文件
└── README.md         # 文档
```

## 注意事项

1. API有调用限制，建议设置延迟1.5-2秒
2. 内部缓存文件会随时间增长
3. MCP服务器需要Python 3.7+
4. API降级机制自动处理超时和限流
5. `stock_finance` 和 `stock_fund_flow` 表结构已保留，但财务/资金流向拉取仍需后续实现
6. 腾讯/网易当前主要用于实时行情备用，尚未实现完整K线历史数据解析
