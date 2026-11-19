# Dr.Spider baseline

Dr.Spider 数据集分析与 Text-to-SQL 基线实验。输入为自然语言问题和数据库表结构，输出为 SQLite 查询，通过查询执行结果比较正确性。

本次用 Thingo API 的 `gpt-6-sol` 测了五类扰动，共 75 对、150 条预测。50 对主批的单数据库执行一致率从扰动前 72% 降至扰动后 66%。两批实验表、六类主要 SQL 差异、七处单点复核和 JetBlue 模型对照均有对应记录。[任务1实验报告](reports/任务1实验报告.md) · [问题记录](reports/问题记录.md) · [工程阅读](reports/rsi-data阅读记录.md)

## 环境与数据

使用 Python 3.13。PowerShell 中从项目根目录执行。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -X utf8 scripts/prepare_data.py
.\.venv\Scripts\python.exe -X utf8 scripts/setup_evaluator.py
```

数据来源版本和 SHA-256 保存在 `manifests/data_source.json`，数据目录为 `data/`。本地数据已复制完成时，准备脚本会使用已有目录。数据规模检查记录见 `manifests/data_inventory.json`。

评测辅助模块下载到 `.cache/evaluator/`，固定上游提交为 `e97acc546ecbee8fa27fa8dbf025ef61493a876c`。脚本导入其中的 `result_eq`。来源和使用说明见上游项目。[Dr.Spider 数据说明](https://github.com/awslabs/diagnostic-robustness-text-to-sql) · [评测项目](https://github.com/taoyds/test-suite-sql-eval)

## Thingo API 单题测试

从项目根目录执行。复制配置模板后，在 `.env` 填写 `THINGO_API_KEY`。

```powershell
Copy-Item .env.example .env
notepad .env
.\.venv\Scripts\python.exe -X utf8 scripts/run_api_sample.py --prepare
.\.venv\Scripts\python.exe -X utf8 scripts/run_api_sample.py --list-models
.\.venv\Scripts\python.exe -X utf8 scripts/run_api_sample.py --run api-sol-one
```

已有 `.env` 时直接编辑该文件。配置中的 `gpt6sol` 是当前选择的模型名称，准确 ID 通过账号的 `/v1/models` 核实。脚本接受大小写、标点和 ChatGPT 显示名前缀的等价写法。匹配失败时，根据 `--list-models` 输出修改 `THINGO_MODEL`，或传入 `--model` 精确 ID。

单题默认选用 `NLQ_keyword_synonym` 第 0 对的 `pre` 侧，也可用 `--group`、`--index`、`--side` 指定题目。每次运行先获取模型清单，再发送完整表结构和问题以生成一条 SQL。请求显式传入 `stream=false`，其余生成参数采用服务端默认值。每次尝试用独立的运行名。历史 `gpt-6-astra` 试跑见本地 `runs/api-one/`。

`runs/<单题运行名>/` 保存样本、配置、依赖环境、模型清单、请求、响应和评分。题目身份及扰动前后以 `sample.json` 为准。配置记录代码提交、工作区状态与源文件哈希。标准 SQL 仅用于本地评分，数据库扰动的 `post` 侧使用对应的扰动后数据库。远程模型 digest 记为未知，返回模型名和 fingerprint 按实际响应记录。

`.env` 已加入 Git 忽略。配置文件采用简单的 `KEY=value` 格式，支持整行注释和外层引号，同名进程环境变量优先。接口和模型权限说明见 [Thingo 快速开始](https://thingo-2.apifox.cn/9352582m0) 与 [客户端接入](https://thingo-2.apifox.cn/9358238m0)。

## Thingo API 配对批测

`scripts/run_api_batch.py` 从选定的类别中各抽取指定对数，使用同一个索引配对 `pre` 和 `post`，再逐条调用 `scripts/run_api_sample.py`。例如，下列命令选两类，每类三对，共 12 条生成请求。

```powershell
.\.venv\Scripts\python.exe -B -X utf8 scripts/run_api_batch.py `
    --run sol-two-groups-3pairs `
    --groups SQL_sort_order DB_schema_synonym `
    --pairs-per-group 3 `
    --execute
