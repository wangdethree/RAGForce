"""通用 Hypothesis strategies —— 属性测试的随机输入生成器。

本模块仅定义 Hypothesis ``SearchStrategy`` 工厂，不包含任何 ``@given`` 测试函数。
属性测试文件按需 ``from tests.properties.strategies import ...`` 复用。

设计目标（对齐 ``design.md`` LLD-9 / ``requirements.md`` §2.7、§8.6）：

1. **稳定短 ID**：``chunk_ids()`` 限定字符集为 ``[a-z0-9-]``，长度 1..16，
   便于在 `unique_by` 去重场景下控制冲突概率；也避开 JSONL/报告中的转义问题。

2. **中英混排 + 空白 + 超长**：``contents()`` 的字符域覆盖：
   - ASCII 可见字符（字母、数字、常用符号）
   - 半角空白（空格、制表符）
   - 常用 CJK 统一汉字区间 ``\\u4e00-\\u9fff``

   长度范围 0..256，兼顾"空文本"、"仅空白"、"超长字符串"等边界。

3. **检索记录结构**：``records()`` 产出 ``{chunk_id, document_id, content, content_type}``
   字典，与 ``services.retrieval.*`` 中的候选 dict 形状一致，供 RRF 融合、
   Retriever、Reranker 等场景直接消费。

4. **去重列表**：``unique_records(min_size, max_size)`` 基于 ``chunk_id`` 去重，
   避免列表内部预先冲突，把"冲突触发去重"的路径留给用例组合（例如 dense ∪ sparse）。

5. **评分列表**：``scored_results(max_size=20)`` 为 RRF 融合测试生成
   ``list[{chunk_id, content, score}]``，并按 ``score`` 非递增排序 ——
   许多生产接口（dense/sparse searcher 的返回）都隐含了"已排序"的前置契约。

可选的 ``nonempty_contents()`` / ``empty_or_blank()`` 辅助策略用于
"空/空白输入的优雅退化" 类属性（参见 Requirement 6、8.5）。
"""

from __future__ import annotations

from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# 原子策略
# ---------------------------------------------------------------------------

# 允许的 chunk_id 字符集：小写字母 + 数字 + 连字符。
# 选择这些字符的理由：
#   - 可读、可在 Markdown 报告中直接展示
#   - 完全 ASCII，避免跨平台文件名编码差异
#   - 连字符允许模拟 UUID/slug 结构（例如 "kb-001-chunk-42"）
_CHUNK_ID_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789-"

# 内容字符域：ASCII 可见区 + 半角空白 + 常用 CJK 区间。
# 使用 characters() 的白名单方式比手写 alphabet 更高效，也能让 Hypothesis
# 在缩减（shrink）阶段更好地找到最小反例（例如最小 CJK 字符 '一'）。
_CONTENT_CHARACTERS = st.one_of(
    # ASCII 可见字符（0x20 空格 至 0x7E 波浪号）—— 覆盖字母、数字、常见标点
    st.characters(min_codepoint=0x20, max_codepoint=0x7E),
    # 半角制表符：ASCII 0x09，属于常见"仅空白"场景的触发字符
    st.just("\t"),
    # 常用 CJK 统一汉字（20992 个）—— 覆盖绝大多数中文语料
    st.characters(min_codepoint=0x4E00, max_codepoint=0x9FFF),
)

# content_type 枚举：严格对齐 Requirement 8.4 的封闭枚举。
# 在 Fakes/集成测试里 content_type 通常只会出现 "text"，但在属性测试里
# 我们也要覆盖 "image"/"table" 分支，避免只对 text 验证不变式。
_CONTENT_TYPES = st.sampled_from(["text", "image", "table"])


# ---------------------------------------------------------------------------
# 公开策略（函数形式便于参数化与组合）
# ---------------------------------------------------------------------------


def chunk_ids() -> st.SearchStrategy[str]:
    """生成稳定的短 chunk_id 字符串。

    - 字符集：``[a-z0-9-]``（小写字母 + 数字 + 连字符）
    - 长度范围：1..16（保证非空，避免在集合/字典键上引入空串歧义）

    返回：``SearchStrategy[str]``，示例值：``"a"``、``"kb-01-c3"``、``"z9"``。
    """
    # min_size=1：禁止空字符串，防止与"缺失 id"语义混淆
    # max_size=16：足以区分数百万候选，同时缩减阶段收敛快
    return st.text(alphabet=_CHUNK_ID_ALPHABET, min_size=1, max_size=16)


def contents(min_size: int = 0, max_size: int = 256) -> st.SearchStrategy[str]:
    """生成混合 ASCII + 空白 + CJK 的文本内容。

    - 字符域：ASCII 可见区 ``\\u0020-\\u007E`` + 半角制表符 + CJK ``\\u4e00-\\u9fff``
    - 长度范围：``min_size..max_size``，默认 ``0..256``

    默认下界为 0 是为了覆盖 "空文本" / "仅空白" 这两类退化输入（对应
    Requirement 6、8.5）；如需非空文本，使用 ``nonempty_contents()``。

    参数：
        min_size: 最小字符数，默认 0。
        max_size: 最大字符数，默认 256（足以触发"超长单段"场景但仍可控）。
    """
    return st.text(alphabet=_CONTENT_CHARACTERS, min_size=min_size, max_size=max_size)


