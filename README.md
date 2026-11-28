# Dr.Spider 与 RSI Data

## 课程十题验收

课程验收使用 Dr.Spider 的十道原题。历史基线 `pre` 通过 10/10、`post` 通过 0/10。课程默认「运行」入口统一使用 Thinking `high` 实测，`pre` 和 `post` 各通过 **10/10**。逐题材料包括人工调整后的前端画布 JSON、Spring Boot 编排 JSON、运行结果和原因说明。[十题验收明细](results/task2/submission/acceptance/README.md) · [十题提交包](results/task2/submission/课程十题验收.zip)

## 项目与扩展实验

本阶段我在 Dr.Spider 上完成了 SQL 生成基线，逐对复核了 134 对扰动前通过、扰动后失败的样本。我从中选择 10 个问题，先比较加入先验知识前后的结果，再在画布中测试人工编排。

| 任务 | 提交内容 | 验收入口 |
| --- | --- | --- |
| 1 · Dr.Spider 基线 | 使用 `gpt-6-sol` 完成 **850 对、1,700 条预测**。执行准确率从 **78.24%（665/850）降至 64.00%（544/850）**。 | [基线实验报告](reports/任务1实验报告.md) · [134 对人工复核 Excel](results/drspider-17x50/Dr.Spider-850对基线与鲁棒性问题复核（汇报版）.xlsx) |
| 1 · 扩样与辅助对照 | 扩样和定向补测共 **344 对**。另完成三行样例对照与表数分层分析。 | [扩样结果](results/drspider-17x50/expansion/README.md) · [三行样例对照](results/drspider-17x50/select3/README.md) · [表数分层](results/drspider-17x50/diagnostics/table-count-summary.json) |
| 2 · Dr.Spider 人工编排历史实验 | 接入课程默认入口前，Visual 实验页实测的原题扰动后通过 **9/10**，扰动前后均通过 **8/10**。第 7 题采用通用 v4。 | [历史十题结果](reports/任务2先验知识与人工编排实验.md#十题最新编排结果) · [画布与复测证据](results/task2/submission/README.md#扩展实验与历版记录) · [编排源码](task2-rsi-data/experiment/README.md) |
| 2 · RSI Data 启动验收 | 课程 Spring Boot 经流程引擎运行单表 Agent 和多 Agent 协作，在 Dr.Spider SQLite 上核对结果。 | [课程执行验收记录](results/task2/course-acceptance-20261120.json) |

## 启动 Visual 并查看编排结果

### 准备数据和 Python 环境

在仓库根目录运行以下命令。实测环境使用 Python 3.13.6。数据准备脚本下载并校验固定版本的 Dr.Spider，评测准备脚本下载固定版本的 SQL 比较器。

```powershell
python -m venv .venv
& ./.venv/Scripts/python.exe -m pip install -r requirements.txt
& ./.venv/Scripts/python.exe ./scripts/prepare_data.py
& ./.venv/Scripts/python.exe ./scripts/setup_evaluator.py
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

在本地 `.env` 填入课程 API 地址和密钥，模型账户需可调用 `gpt-6-sol`。首次运行还需按下文「首次接入课程前端和后端」准备课程组件和编译后端。已经配置好课程环境的读者可直接启动三个服务。

### 启动前后端

在仓库根目录打开三个 PowerShell 终端，每个终端执行对应的命令并保持运行。

**终端 1 · Python 编排服务（3213）**

```powershell
& ./.venv/Scripts/python.exe ./task2-rsi-data/experiment/serve_canvas.py
```

**终端 2 · Spring Boot 后端（30845）**

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\task2-rsi-data\spring-boot\start-course.ps1
```

该命令为仓库启动脚本新开一个 PowerShell 进程，`-ExecutionPolicy` 仅作用于该次启动。[PowerShell 执行策略](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_powershell_exe?view=powershell-5.1)

**终端 3 · RSI Data Visual 前端（3000）**

```powershell
Set-Location ./.local/platform-preview/rsi-data-platform
npm.cmd run dev -- --hostname 127.0.0.1 --port 3000
```

Spring Boot 显示 `Started AppStarter`、前端显示 `Ready` 后，就可以打开下方的编排示例。

### 在页面运行并查看结果

十题验收页面直接选择编号和 `pre` / `post`，使用固定编排和 Thinking `high`。页面运行后会显示是否通过、最终 SQL 和查询结果。编排实验工作台可以改节点、切换历版预设和运行对照样本。在工作台选择某题的预设会自动匹配该题样本，跨题实验可以手动切换题面。「本机草稿」保存在当前浏览器。[十题验收页面](http://127.0.0.1:3000/?case=case1) · [编排实验工作台](http://127.0.0.1:3000/task2-experiment)

打开下面任一示例，选择「开发样本」中的扰动后（`post`）题面，点击「运行当前流程」。「运行记录」会显示节点输出、生成的 SQL、SQLite 查询结果和执行评分。

| 十题编排入口 | SQLite 数据库 | 库内关键数据与参考结果 |
| --- | --- | --- |
| [第 1 题 · 输出字段匹配 v2](http://127.0.0.1:3000/task2-experiment?case=projection_v2) | `network_1` | `Highschooler.grade = 10` 匹配 4 人，参考结果只输出 `name` 列。 |
| [第 2 题 · 筛选值归一化](http://127.0.0.1:3000/task2-experiment?case=filter_format) | `tvshow` | `TV_Channel.series_name` 实际存为 `Sky Radio`，对应套餐 `Sky Famiglia`。 |
| [第 3 题 · 筛选值同义配对](http://127.0.0.1:3000/task2-experiment?case=filter_synonym) | `flight_2` | `AIRLINES.Country` 存为 `USA`，匹配 12 家航司。 |
| [第 4 题 · 布尔字段取样](http://127.0.0.1:3000/task2-experiment?case=filter_boolean_evidence) | `battle_death` → `battle_death_0` | 原库用 `ship.disposition_of_ship = 'Captured'`。扰动库的 `ship.is_captured` 存文本 `F`、`T`，其中 `T` 有 4 条。 |
| [第 5 题 · 缺失明细与零值 v3](http://127.0.0.1:3000/task2-experiment?case=count_scope_v3) | `world_1` | `country` 中有 6 个地区在 `countrylanguage` 中没有明细。扰动后的参考查询按已有语言明细计数，返回 21 行。 |
| [第 6 题 · 姓名分列 v3](http://127.0.0.1:3000/task2-experiment?case=split_output_v3) | `museum_visit` → `museum_visit_0` | `visitor` 中同一访客从 `name = 'Fernando Gago'` 改为 `first_name = 'Fernando'`、`last_name = 'Gago'`。 |
| [第 7 题 · Top N v4](http://127.0.0.1:3000/task2-experiment?case=top_n_v4) | `wta_1` | `matches` 中 Madison Keys 的排名 12 组合重复。按姓名和排名去重后，前 5 项的排名为 17、24、16、12、9。 |
| [第 8 题 · 替代字段排序 v3](http://127.0.0.1:3000/task2-experiment?case=sort_direction_v3) | `orchestra` → `orchestra_1` | `orchestra.Year_of_Founded` 降序对应扰动库 `year_of_existence` 升序。两侧参考结果各 12 行。 |
| [第 9 题 · 筛选列核验 v2](http://127.0.0.1:3000/task2-experiment?case=filter_column_v2) | `car_1` | `car_makers.FullName` 存有 `Honda`，同一行的 `Maker` 是 `honda`。扰动后参考结果为 14 个车型。 |
| [第 10 题 · 筛选条件核验](http://127.0.0.1:3000/task2-experiment?case=filter_count) | `wta_1` | `matches` 中 WTA Championships 的 `winner_hand = 'L'` 匹配 3 条比赛明细，按获胜者姓名去重后为 2 人。 |

每题的 `pre` 和 `post` 均附 SQLite 路径、建表语句、核对查询与实际返回行，以及参考 SQL 和完整结果。[十题数据库证据](results/task2/submission/十题数据库证据.json) · [全部编排预设](task2-rsi-data/experiment/README.md) · [实验结果与画布证据](results/task2/submission/README.md)

<details>
<summary>首次接入课程前端和后端</summary>

使用 PowerShell 7、Node.js 24、Corretto 8u514、Maven 3.9.16 和 H2 1.4.199。将课程前端放在 `.local/platform-preview/rsi-data-platform/`，按前端 `package.json` 的 `@horsecoder/visual-core` 配置放置同级可视化组件及课程提供的 `dist`。课程后端源码放在 `.local/upstream/snapshots/rsi-data-spring-boot/`。Maven 私服配置放在 `.local/task2-rsi-data/spring-boot/settings.xml`，Java、Maven 和 H2 放在同目录的 `runtime/` 下，路径分别为 `corretto8/jdk1.8.0_514/`、`apache-maven-3.9.16/` 和 `h2-1.4.199.jar`。[课程前端源码](https://github.com/ymxiong/rsi-data-platform/tree/dev_main) · [课程后端源码](https://github.com/ymxiong/rsi-data-spring-boot)

从仓库根目录执行以下命令，再启动上面的三个服务。

```powershell
npm.cmd --prefix .local/platform-preview/rsi-data-platform install
& ./task2-rsi-data/spring-boot/build-course.ps1
& ./task2-rsi-data/experiment/build-course.ps1
& ./task2-rsi-data/experiment/install-preview.ps1
```

</details>

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

134 对前对后错样本的逐对判断、分类依据和备注见人工复核工作簿。[人工复核 Excel](results/drspider-17x50/Dr.Spider-850对基线与鲁棒性问题复核（汇报版）.xlsx) · [实验报告](reports/任务1实验报告.md) · [逐对判定 CSV](results/drspider-17x50/prepass-postfail-review.csv)

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

随后我在课程 Visual 按问题类型设计节点和分支。第 7 题通用 v4 的原题在实验页和两档 Thinking 批测均双侧通过。接入课程默认入口前，第 3 题的扰动后输入及第 9 题的扰动前输入在实验页实测失分。同类与混合题单用于开发回归，独立泛化仍待验证。[版本迭代汇总](reports/任务2先验知识与人工编排实验.md#版本迭代汇总) · [历史页面与批测证据](results/task2/submission/README.md#扩展实验与历版记录)
