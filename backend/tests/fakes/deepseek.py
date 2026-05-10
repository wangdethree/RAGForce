"""DeepSeek 对话大模型端口的 Fake 实现。

本模块对应 ``design.md`` LLD-3 中的 ``ChatLLMPort`` 端口契约，提供一个
完全在内存中运行、**永不发起任何真实网络请求** 的 ``FakeDeepSeekChat``，
用于：

- API 契约测试（``tests/api/test_chat_api.py``）验证 ``/api/v1/chat`` 的响应 schema
- 单元测试覆盖"调用链路异常时查询改写回退为仅含原始 query"的分支
- 评测 lite profile 下需要生成离线回答的场景（v1 评测本身不打分 answer）

与生产侧 ``services.generation.deepseek_chat.DeepSeekChat`` 的接口保持一致：

- ``async generate(query, context_chunks, history=None) -> ChatResponse``
- ``async def generate_stream(query, context_chunks, history=None)``  （异步生成器）

但所有逻辑都是纯内存/纯字符串拼装，不会触发 ``httpx`` 或任何 I/O，因此
满足 Requirement 9.5（测试不依赖外部网络）与 Requirement 19.1（通过
``monkeypatch.setattr`` 注入，不修改生产代码）。
"""

from __future__ import annotations

import time
from typing import AsyncIterator

from schemas.chat import ChatResponse, Citation


class FakeDeepSeekChat:
    """返回基于上下文拼装的"罐头"回答，永不联网的 DeepSeek 替身。

    与生产 ``DeepSeekChat`` 的差异：

    - 不读取 ``settings.DEEPSEEK_API_KEY`` / ``DEEPSEEK_BASE_URL``
    - 不创建 ``httpx.AsyncClient``，不触发任何 DNS / TCP / TLS
    - 对相同输入返回完全相同的输出（确定性，满足 Requirement 18.3）

    ``calls`` 列表记录每一次 ``generate`` / ``generate_stream`` 的调用入参，
    供测试断言"是否被调用/被调用了几次"（例如验证关闭流式路径时不触发）。
    """

    #: 默认的 answer 前缀；可在构造时覆盖，便于区分多个 Fake 实例
    DEFAULT_ANSWER = "(fake-answer)"

    def __init__(self, answer: str = DEFAULT_ANSWER) -> None:
        # ``answer``：罐头回答的前缀，最终 answer 会拼接上 query 与上下文条数
        self.answer = answer
        # ``calls``：调用日志，结构为 ``(mode, query, n_ctx)``
        # ``mode`` 取值于 ``"generate"`` / ``"stream"``；测试可直接断言
        self.calls: list[tuple[str, str, int]] = []

    async def generate(
        self,
        query: str,
        context_chunks: list[dict],
        history: list[dict] | None = None,
    ) -> ChatResponse:
        """生成非流式回答。

        - ``answer`` 由 ``self.answer`` 前缀、原始 query、上下文条数拼装而成，
          便于在断言中直接匹配（避免真实 LLM 的不确定输出）。
        - ``citations`` 由 ``context_chunks`` 派生，``content`` 截断到 200 字符，
          与生产实现保持一致，从而让 schema 校验的行为完全一致。
        - ``latency_ms`` 反映 **本函数** 的执行耗时（通常为亚毫秒），保留
          两位小数，以验证 ``ChatResponse`` 字段契约。
        """
        # 记录本次调用，供测试断言调用次数与入参
        self.calls.append(("generate", query, len(context_chunks)))

        start = time.perf_counter()

        # 由上下文片段派生 Citation 列表：保留与生产相同的字段与截断策略
        citations = [
            Citation(
                chunk_id=c.get("chunk_id", ""),
                document_name=c.get("document_name", ""),
                # content 截断至 200 字符，和生产 DeepSeekChat.generate 一致
                content=c["content"][:200],
                score=float(c.get("score", 0.0)),
            )
            for c in context_chunks
        ]

        # 拼装罐头 answer：包含 query 与上下文条数，便于测试精确断言
        answer_text = f"{self.answer} | q={query} | n_ctx={len(context_chunks)}"

        # 用 perf_counter 差值换算为毫秒；round 保留两位小数保持与生产一致
        latency_ms = round((time.perf_counter() - start) * 1000, 2)

        return ChatResponse(
            answer=answer_text,
            citations=citations,
            latency_ms=latency_ms,
        )

    async def generate_stream(
        self,
        query: str,
        context_chunks: list[dict],
        history: list[dict] | None = None,
    ) -> AsyncIterator[str]:
        """以异步生成器形式吐出最小化的 SSE delta。

        产出的每一段字符串的格式与生产端对 DeepSeek API 返回的 SSE chunk 解析
        后的 ``data`` 载荷一致，即 ``{"choices":[{"delta":{"content":...}}]}``。
        这样 API 层 (``api/v1/chat.py:chat_stream``) 的 ``yield f"data: {chunk}..."``
        包装逻辑无需任何特殊分支即可被覆盖。

        本实现 **不发起任何网络请求**：所有 chunk 都在内存中合成。为了覆盖
        "多次 yield + 流终止"两条路径，这里吐出两段内容 delta。
        """
        # 记录本次调用，供测试断言流式路径被触发
        self.calls.append(("stream", query, len(context_chunks)))

        # 首段：固定前缀 + 上下文条数，便于集成测试精确断言
        # 注意：此处 JSON 字符串与生产 DeepSeek 的 SSE payload 结构保持一致
        yield (
            '{"choices":[{"delta":{"content":"'
            f"{self.answer}"
            '"}}]}'
        )

        # 次段：携带原始 query 的轻量上下文回显，覆盖生成器"多次迭代"分支
        # 对 query 做最基础的 JSON 转义（仅处理 "\" 与双引号），避免外部依赖
        safe_query = query.replace("\\", "\\\\").replace('"', '\\"')
        yield (
            '{"choices":[{"delta":{"content":" | q='
            f"{safe_query}"
            '"}}]}'
        )
