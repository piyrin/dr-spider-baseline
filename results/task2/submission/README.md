# 任务 2 编排与复测证据

## 课程十题验收

十道 Dr.Spider 原题的前后端编排、运行结果和分析见验收明细。提交包收录这十题及复核索引。[验收明细](acceptance/README.md) · [十题提交包](课程十题验收.zip)

## 扩展实验与历版记录

[实验报告](../../../reports/任务2先验知识与人工编排实验.md) · [编排源码](../../../task2-rsi-data/experiment/README.md)

实验页的首次运行索引列出各题 post 输入的历史基线 SQL、参考 SQL、实际 SQL、评分、运行 ID 和 token，其中第 7 题采用 v2。接入课程默认入口前，实验页的最后一轮汇总采用第 7 题通用 v4，原题 post 通过 9/10，双侧通过 8/10。[首次运行索引](十题原题验收索引.json) · [实验页逐题统计](../../../reports/任务2先验知识与人工编排实验.md#十题最新编排结果)

| 内容 | 阅读入口 |
|---|---|
| 各题各版 Visual 画布 | [canvas/](canvas/) |
| 十道所选原题的 SQLite 路径、建表语句、库内取值与参考结果 | [十题数据库证据](十题数据库证据.json) |
| 先验实验请求与响应、各题浏览器记录、汇总与题单 | [records/](records/) |
| 批量逐节点请求、响应与逐题评分 | [完整批测记录.zip](完整批测记录.zip) |
| 第 5 题 v2/v3 同题单回放与画布实测 | [版本对照](records/task2-count-scope-revisions/comparison.json) |
| 第 6 题 v3 审查与修订 | [复测记录](records/task2-split-output-v3/) |
| 第 7 题通用 v3 | [批测和画布记录](records/task2-top-n-v3/) |
| 第 7 题通用 v4 | [页面记录](records/task2-top-n-v4/browser-results.json) · [两档批测汇总](records/task2-top-n-v4/summary.json) · [逐题证据包](records/task2-top-n-v4/records.zip) |
| 第 8 题 v3 排序方向 | [复测记录](records/task2-sort-direction-v3/) |
| 第 9 题 v2 局部修订 | [同初稿回放和画布记录](records/task2-filter-column-v2/) |
| 第 1 题 v2、第 7 题 v3 页面记录 | [两条 `pre` 运行证据](records/task2-visual-pre-supplement/browser-results.json) |

报告中的压缩包链接标出了包内原始相对路径。解压后可按 `runs/<运行名>/` 核查冻结题单、SQL 和评分。部分浏览器记录的完整请求按课程运行 ID 位于 [course-node-traces/](records/course-node-traces/)。读取这些记录无需连接模型服务。

同类和混合题单用于开发回归。版本间复用的请求和范围以报告各节为准。SQL 执行评分使用对应侧的 SQLite，原题清单的参考查询用于本地评分。
