# 任务 2 编排与复测证据

[实验报告](../../../reports/任务2先验知识与人工编排实验.md) · [编排源码](../../../task2-rsi-data/experiment/README.md)

十题原题验收索引列出同一 post 输入的历史基线 SQL、参考 SQL、验收预设的 Visual 实际 SQL、评分、运行 ID 和 token。历史基线十题均未通过，验收预设通过 9/10。第 3 题默认画布未通过，同源 high 档批测通过。第 7 题保留 v2 原题预设，通用 v3 原题 post 仍未通过。第 9 题 v2 的新画布记录显示 pre 初稿和最终 SQL 均未通过。[十题原题验收索引](十题原题验收索引.json)

| 内容 | 阅读入口 |
|---|---|
| 各题各版 Visual 画布 | [canvas/](canvas/) |
| 先验实验请求与响应、各题浏览器记录、汇总与题单 | [records/](records/) |
| 批量逐节点请求、响应与逐题评分 | [完整批测记录.zip](完整批测记录.zip) |
| 第 5 题 v2/v3 同题单回放与画布实测 | [版本对照](records/task2-count-scope-revisions/comparison.json) |
| 第 6 题 v3 审查与修订 | [复测记录](records/task2-split-output-v3/) |
| 第 7 题通用 v3 | [批测和画布记录](records/task2-top-n-v3/) |
| 第 8 题 v3 排序方向 | [复测记录](records/task2-sort-direction-v3/) |
| 第 9 题 v2 局部修订 | [同初稿回放和画布记录](records/task2-filter-column-v2/) |

报告中的压缩包链接标出了包内原始相对路径。解压后可按 `runs/<运行名>/` 核查冻结题单、SQL 和评分。部分浏览器记录的完整请求按课程运行 ID 位于 [course-node-traces/](records/course-node-traces/)。读取这些记录无需连接模型服务。

同类和混合题单用于开发回归。版本间复用的请求和范围以报告各节为准。SQL 执行评分使用对应侧的 SQLite，原题清单的参考查询用于本地评分。
