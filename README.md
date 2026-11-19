# 任务1 · Dr.Spider 基线实验

使用 Thingo API 的 `gpt-6-sol`，在 Dr.Spider 的五类扰动上完成 **75 对、150 条 Text-to-SQL 预测**。50 对主批的单数据库执行一致率（EX）从 **72%（36/50）降至 66%（33/50）**。

[实验报告](reports/任务1实验报告.md) · [错误诊断](reports/问题记录.md) · [rsi-data 工程阅读](reports/rsi-data阅读记录.md)

## 仓库结构

```text
├── reports/                 实验报告、错误诊断、rsi-data 工程阅读
├── results/
│   ├── baseline/            两批样本标识、配置、预测 SQL、逐题评分与汇总
│   └── diagnostics/         SQL 单点复核与 JetBlue 问句对照
├── manifests/               Dr.Spider 数据版本、SHA-256 与规模盘点
├── scripts/                 数据准备、评测依赖下载、单题入口和配对批测
├── src/                     共用提示词和只读 SQLite 执行逻辑
├── .env.example             Thingo API 配置模板
└── requirements.txt         Python 依赖
```

## 测试数据与评测

固定版本的 Dr.Spider 数据包包含 17 类扰动、15,269 对样本，基于 Spider-dev 的 1,034 道原题。同一道原题可出现在多个扰动类别中。本实验抽取表结构同义改名、表结构缩写、问题关键词改写、问题列名同义表达和排序方向改变五类。每对包含扰动前（pre）和扰动后（post）两个问题侧。两批在 `(类别, 下标)` 上无重叠。[数据版本](manifests/data_source.json) · [规模盘点](manifests/data_inventory.json)

模型根据问题和 SQLite 建表语句生成一条查询。在每题对应的单个数据库上执行预测与标准 SQL，以执行结果一致的比例计算 EX。数据库扰动的 post 侧使用扰动后的数据库。评测实现固定到上游提交 `e97acc5`。[评测实现](https://github.com/taoyds/test-suite-sql-eval/tree/e97acc546ecbee8fa27fa8dbf025ef61493a876c)

## 实验结果

| 批次 | 种子 | 配对数 | 前 EX | 后 EX | 变化 |
| --- | ---: | ---: | ---: | ---: | ---: |
| [首批](results/baseline/sol-25pairs.json) | 42 | 25 | 88%（22/25） | 88%（22/25） | 0 个百分点 |
| [主批](results/baseline/sol-50pairs-seed43.json) | 43 | 50 | 72%（36/50） | 66%（33/50） | −6 个百分点 |

- 主批中，问题列名同义表达的 EX 下降幅度最大，由 6/10 降至 3/10。首批和主批的排序类变化方向不同。
- 主批 31 条执行结果不一致，以关联或候选集合差异最多（11/31）。七条代表预测经 SQL 单点修改后，结果均与标准一致。[SQL 复核](results/diagnostics/sql-diagnostics.json)
- JetBlue 对照保持模型、表结构和参数一致。原问句复测得到 0，把问句中的航司名改为库内大小写后得到 100，与标准结果一致。每种条件新增一次请求。[模型对照](results/diagnostics/jetblue-model-control.json)

## 复现命令

环境为 Git、Python 3.13 和 PowerShell。以下命令从仓库根目录执行。

```powershell
python -m venv .venv
$py = '.\.venv\Scripts\python.exe'
& $py -m pip install -r requirements.txt
& $py -B -X utf8 scripts/prepare_data.py
& $py -B -X utf8 scripts/setup_evaluator.py
```

使用 [.env.example](.env.example) 创建本地 `.env` 并填写 `THINGO_API_KEY`。以下两条批测命令分别发出 50 和 100 次生成请求，输出计划、逐题记录及汇总到本地 `runs/`。

```powershell
& $py -B -X utf8 scripts/run_api_batch.py --run reproduce-25-seed42 --model gpt-6-sol --pairs-per-group 5 --seed 42 --execute
& $py -B -X utf8 scripts/run_api_batch.py --run reproduce-50-seed43 --model gpt-6-sol --pairs-per-group 10 --seed 43 --execute
```

省略 `--execute` 可离线生成抽样计划并执行全部标准 SQL。运行名已存在时，同一配置会复用已有记录。服务端采用默认生成参数，远程模型 digest 未提供，复跑时预测可能变化。
