# 股票数据池

股票数据缓存和分析服务，支持MCP协议。

## 功能

- 使用内部缓存减少重复API调用
- 覆盖基本信息、日K线、估值、财务、资金流向、技术指标、分钟K线等数据能力
- 自动检查数据完整性，只拉取缺失数据
- 实时行情工具直接调用外部API，不使用服务缓存
- 提供当前时间工具，便于AI Agent确定数据分析截止日期与A股交易时段
- 当日/最新数据查询会在内部缓存基础上自动补充实时行情，降低盘中或收盘后当日数据滞后风险
- 提供 `screen_market` 在服务端执行全A股、创业板、科创板、主板筛选，支持条件过滤、分页、受控刷新和少量实时补价
- 提供 `start_market_sync` 后台同步任务，分批、限速、按缓存缺口维护全市场数据
- 提供 `get_stock_universe` 从外部行情接口获取候选股票列表，供小范围候选分析使用
- 支持52周滚动位置分析、估值分析
- 支持常用技术指标：MA、EMA、MACD、RSI、KDJ、BOLL、ATR、OBV
- 提供MCP服务器，支持AI模型直接调用
- 除 `screen_market` 外，当前 MCP 工具以“给定股票代码/代码列表”为输入，不自动枚举与筛选全市场
- **多API源降级机制**
- 查询参数强制校验，降低异常输入风险
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

## Agent 使用边界

Agent 只应通过 MCP 工具获取和分析股票数据。全A股、创业板、科创板、主板复盘或筛选必须调用 `screen_market`，并提供至少一个筛选条件，例如 `position_max`、`pe_ttm_max`、`pb_max` 或 `market_cap_min`。`get_stock_universe` 只用于小范围候选列表任务，不应由 Agent 自行循环处理全量候选。

详细个股分析建议采用“先筛选、后逐只分析”的节奏：先用 `screen_market` 缩小候选，再对候选股票逐只或小批次调用详情工具并完成分析后再进入下一只。不要一次性拉取全量候选的全部详情再统一分析，这会显著增加耗时、触发外部接口限流/风控，并挤占上下文导致关键信息丢失。

小批量工具有单次上限：`get_latest_data` 最多 30 只，`get_realtime_prices` 最多 20 只，`update_stocks` 最多 50 只，`analyze_position` 最多 100 只，`check_missing_data` 最多 200 只。超过这些规模时应使用 `screen_market` 缩小候选，或使用 `start_market_sync` 做后台维护。

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

### 市场筛选

```python
result = pool.screen_market({
    'board': 'a_share',
    'position_max': 30,
    'pe_ttm_max': 20,
    'limit': 50,
    'include_realtime': False,
})
```

`screen_market` 必须提供至少一个筛选条件。默认只使用服务缓存快照，避免全量实时请求；需要刷新数据时使用 `refresh='missing'` 或 `refresh='stale'`。已有足够历史数据时，刷新会按最近缺口增量拉取；选择刷新策略后默认最多刷新 200 只，也可用 `max_refresh` 收紧本次刷新数量。

面向全市场的推荐流程：

```python
# 1. 后台维护缓存，可重复执行；已有足够历史时只补近期缺口
sync = pool.sync_market(board='a_share', refresh='stale', days=250, delay=0.2)

# 2. 用户筛选时直接读快照，避免临时全量刷新
result = pool.screen_market({
    'board': 'a_share',
    'position_max': 30,
    'pe_ttm_max': 20,
    'refresh': 'none',
    'limit': 50,
})
```

常用 `board`：

| board | 范围 |
|------|------|
| `a_share` | 全A股 |
| `main` | 沪深主板 |
| `gem` | 创业板 |
| `star` | 科创板 |
| `hs_a` | 沪深A股 |
| `bse` | 北交所 |

### MCP服务器

启动MCP服务器：

```bash
python mcp_server.py
```

配置文件：`mcp_config.json`

#### 能力边界

