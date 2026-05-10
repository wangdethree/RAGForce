# RAGForce 学习文档

本目录是 RAGForce 项目的配套学习材料，分三份：

| 文档 | 主题 | 读者 |
|---|---|---|
| [01_learning_path.md](./01_learning_path.md) | **学习路线图**，5 周分阶段计划 | 第一次接触本仓库的新人 |
| [02_architecture_walkthrough.md](./02_architecture_walkthrough.md) | **架构与代码详解**，按分层讲生产代码 | 想理解 RAG 管线与 FastAPI 后端的开发者 |
| [03_testing_and_eval_deep_dive.md](./03_testing_and_eval_deep_dive.md) | **测试与评测框架深度讲解**，对应 `.kiro/specs/testing-and-eval-framework/` | 想理解 PBT / Fakes / 评测 runner 的开发者 |

## 怎么读

- 新人先读 **01**（30 分钟），形成整体心智模型
- 再读 **02**（1-2 小时，边读边打开对应源码）
- 要扩展评测框架或增加 property 测试，读 **03**

## 配套阅读

- 根 `README.md` — 仓库的"使用说明书"（启动命令、API 端点列表）
- `.kiro/specs/testing-and-eval-framework/` — 本次交付的 spec 三件套（requirements / design / tasks）
- `backend/eval/README.md` — 评测数据集的字段契约与 CLI 用法