def nonempty_contents(max_size: int = 256) -> st.SearchStrategy[str]:
    """生成一定非空、至少含一个非空白字符的文本内容。

    用于不希望触发"空/空白退化分支"的属性测试（例如"chunker 信息无损"
    要求存在至少一个非空白字符才有意义）。
    """
    # 先按 contents 生成，再通过 filter 剔除"去掉空白后为空"的样本。
    # 注：filter 会降低生成效率；若使用频繁，可考虑拼接固定非空前缀。
    return contents(min_size=1, max_size=max_size).filter(lambda s: bool(s.strip()))


def empty_or_blank() -> st.SearchStrategy[str]:
    """生成空字符串或仅由空白字符组成的字符串（退化输入）。

    覆盖场景：
    - ``""``：绝对空
    - ``" "``、``"\\t"``、``"  \\t \\n"``：仅含空白
    - 混合制表符、空格、换行的长空白串

    用于 Requirement 6.3 / 6.4 / 8.5 等"空白输入必须优雅处理"的属性。
    """
    # st.just("") 单例 + 纯空白字符串（空格/制表符/换行）的合集
    _BLANK_CHARS = st.sampled_from([" ", "\t", "\n", "\r"])
    return st.one_of(
        st.just(""),
        st.text(alphabet=_BLANK_CHARS, min_size=1, max_size=32),
    )


def document_ids() -> st.SearchStrategy[str]:
    """生成文档 id 字符串（与 ``chunk_ids`` 同字符集，长度 1..12）。

    单独提出一个策略是因为：一个 doc 下常包含多条 chunk，测试里通常希望
    把 document_id 从较小的候选池中抽取以模拟"同文档多 chunk"的场景。
    """
    return st.text(alphabet=_CHUNK_ID_ALPHABET, min_size=1, max_size=12)


def records() -> st.SearchStrategy[dict]:
    """生成单条检索记录（``dict``）。

    字段契约（对齐 ``InMemoryDenseSearcher`` / ``InMemorySparseSearcher`` 的 store 项）：

    - ``chunk_id``：``str``，由 ``chunk_ids()`` 生成
    - ``document_id``：``str``，由 ``document_ids()`` 生成
    - ``content``：``str``，由 ``contents()`` 生成（允许空/空白）
    - ``content_type``：``Literal["text","image","table"]``

    注意：此处 **不** 包含 ``score`` 字段 —— ``score`` 属于"检索结果"语义，
    由下游 ``scored_results`` 策略负责构造。
    """
    return st.fixed_dictionaries(
        {
            "chunk_id": chunk_ids(),
            "document_id": document_ids(),
            "content": contents(),
            "content_type": _CONTENT_TYPES,
        }
    )


def unique_records(
    min_size: int = 0, max_size: int = 20
) -> st.SearchStrategy[list[dict]]:
    """生成 ``chunk_id`` 唯一的记录列表。

    - 基于 ``records()`` 构造 ``st.lists``，并设置 ``unique_by=chunk_id``。
    - 默认大小范围 ``0..20`` —— 上界 20 与生产 ``top_k`` 常用值（5/10）吻合，
      既能覆盖"远大于 top_k"的场景，也能保持属性测试的迭代开销可控。

    为什么在列表内部就去重？
        属性测试里很多不变式（例如 RRF 的"去重"）需要明确区分"输入内部重复"
        与"输入之间重叠"。在生成器里强制列表内部唯一，把"跨列表重叠"的
        组合交给调用方显式构造（例如 ``dense = unique_records(); sparse = ...``），
        这样失败反例的语义更清晰。
    """
    return st.lists(
        records(),
        min_size=min_size,
        max_size=max_size,
        unique_by=lambda r: r["chunk_id"],
    )


def scored_results(max_size: int = 20) -> st.SearchStrategy[list[dict]]:
    """生成 RRF 融合测试专用的"评分结果列表"。

    字段契约（对齐 dense/sparse searcher 的返回形状）：

    - ``chunk_id``：``str``
    - ``content``：``str``（允许空，RRF 不消费）
    - ``score``：``float``，范围 ``[0.0, 1.0]``

    不变式（由生成器保证）：

    - 列表长度 ``0..max_size``（默认上界 20）
    - 列表内 ``chunk_id`` 唯一 —— RRF 输入侧已是"单路排好序去重"的语义
    - 按 ``score`` 非递增排序 —— 生产 searcher 均返回已排序结果

    参数：
        max_size: 列表最大长度，默认 20。

    实现细节：
        Hypothesis 原生不支持"生成后再排序"的字段级约束，这里使用
        ``.map(lambda xs: sorted(xs, key=..., reverse=True))`` 在生成后
        统一按 score 非递增重排。这不会影响缩减阶段，因为排序是确定性映射。
    """
    # 单条评分记录：score 限定在 [0, 1]，且禁止 NaN/inf（allow_nan=False, allow_infinity=False）
    # 否则会给 "var(scores)" 这类聚合断言带来数值不稳定。
    _scored_record = st.fixed_dictionaries(
        {
            "chunk_id": chunk_ids(),
            "content": contents(),
            "score": st.floats(
                min_value=0.0,
                max_value=1.0,
                allow_nan=False,
                allow_infinity=False,
            ),
        }
    )
    return st.lists(
        _scored_record,
        min_size=0,
        max_size=max_size,
        unique_by=lambda r: r["chunk_id"],
    ).map(
        # 按 score 非递增排序：生产 searcher 的前置契约
        lambda xs: sorted(xs, key=lambda r: r["score"], reverse=True)
    )
