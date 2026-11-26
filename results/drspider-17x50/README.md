# Dr.Spider 17 类配对实验

正式模型实验在固定发布版本的 17 类扰动中各随机抽 50 对，种子为 `20261121`。每对的 pre 和 post 各生成一次，使用 `gpt-6-sol`，共 1,700 条。全量参考 SQL 执行检查覆盖 30,538 个问题侧。正式的抽样结果与全量参考检查分别记录。

基线的 850 个配对状态为 **531 双通过、134 前对后错、13 前错后对、172 双未通过**。主分析聚焦前对后错的 134 对，剔除 38 对参考 SQL 错误和 9 对题意或判分争议，人工分类计入 87 对。完整类别与扩样口径见[主报告](../../reports/任务1实验报告.md#134-对前对后错的人工复核)。

| 文件 | 内容 |
| --- | --- |
| [summary.json](summary.json) | 每类执行评分、配对变化、错误复核计数和运行版本 |
| [predictions.csv](predictions.csv) | 正式批次全部样本、参考 SQL、预测 SQL 和执行状态 |
| [prepass-postfail-review.csv](prepass-postfail-review.csv) | 134 对前对后错的处理判定、主要类别、原备注与配对 ID |
| [combined-category-counts.csv](combined-category-counts.csv) | 12 类的主批、扩样、合计和扩样题意待定数 |
| [独立与定向扩样](expansion/README.md) | 原题与主批隔离的纯表结构补充基线及逐对诊断 |
| [review_cases.json](review_cases.json) | 从未通过侧分层抽取的题目、SQL、语义判定及证据 |
| [diagnostic_examples.json](diagnostic_examples.json) | 三个定向核查案例及同库执行证据 |
| [reference_audit.json](reference_audit.json) | 全量参考查询的可执行性与空结果统计 |
| [表数分层](diagnostics/table-count-summary.json) | 按 SQL 引用表数统计配对结果，附各扰动类别的分层明细 |
| [每表最多三行样例补测](select3/README.md) | 同一份 850 对题单上，比较纯表结构与附样例行提示的逐题判分、相对鲁棒性和输入 token |

## 复现

在仓库根目录按 [README](../../README.md) 准备 SQLite 数据、评测依赖与课程 API。以下命令运行全量离线参考检查和 17 类各 50 对的正式抽样。重复模型调用会消耗课程 API 配额。运行中断时用原命令恢复，已有预测响应及评分会保留。数据、执行脚本或实验配置发生变化时使用新运行名。

```powershell
.\.venv\Scripts\python.exe -B -X utf8 scripts/run_full_evaluation.py --audit --run drspider-reference-audit
.\.venv\Scripts\python.exe -B -X utf8 scripts/run_full_evaluation.py --execute --run sol-drspider-50pergroup-seed20261121 --pairs-per-group 50 --seed 20261121 --workers 16
Copy-Item runs/drspider-reference-audit/reference_audit.json results/drspider-17x50/reference_audit.json
.\.venv\Scripts\python.exe -B -X utf8 scripts/summarize_full_evaluation.py runs/sol-drspider-50pergroup-seed20261121 results/drspider-17x50 --annotations results/drspider-17x50/review_cases.json
```

语义复核在每个「扰动类别 × pre/post」层内，对评分未通过的样本按种子与样本 ID 的 SHA-256 排序，取至多两条，共 68 条。标签分布以这 68 条为分母。后续 491 条工作备注覆盖了全部执行未通过预测，可用于逐题检查。若重新生成后预测或复核样本变化，需对新复核样本重新判定。
