# MarketCell 存储层设计 v0.1

## 1. 目标

MarketCell 的存储层要解决三件事：

- 行情数据可以重复读取，不依赖外部 API 临时状态。
- 历史分析和回放可以快速筛选时间窗口。
- Rust 热路径和 Python 冷路径通过稳定文件契约交接。

当前阶段先提供轻量基础，不把系统提前绑死在某个数据库或云服务上。

## 2. 当前代码落点

```text
packages/python/src/market_cell/data/
├── cache.py      # JSON 文件缓存，适合开发、测试和低频请求
├── storage.py    # Parquet/DuckDB 存储适配基础
├── sources.py    # CandleSource 协议和 MarketDataRouter
└── quality.py    # K 线质量检查
```

`storage.py` 当前提供：

- `CandleRow`：和 `contracts/parquet/candle_schema.md` 对齐的行结构。
- `batch_to_candle_rows`：把 `CandleBatch` 转成批量存储行。
- `partition_path`：生成稳定分区路径。
- `ParquetCandleStore`：可选 `pyarrow` 写入 Parquet。
- `DuckDBCandleSource`：可选 `duckdb` 读取本地 Parquet 并返回 `CandleBatch`。

## 3. 依赖策略

基础测试不强制安装 Parquet/DuckDB 依赖。

原因：

- CI 必须轻、稳、快。
- Cell、契约、回放不能因为本地没有重依赖而失败。
- 生产环境或研究环境需要时再安装存储扩展。

安装方式：

```bash
python3 -m pip install -e 'packages/python[storage]'
```

如果没有安装可选依赖，相关适配器会抛出 `OptionalStorageDependencyError`，错误信息会明确提示缺少哪个包。

## 4. 分区策略

Parquet 分区路径遵守：

```text
provider=<source_provider>/
exchange=<exchange>/
market_type=<market_type>/
symbol=<symbol>/
interval=<interval>/
date=<YYYY-MM-DD>/
```

这个结构优先服务：

- 单品种、多周期读取
- 多交易所交叉校验
- 回放窗口选择
- 后续 DuckDB 本地研究查询

## 5. 边界原则

- Cell 不直接读 Parquet。
- AnalysisEngine 不直接依赖 DuckDB。
- 数据源适配器输出 `CandleBatch`，再进入 `AnalysisRequest`。
- 存储层可以缓存和查询行情，但不能生成决策解释。
- Rust 后续可以写入同一 Parquet 契约，Python 负责读取和静态分析。

## 6. 当前未完成

当前只是存储层基础，不等于生产级行情仓库。

后续还需要：

- 批量写入去重和 upsert 策略。
- 数据修复版本记录。
- 跨源价差和缺口监控。
- 数据源质量问题 Parquet 化。
- Provider 健康趋势的长期存储和查询优化。
- DuckDB 查询窗口、分页和多条件过滤。
- FeatureSnapshot 的 Parquet 化。
- 大规模压缩、分区合并和生命周期管理。
