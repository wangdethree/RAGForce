"""评测数据集包。

本包承载 ``corpus/`` 中的中文 Markdown 语料与 ``qa_zh.jsonl`` QA 集。
文件的具体内容与校验逻辑分别由子任务 12.1 / 12.2 与 13.2 实现，本文件
仅用于 Python 包标记，使 ``backend/eval/dataset.py`` 可按包方式解析相对
路径（Requirement 20.5：统一使用 ``pathlib.Path``，避免硬编码分隔符）。
"""
