# 数据盘点、抽样审核与清洗差异

## 完整运行

```bat
scripts\governance.cmd audit data\raw --sample-size 50 --seed 2026
```

每次运行写入 `data/reports/<run_id>/`，包括：

- `inventory/inventory_summary.json`：文件总数、格式、来源、长度区间、分位数、重复和失败统计。
- `inventory/inventory_records.csv`：逐文件盘点明细，可直接用 Excel 查看。
- `review/review_sheet.csv`：人工审核表。
- `review/review_instructions.md`：审核字段说明。
- `cleaning_diff/samples/<sample_id>/before.md`：清洗前文本。
- `cleaning_diff/samples/<sample_id>/after.md`：清洗后文本。
- `cleaning_diff/samples/<sample_id>/cleaning.diff`：Unified Diff。
- `cleaning_diff/samples/<sample_id>/cleaning_diff.html`：可视化差异。
- `cleaning_diff/cleaning_diff_summary.json`：规则命中、删除比例和审核汇总。
- `overview.md`：本轮治理总览。
- `run_manifest.json`：运行参数与全部工件路径。

## 分层抽样

抽样分层同时考虑：

- 一级来源目录。
- 文件格式。
- 文档长度区间。
- 解析状态。
- 是否重复文件。

相同 `seed` 和相同数据集会得到相同样本，便于回归对比。

## 人工审核

打开 `review/review_sheet.csv`，填写：

- `review_status`：`approved`、`needs_rule`、`false_positive`、`parse_failed`。
- `quality_score`：1–5分。
- `noise_patterns`：残留噪音。
- `false_positive_rules`：疑似误删规则。
- `suggested_rules`：建议新增规则。
- `reviewer`、`reviewed_at` 和 `notes`。

导入审核结果：

```bat
scripts\governance.cmd import-review <run_id> data\reports\<run_id>\review\review_sheet.csv
```

导入后会重新生成清洗汇总，并产生 `review_summary.json`。

## 多轮比较

```bat
scripts\governance.cmd compare <baseline_run_id> <current_run_id>
```

比较报告用于观察：

- 解析失败是否下降。
- 重复文档是否减少。
- 高删除比例警告是否增加。
- 未命中规则样本是否减少。
- 审核通过率和质量评分是否提升。
- 误删和残留噪音是否收敛。

## API

- `POST /api/v1/governance/audits`
- `GET /api/v1/governance/audits`
- `GET /api/v1/governance/audits/{run_id}`
- `POST /api/v1/governance/audits/{run_id}/reviews`
- `POST /api/v1/governance/comparisons`