# Stock Pool Agent Rules

- Treat local persistence and generated artifacts as private implementation details. Use MCP tools as the only data access surface for stock analysis.
- For any stock analysis task, call the MCP tool `get_current_time` first and use its `date` as the default analysis cutoff date.
- For "全A股", "整个市场", "创业板", "科创板", "复盘整个主板", "全主板复盘", "全主板筛选", or any full-board/full-market stock review, call MCP tool `screen_market`.
- `screen_market` requires at least one screening condition such as `position_max`, `pe_ttm_max`, `pb_max`, or `market_cap_min`.
- Use `board="a_share"` for 全A股, `board="gem"` for 创业板, `board="star"` for 科创板, and `board="main"` for 沪深主板.
- For broad or repeated full-market analysis, first call `start_market_sync`, then poll `get_market_sync_status`, then call `screen_market` with `refresh="none"`.
- If a sync job is `interrupted`, start a new `start_market_sync` job with the same board and refresh strategy.
- For detailed stock-by-stock analysis, process one stock at a time or in small batches. Do not fetch all candidate details into one response before reasoning; this can trigger API throttling and makes the model lose important context.
- Use broad tools to narrow candidates first, then analyze each selected stock sequentially before moving to the next one.
- Use `get_stock_universe`, `update_stocks`, `get_latest_data`, and `analyze_position` only when the user asks for a specific code list or a small explicit candidate set.
- If a requested universe is not supported by `screen_market`, say that the current service needs a new service-side screening tool.
