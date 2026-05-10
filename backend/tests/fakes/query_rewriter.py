"""Fake 查询改写器：FakeQueryRewriter.

该模块提供生产 :class:`services.retrieval.query_rewriter.QueryRewriter`
的测试替身,对外暴露与生产完全一致的 duck-typed 接口 ``rewrite(query)``,
但**永不发起真实的 DeepSeek HTTP 请求**,而是返回一个确定性的变体列表。

核心契约(对应 requirements §1.3、§3.4、§18.3、§19.1):

* **首元素锚定**:返回列表的第 0 位**始终**是调用方传入的原始 ``query``;
  这与生产 ``QueryRewriter`` 的返回值语义一致(``[query] + rewrites``),
  让检索管线无论是否启用查询改写,原始 query 都保底参与检索。
* **可注入变体**:构造参数 ``variants`` 接受一个字符串列表,代表"除原始
  query 之外额外追加的改写变体",默认 ``None`` 即退化为恒等变换
  ``rewrite(q) -> [q]``。
* **优雅回退**:对空串、纯空白、``None`` 等退化输入,或任何意外异常,
  都 **SHALL** 返回仅含原始 query 的单元素列表,与生产在 DeepSeek 调用
  失败时 ``except Exception: return [query]`` 的行为保持一致。
* **确定性**:相同 ``(variants, query)`` 输入两次调用返回等价结果,
  满足 Fakes 的可复现性要求(需求 18.3)。

典型用法(见 ``tests/conftest.py`` 的 ``fake_query_rewriter`` fixture):

>>> fake = FakeQueryRewriter(variants=["改写变体一", "改写变体二"])
>>> await fake.rewrite("原始问题")
['原始问题', '改写变体一', '改写变体二']

>>> fake = FakeQueryRewriter()
>>> await fake.rewrite("原始问题")
['原始问题']
"""

from __future__ import annotations

from collections.abc import Iterable


class FakeQueryRewriter:
    """默认恒等变换、可注入额外变体的 Fake 查询改写器。

    Duck-typed 接口与生产 :class:`services.retrieval.query_rewriter.QueryRewriter`
    一致,可通过 ``monkeypatch.setattr`` 直接替换
    ``services.retrieval.retriever.query_rewriter`` 模块级单例。
    """

    def __init__(self, variants: Iterable[str] | None = None) -> None:
        """初始化 Fake 查询改写器。

        Args:
            variants: 除原始 query 之外额外追加的改写变体序列。
                * ``None``(默认)或空序列 → 退化为恒等变换,``rewrite`` 只返回
                  ``[query]``。
                * 任何可迭代对象 → 在构造期一次性物化为内部 ``list[str]``,
                  以保证每次 ``rewrite`` 调用都拿到相同序列(确定性,需求 18.3)。

        Notes:
            * 这里对 ``variants`` 做浅拷贝 (``list(variants)``),避免调用方
              随后修改原列表从而影响 Fake 的后续返回值。
            * 构造期不做类型校验,由调用方自行保证元素为 ``str``;Fake 的
              定位是"测试替身",过度防御反而掩盖测试用例的参数错误。
        """
        # 浅拷贝 variants,防止调用方在外部修改列表导致 Fake 行为漂移
        self._variants: list[str] = list(variants) if variants else []

    @property
    def variants(self) -> list[str]:
        """只读视图:当前注入的额外变体列表(返回副本以避免外部修改内部状态)。"""
        # 返回副本而非内部列表本身,保持 Fake 状态的封装性
        return list(self._variants)

    async def rewrite(self, query: str) -> list[str]:
        """生成查询的改写变体列表,首元素始终为原始 ``query``。

        Args:
            query: 原始查询字符串。

        Returns:
            长度 ``>= 1`` 的字符串列表:
            * 正常路径:``[query, *self._variants]``。
            * 退化路径(空串 / 仅空白 / ``None`` / 非字符串类型 / 运行期异常):
              ``[query]`` —— 即使 ``query`` 本身为空串,也保证首元素是它,
              让调用方可以稳定地以 ``result[0]`` 取回原始查询。

        契约(与 requirements §1.3、§3.4 对齐):
            * **不抛异常**:Fake 在任何输入下都 SHALL NOT 抛出,与生产
              ``QueryRewriter`` 的 ``except Exception: return [query]`` 一致;
              这保证检索管线即使在改写失败场景也能回退继续。
            * **首元素锚定**:无论走哪条分支,``result[0] is query`` 恒成立。
            * **去重由调用方负责**:Fake 不做变体之间或与 query 的去重;
              检索管线会在下游(RRF 融合 / 候选去重)统一处理重复 chunk_id。
        """
        # 防御式分支 1:空 query / 纯空白 / 非字符串 —— 直接退回仅含原 query 的单元素列表
        # 这模拟生产在"DeepSeek 不会针对无意义输入产出有效变体"时的回退语义
        if not isinstance(query, str) or not query.strip():
            return [query]

        # 防御式分支 2:把变体拼接过程包到 try 中,任何意外(例如构造期注入了非 str)
        # 都统一走生产一致的兜底路径,避免单测因 Fake 自身问题而崩溃
        try:
            # 正常路径:首元素为原始 query,后续依次追加构造期注入的变体
            # 使用列表解包 ``[query, *self._variants]`` 以生成全新列表,
            # 防止调用方修改返回值反过来污染 Fake 的内部状态
            return [query, *self._variants]
        except Exception:
            # 兜底路径:与生产 ``except Exception: return [query]`` 语义对齐
            return [query]
