"""单元测试层（`@pytest.mark.unit`）。

本层仅覆盖**纯逻辑**组件，要求：

- 不发起任何真实的 HTTP / 数据库 / 向量检索 I/O（Requirement 1.7）
- 单次 `pytest -m unit` 须在 2 秒内完成（Requirement 9.2）

规划覆盖的被测对象：``DocumentChunker``、``RRFusion``、``QueryRewriter``、
上下文组装函数、以及 ``backend/eval/metrics.py`` 中的指标纯函数。
"""
