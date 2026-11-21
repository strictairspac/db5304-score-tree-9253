# 结构迁移

`src/models/tables.py` 定义当前关系结构，全新数据库由启动流程（`src/config/migrate.py` 的 `upgrade()`）直接按模型建表。

## 增量版本

- 初始快照：accounts、business_cases、business_runs、business_evidence、audit_events。
- 批次归并版本：新增 catalog_batches（目录批次登记）与 batch_conflicts（编号冲突明细）；business_runs 增加 attempt_count、batch_id；business_evidence 增加 inspection_passed、exportable 巡检闸门列。

`upgrade()` 幂等：列或表已存在时跳过；仅在闸门列首次加入旧库时把历史证据回填为可导出（旧版本证据均通过全部巡检）。应用启动与 `python -m scripts.seed_demo` 都会先执行迁移。
