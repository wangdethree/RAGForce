"""FastAPI 契约测试层（`@pytest.mark.api`）。

本层通过 ``httpx.AsyncClient(transport=ASGITransport(app=app))`` 在进程内
驱动 FastAPI 应用，配合 ``app.dependency_overrides`` 注入内存 SQLite 会话
与 Fakes，用以验证对外暴露的 REST 契约（状态码、响应 schema）。

约束：任何 API 契约测试都 **不得** 触发真实外部 I/O（Requirement 7.6）。
具体测试由子任务 10.x 实现。
"""
