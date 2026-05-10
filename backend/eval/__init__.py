"""RAGForce 检索质量评测框架根包。

本包落地 `design.md` Scope B，提供一个可复现的离线评测工具：

- ``config.py``     —— ``RetrievalConfig`` / ``RunConfig`` 与 4 个预置配置
- ``dataset.py``    —— 加载与校验 ``datasets/qa_zh.jsonl``
- ``ingest.py``     —— 复用生产 ``DocumentChunker`` 把语料装入内存存储
- ``metrics.py``    —— Recall@k / MRR@k / nDCG@k / percentile 纯函数
- ``run.py``        —— ``python -m eval.run`` CLI 入口
- ``__main__.py``   —— 模块入口，等价于 ``run.py`` 的 ``main()``
- ``report.py``     —— 生成 ``YYYY-MM-DD-<profile>.md`` Markdown 报告
- ``profiles/``     —— ``lite``（内存 Fakes，零 Docker）与 ``full``（真实栈）两套 profile
- ``datasets/``     —— 内置的中文语料与 QA 集
- ``reports/``      —— 运行时产物目录（`.md` 文件不纳入版本控制）

默认使用 ``lite`` profile 以保证 CI 友好；切换到 ``full`` 后通过真实
docker-compose 栈运行（Requirement 15）。具体实现由子任务 11.x – 13.x 落地。
"""
