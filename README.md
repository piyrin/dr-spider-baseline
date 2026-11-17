# Dr.Spider baseline

Dr.Spider 数据集分析与 Text-to-SQL 基线实验。输入为自然语言问题和数据库表结构，输出为 SQLite 查询，通过查询执行结果比较正确性。

当前提供五类扰动各五对的起步实验入口，固定种子为 42，共 25 对、50 次预测。真实模型实验与结果报告待完成。扩大运行范围前先完成小批量问题分析，再调整脚本的抽样数量与汇总分母。

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

## 准备固定样本

```powershell
.\.venv\Scripts\python.exe -X utf8 src/baseline.py --run preflight --prepare
```

准备命令只使用 Python 标准库，固定样本并执行 50 条标准 SQL，保存 `runs/preflight/config.json` 和 `samples.json`。`DB_` 扰动后的样本使用对应子集的 `database_post_perturbation` 数据库，其余读取原始数据库。

## 模型试跑

先启动 Ollama，检查已安装模型的实际名称和 digest。

```powershell
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

小批量完成后记录每种实际错误的样本标识、SQL、现象、证据、原因判断、修复和复测结果。将服务故障、SQL 执行错误和执行成功但答案错误分别计数，结合至少五类扰动分析模型表现。扩大规模前固定样本范围和配置，保存小批量问题记录。

当前指标是数据包所附单数据库上的执行一致率 EX，保留实际值与 DISTINCT，排序要求由标准 SQL 判断。报告写明数据库范围、已尝试数、未完成数、失败处理及比例分母。扩展为完整测试套件指标需要另行接入其数据库集合与评测流程。

提交时在 `reports/` 放置实验报告、问题记录、真实实验表和代表案例，在 `results/` 放置与报告对应的配置、环境、代码版本、样本标识、逐题预测及评分。大量原始输出可另外归档，在报告标明获取方法。题目与数据库内容的再分发按来源许可处理。

`reports/` 和 `results/` 可纳入 Git 跟踪。使用 `git add` 明确选择本次交付文件，并检查 `git diff --cached --name-only`。
