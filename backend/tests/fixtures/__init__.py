"""测试用 fixtures 与样例数据工厂。

本包汇总不属于 ``conftest.py`` 范畴、但需要被多个测试模块复用的数据工厂：

- ``sample_files.py`` —— 借助 ``reportlab`` / ``python-docx`` 在内存中生成
  样例 PDF/DOCX，避免在仓库中提交任何二进制（Requirement 9.6）。
- ``seeded_kb.py``    —— 预置知识库记录工厂，为集成测试、属性测试与 API
  契约测试提供稳定的 ``(chunk_id, document_id, content)`` 样本。

具体内容由子任务 3.1 – 3.2 实现，本文件仅作为包占位。
"""