- `screen_market`：服务端受控执行全A股、创业板、科创板、主板筛选；默认不拉实时行情，支持筛选条件、分页返回、受控刷新。
- `screen_main_board`：兼容入口，等价于 `screen_market(board="main")`。
- `start_market_sync` / `get_market_sync_status` / `cancel_market_sync`：后台维护全市场/板块缓存，用于为后续筛选准备完整快照。
- 同步任务状态可通过 `get_market_sync_status` 查询；服务重启后未完成任务会标记为 `interrupted`，可重新启动同步继续补齐。
- `get_stock_universe`：从外部行情接口获取候选股票代码列表，适用于小范围候选分析，不作为全市场/板块筛选的主入口。
- `update_stock` / `update_stocks` / `update_minute_data`：按用户或 Agent 提供的股票代码更新服务缓存，必要时从外部 API 拉取数据。
- `get_daily_data` / `get_valuation_data` / `get_technical_data` / `get_latest_data` / `analyze_position` / `analyze_intraday`：面向调用方表现为获取/分析股票数据；服务内部会优先使用缓存，避免重复 API 调用。
- `get_realtime_price` / `get_realtime_prices`：按给定股票代码直连外部 API 获取实时行情，不使用服务缓存，但也不负责发现股票代码。
- 全市场/板块筛选必须走 `screen_market`。其他工具只处理用户或 Agent 已明确给出的股票代码列表。

#### MCP工具列表

> Agent 使用规则：每次股票分析任务开始前必须先调用 `get_current_time`，以返回的 `date` 作为默认分析截止日期，并结合 `is_trading_time` / `trading_session` 判断是否正在交易、是否需要关注实时行情。
> 全市场/板块筛选规则：必须调用 `screen_market`，且必须提供至少一个筛选条件。不要自行循环全量候选代码。
> 个股深度分析规则：筛选后逐只或小批次分析，完成一只再进入下一只；不要一次性读取所有候选详情。

`get_current_time` 返回字段包括：

- `datetime` / `date` / `time`：北京时间（Asia/Shanghai）
- `timestamp`：Unix 时间戳
- `is_trading_day`：是否为工作日交易日（不含节假日日历判断）
- `is_trading_time`：是否处于 A 股连续竞价交易时段（09:30-11:30 或 13:00-15:00）
- `trading_session`：`pre_market`、`morning_trading`、`lunch_break`、`afternoon_trading`、`after_market`、`non_trading_day`

当 `get_daily_data` 的查询范围包含当前日期，或调用 `get_latest_data` 获取最新综合数据时，服务会尝试直连实时行情 API 补充：

- `realtime_used`：是否成功使用实时行情
- `realtime_price`：实时价格
- `effective_close`：分析推荐优先使用的有效价格（实时价优先，否则缓存收盘价）
- `effective_price_source`：`realtime` 或 `cache`
- `time_context`：本次数据对应的当前时间与交易时段上下文

| 工具 | 说明 |
|------|------|
| get_current_time | 强制前置工具；获取当前北京时间、交易日/交易时段状态，用于确定分析截止日期 |
| screen_market | 服务端执行全A股、创业板、科创板、主板筛选；支持条件过滤、分页、受控刷新，默认不拉实时行情 |
| screen_main_board | 主板筛选兼容入口 |
| start_market_sync | 启动后台市场同步任务，分批、限速、按缓存缺口补齐数据 |
| get_market_sync_status | 查询后台市场同步任务状态 |
| cancel_market_sync | 请求取消正在运行的后台市场同步任务 |
| get_stock_universe | 从外部行情接口获取候选股票列表，供小范围候选分析使用 |
| update_stock | 按给定代码更新单只股票服务缓存，不自动枚举全市场 |
| update_stocks | 按给定代码列表批量更新股票服务缓存，不自动枚举全市场 |
| get_stock_info | 获取股票基本信息，服务优先使用缓存 |
| get_daily_data | 获取日K线；若查询范围涉及今天，会在缓存基础上自动补充实时行情 |
| get_valuation_data | 获取估值数据，服务优先使用缓存 |
| get_technical_data | 获取技术指标，服务优先使用缓存 |
| get_latest_data | 批量获取给定代码列表的最新数据；仅适合小批量候选详情读取，大量代码建议关闭实时补价 |
| get_realtime_price | 实时获取单只股票当前价格，直连外部API，不使用服务缓存 |
| get_realtime_prices | 批量实时获取股票当前价格，直连外部API，不使用服务缓存 |
| analyze_position | 基于给定代码列表的可用历史数据分析52周位置，不是全市场筛选器 |
| check_missing_data | 检查给定代码列表在服务缓存中的缺失数据 |
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
└── README.md         # 文档
```

## 注意事项

1. API有调用限制，建议设置延迟1.5-2秒
2. MCP服务器需要Python 3.7+
3. API降级机制自动处理超时和限流
4. 财务/资金流向拉取仍需后续实现
5. 腾讯/网易当前主要用于实时行情备用，尚未实现完整K线历史数据解析
