"""基于属性的测试层（`@pytest.mark.property`）。

本层使用 `Hypothesis` 对 RRF 融合、Retriever、Chunker、指标函数、评测
可复现性等不变式进行随机化验证：

- ``strategies.py``          —— 通用 Hypothesis strategies（由子任务 6.1 实现）
- ``test_rrf_properties.py`` —— Properties 1–6（RRF 不变式）
- ``test_retriever_properties.py`` —— Properties 7–10、15（检索管线）
- ``test_chunker_properties.py``   —— Properties 11–14（分块不变式）
- ``test_metrics_properties.py``   —— Property 16（指标取值域）
- ``test_eval_properties.py``      —— Property 17（评测可复现性）

每条属性测试均配置 ``max_examples >= 100``（性能相关例外 20）并使用
``@pytest.mark.property`` 标记（Requirement 2.7、2.8）。具体测试由子任务
6.x – 14.2 实现。
"""