```

默认使用全部五类、每类五对、种子 `42` 和模型 `gpt-6-sol`。用 `--help` 查看类别名称，用 `--model` 指定服务端实际模型 ID。省略 `--execute` 时，仅在本地选择样本、执行标准 SQL、写出计划和汇总文件。正式运行也会先执行这些检查。

扩大样本规模时，可用 `--seed` 重新抽样。本地数据上已核对下列配置，和种子 `42` 的 `sol-25pairs` 相比，50 对的 `(类别, 下标)` 交集为 0。其他规模、种子或数据版本的重叠情况，可比较两份 `plan.json`。

```powershell
.\.venv\Scripts\python.exe -B -X utf8 scripts/run_api_batch.py --run sol-50pairs-seed43 --pairs-per-group 10 --seed 43 --execute
```

- `runs/<批次名>/plan.json` 记录样本、模型、抽样参数、数据版本与源码哈希。
- `runs/<批次名>/per_pair.csv` 并排保存每对题的前后预测、标准 SQL、评分和错误状态。
- `runs/<批次名>/summary.csv` 汇总每类的前后正确数、单数据库 EX 和百分点变化。某侧的结果收齐后才计算该侧 EX。收到响应后的生成格式错误和 SQL 执行错误计为答错。缺失响应、模型标识不一致或评测比较错误会停止批测，并保留当前明细。
- `runs/<批次名>-<样本ID>/` 保留每条请求的配置、响应和评测记录。

相同配置可以用同一命令续跑，复用已有评测记录。配置或代码有变化时使用新批次名。先关掉 Excel 中已打开的输出 CSV，再继续运行，以便脚本更新汇总。

## Ollama 示例试跑

本地 Ollama 基线保留独立入口。其 `--prepare` 模式可以离线验证固定的 25 对样本，输出 `samples.json`。测试本地模型时，先启动 Ollama 并检查已安装模型的名称和 digest。

```powershell
.\.venv\Scripts\python.exe -X utf8 src/baseline.py --run preflight --prepare
Invoke-RestMethod http://127.0.0.1:11434/api/version
(Invoke-RestMethod http://127.0.0.1:11434/api/tags).models | Select-Object name,digest
.\.venv\Scripts\python.exe -X utf8 src/baseline.py --run smoke --model qwen3.5:9b --limit 2
```

模型默认值为 `qwen3.5:9b`，请按实际模型列表填写 `--model`。基线将问题和完整表结构交给模型生成一次 SQL，标准 SQL 用于本地评分。提示词和请求参数在 `src/baseline.py` 定义，每次运行保存配置快照。

查看两条预测的原始响应、执行结果及错误记录后，运行五类小批量。

```powershell
.\.venv\Scripts\python.exe -X utf8 src/baseline.py --run pilot --model qwen3.5:9b
.\.venv\Scripts\python.exe -m pip freeze | Set-Content -Encoding utf8 runs/pilot/environment.txt
git rev-parse HEAD | Set-Content -Encoding utf8 runs/pilot/code_commit.txt
```

`runs/<运行名>/` 包含固定样本、配置、模型标识、请求、响应、逐题记录和汇总。相同命令可复用已有记录继续运行。已记录的失败也会复用，修复后重测采用新运行名。模型 digest、配置和样本变化时采用新运行名。

## 分析与交付

对代表错误保存问题及表结构、标准 SQL、预测 SQL、执行结果或报错，指出具体错误位置，说明原因假设和证据。围绕假设进行有针对性的核查或受控复测，记录预期与实际结果、结论可信程度及后续改进方向。结合至少五类问题形成诊断分析，统计当前样本中的错误数量与比例，并保存样本范围和配置。

当前指标是数据包所附单数据库上的执行一致率 EX，保留实际值与 DISTINCT，排序要求由标准 SQL 判断。报告写明数据库范围、已尝试数、未完成数、失败处理及比例分母。扩展为完整测试套件指标需要另行接入其数据库集合与评测流程。

`results/` 收录两批的配置、环境、源码哈希、样本标识、预测 SQL、逐题评分与分类汇总，以及离线复核和模型对照。用 `group`、`index` 和 `side` 在固定版本的数据中定位对应问题、schema 和标准 SQL。完整请求与响应保存在本地 `runs/`，导出记录中的哈希可用于核对原始文件。[25 对首批](results/sol-25pairs.json) · [50 对主批](results/sol-50pairs-seed43.json) · [SQL 复核](results/sql-diagnostics.json) · [模型对照](results/jetblue-model-control.json)

`reports/` 和 `results/` 可纳入 Git 跟踪。使用 `git add` 明确选择本次交付文件，并检查 `git diff --cached --name-only`。
