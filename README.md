# Dr.Spider 与 RSI Data

本阶段我在 Dr.Spider 上完成了 SQL 生成基线，逐对复核了 134 对扰动前通过、扰动后失败的样本。我从中选择 10 个问题，先比较加入先验知识前后的结果，再在 RSI Data 课程 Visual 中测试人工编排。

| 任务 | 提交内容 | 验收入口 |
| --- | --- | --- |
| 1 · Dr.Spider 基线 | 使用 `gpt-6-sol` 完成 **850 对、1,700 条预测**。执行准确率从 **78.24%（665/850）降至 64.00%（544/850）**。 | [基线实验报告](reports/任务1实验报告.md) · [134 对人工复核 Excel](results/drspider-17x50/Dr.Spider-850对基线与鲁棒性问题复核（汇报版）.xlsx) |
| 1 · 扩样与辅助对照 | 扩样和定向补测共 **344 对**。另完成三行样例对照与表数分层分析。 | [扩样结果](results/drspider-17x50/expansion/README.md) · [三行样例对照](results/drspider-17x50/select3/README.md) · [表数分层](results/drspider-17x50/diagnostics/table-count-summary.json) |
| 2 · Dr.Spider 人工编排 | 十题均有先验对照和课程画布记录。按验收索引中的预设，扰动后原题通过 **9/10**，其中第 7 题采用 v2 原题预设。 | [人工编排报告](reports/任务2先验知识与人工编排实验.md) · [画布与验收证据](results/task2/submission/README.md) · [编排源码](task2-rsi-data/experiment/README.md) |
| 2 · RSI Data 启动验收 | 课程 Spring Boot 经流程引擎运行单表 Agent 和多 Agent 协作，在 Dr.Spider SQLite 上核对结果。 | [课程执行验收记录](results/task2/course-acceptance-20261120.json) |

## 目录与产物

```text
├── reports/                 实验报告与错误诊断
├── results/
│   ├── baseline/            两批样本标识、配置、预测 SQL、逐题评分与汇总
│   ├── diagnostics/         SQL 单点复核与 JetBlue 问句对照
│   ├── drspider-17x50/       17 类配对实验、参考检查及后续诊断
│   └── task2/               课程流程复测、十题画布截图和验收证据
├── task2-rsi-data/           任务 2 流程、Agent 节点、演示页面和启动脚本
├── manifests/               Dr.Spider 数据版本、SHA-256 与规模盘点
├── scripts/                 数据准备、评测依赖下载、单题入口和配对批测
├── src/                     共用提示词和只读 SQLite 执行逻辑
├── .env.example             Thingo API 配置模板
└── requirements.txt         Python 依赖
```

## 人工复核附件

我将 134 对前对后错样本的逐对判断、分类依据和备注整理在[人工复核 Excel 工作簿](results/drspider-17x50/Dr.Spider-850对基线与鲁棒性问题复核（汇报版）.xlsx)中，作为本次汇报的附件。老师可以结合[实验报告](reports/任务1实验报告.md)和[逐对判定 CSV](results/drspider-17x50/prepass-postfail-review.csv)核对结果。

## Dr.Spider 基线

### 测试数据与评测

固定版本的 Dr.Spider 数据包包含 17 类扰动、15,269 对样本，基于 Spider-dev 的 1,034 道原题。主实验由 17 类各抽 50 对组成，每对包含扰动前（pre）和扰动后（post）两个问题侧。同一道原题可以出现在多个扰动类别中。[数据版本](manifests/data_source.json) · [规模盘点](manifests/data_inventory.json)

模型根据问题和 SQLite 建表语句生成一条查询。在每题对应的单个数据库上执行预测与标准 SQL，以执行结果一致的比例计算 EX。数据库扰动的 post 侧使用扰动后的数据库。评测实现固定到上游提交 `e97acc5`。[评测实现](https://github.com/taoyds/test-suite-sql-eval/tree/e97acc546ecbee8fa27fa8dbf025ef61493a876c)

### 主实验结果

850 对主批中，**前后都通过 531 对、前对后错 134 对、前错后对 13 对、前后都未通过 172 对**。134 对人工复核后，排除 38 对参考 SQL 错误和 9 对题意或判分争议，87 对进入修复研究。主批最常见的差异是返回内容多选（27 对）和筛选值与库内存法不符（26 对）。扩样明确候选与主批按类别合并统计。[主报告](reports/任务1实验报告.md#134-对前对后错的人工复核) · [合并统计](results/drspider-17x50/combined-category-counts.csv)

### 早期试跑与诊断

早期试跑覆盖五种扰动，共 75 对。

| 批次 | 种子 | 配对数 | 前 EX | 后 EX | 变化 |
| --- | ---: | ---: | ---: | ---: | ---: |
| [首批](results/baseline/sol-25pairs.json) | 42 | 25 | 88%（22/25） | 88%（22/25） | 0 个百分点 |
| [主批](results/baseline/sol-50pairs-seed43.json) | 43 | 50 | 72%（36/50） | 66%（33/50） | −6 个百分点 |

- 主批中，问题列名同义表达的 EX 下降幅度最大，由 6/10 降至 3/10。首批和主批的排序类变化方向不同。
- 主批 31 条执行结果不一致，以关联或候选集合差异最多（11/31）。七条代表预测经 SQL 单点修改后，结果均与标准一致。[SQL 复核](results/diagnostics/sql-diagnostics.json)
- JetBlue 对照保持模型、表结构和参数一致。原问句复测得到 0，把问句中的航司名改为库内大小写后得到 100，与标准结果一致。每种条件新增一次请求。[模型对照](results/diagnostics/jetblue-model-control.json)

## RSI Data 先验知识与人工编排

我先比较同一题面和模型在有无人工先验时的结果。配对复测中，扰动后通过从 **1/10 提升到 10/10**，扰动前有 1 题回退，双侧同时通过从 **1/10 提升到 9/10**。

随后我在课程 Visual 按问题类型设计节点和分支。第 1、4–9 题的版本改动、复测结果和适用范围列在报告末尾。第 3 题默认画布的扰动后输入仍未通过，同源 high 档批测通过。第 7 题通用 v3 的原题 post 仍未通过。第 9 题 v2 的画布通过 post，pre 仍多返回车型 `hi`。同类与混合题单用于开发回归，独立泛化仍待验证。[版本迭代汇总](reports/任务2先验知识与人工编排实验.md#版本迭代汇总) · [十题原题验收索引](results/task2/submission/十题原题验收索引.json)
