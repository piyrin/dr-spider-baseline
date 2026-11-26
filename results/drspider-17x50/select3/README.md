# 每表最多三行样例的配对补测

## 论文设置

Dr.Spider 主表比较在 Spider 上训练的 Text-to-SQL 模型，附录 B 的 Codex-davinci 实验采用 Rajkumar 等的 `Create Table + Select 3`。其图 10 在各表的建表语句后放一个 SQL 注释。注释包含 `SELECT * FROM 表名 LIMIT 3`、列头和读到的实际行。最后附当前题目并让模型生成 SQL。官方数据仓库的流程先生成 Spider-dev 的预测，再复制到各扰动类的 pre 集中，post 各自生成并用 test-suite 评测。论文表 16 按扰动类别做宏平均。[论文附录 B](https://arxiv.org/html/2301.08881v2#A2) · [提示词图 10](https://arxiv.org/pdf/2204.00498#page=12) · [官方评测流程](https://github.com/awslabs/diagnostic-robustness-text-to-sql#to-evaluate-a-model)

## 本地对照

- 沿用 [17 类 × 50 对题单](../README.md) 的样本 ID、题目、参考 SQL 和 111 个 SQLite 文件。两侧各生成一次，使用 `gpt-6-sol`、相同的系统指令和课程 API 默认生成参数。服务未提供可核实的模型 digest。两批在不同日期运行。
- 每个题面读取当侧库。保持全部建表语句及其顺序，在每张表的 DDL 后附 SQLite `SELECT * … LIMIT 3` 的列头和实际行。没有 `ORDER BY`。以 JSON 数组逐行呈现，便于保留空值、空格和分隔符。写入运行配置前生成并记录各库提示词的 SHA-256。
- 继续使用同一单库执行评分器。相对鲁棒性按「两侧都通过 ÷ pre 通过」计算，另列按 17 类等权宏平均。跨提示的修复与回退在同一题面上统计。历史参考答案疑难题仍按原本的 EX 计分。

## 结果

| 指标 | 纯表结构 | 每表最多三行 | 变化 |
| --- | ---: | ---: | ---: |
| pre EX | 665/850（78.24%） | 643/850（75.65%） | −2.59 pp |
| post EX | 544/850（64.00%） | 553/850（65.06%） | +1.06 pp |
| 两侧合计 EX | 1,209/1,700（71.12%） | 1,196/1,700（70.35%） | −0.76 pp |
| 两侧均通过 | 531/850 | 532/850 | +1 对 |
| 相对鲁棒性（合并配对） | 531/665（79.85%） | 532/643（82.74%） | +2.89 pp |
| 相对鲁棒性（17 类等权） | 80.08% | 82.80% | +2.73 pp |
| 每题面输入 token 中位数 | 4,662 | 6,126 | +31.4% |

post 有 55 个题面由未通过变为通过，46 个由通过变为未通过。pre 对应为 32 和 54。原基线 134 对「前对后错」中，35 对的 post 改为通过，其中 32 对在新提示下两侧都通过。相对鲁棒性的增幅主要来自 pre 通过数减少，两侧都通过的数量仅增加 1 对。两批 API 都未返回系统指纹，结果保留单次历史对照的口径。[指标和运行配置](comparison.json)

| 扰动类别 | pre 原 → 新 | post 原 → 新 | post 修复 | post 回退 |
| --- | ---: | ---: | ---: | ---: |
| `DB_DBcontent_equivalence` | 44 → 41 | 30 → 33 | 7 | 4 |
| `DB_schema_abbreviation` | 41 → 36 | 38 → 35 | 1 | 4 |
| `DB_schema_synonym` | 36 → 37 | 33 → 35 | 4 | 2 |
| `NLQ_column_attribute` | 34 → 34 | 34 → 31 | 0 | 3 |
| `NLQ_column_carrier` | 45 → 44 | 31 → 34 | 3 | 0 |
| `NLQ_column_synonym` | 36 → 37 | 28 → 26 | 2 | 4 |
| `NLQ_column_value` | 46 → 38 | 36 → 32 | 4 | 8 |
| `NLQ_keyword_carrier` | 40 → 37 | 39 → 35 | 1 | 5 |
| `NLQ_keyword_synonym` | 34 → 32 | 30 → 29 | 1 | 2 |
| `NLQ_multitype` | 37 → 37 | 27 → 31 | 6 | 2 |
| `NLQ_others` | 39 → 34 | 33 → 31 | 1 | 3 |
| `NLQ_value_synonym` | 38 → 38 | 18 → 27 | 11 | 2 |
| `SQL_comparison` | 39 → 39 | 27 → 27 | 1 | 1 |
| `SQL_DB_number` | 42 → 46 | 43 → 45 | 3 | 1 |
| `SQL_DB_text` | 36 → 38 | 33 → 35 | 3 | 1 |
| `SQL_NonDB_number` | 40 → 36 | 32 → 32 | 4 | 4 |
| `SQL_sort_order` | 38 → 39 | 32 → 35 | 3 | 0 |

每个类别的 pre 和 post 分母各为 50。女学生养狗题 `DB_DBcontent_equivalence-00037-post` 在新提示里用了 `is_male = 'F'`，Volvo 题 `DB_schema_synonym-00410-post` 改用 `model_name = 'volvo'`，均通过。Robbin CV 题 `DB_schema_synonym-01010-post` 仍从关联表取描述。题意要求最近一次治疗的 `DB_DBcontent_equivalence-00364-post` 仍因参考 SQL 漏写日期降序而未通过 EX。

## 复现

```powershell
.\.venv\Scripts\python.exe -B -X utf8 scripts/run_full_evaluation.py --execute --run sol-drspider-50pergroup-select3-20261122 --pairs-per-group 50 --seed 20261121 --sample-rows 3 --workers 16
.\.venv\Scripts\python.exe -B -X utf8 scripts/compare_sample_rows_evaluation.py runs/sol-drspider-50pergroup-seed20261121 runs/sol-drspider-50pergroup-select3-20261122 results/drspider-17x50/select3
```

生成程序按运行名恢复，已保存在 `records/` 中的评分与 `responses/` 中的有效模型响应会复用。汇总核对题单和运行配置，并要求两组每个题面都有执行判分。
