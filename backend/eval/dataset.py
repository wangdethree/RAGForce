"""评测数据集加载与校验模块（Requirement 11、13.2）。

本模块为 ``backend/eval/`` 框架提供"数据集入口守门员"，对应 ``design.md``
LLD-12 与 ``requirements.md`` §11.2 的字段契约。职责单一：

- **加载**：按行读取 ``datasets/qa_zh.jsonl``（JSON Lines，UTF-8）；
- **校验**：逐条核验字段类型、必填、取值域；
- **关联校验**：每条的 ``relevant_doc_ids`` 必须能在 ``corpus_path`` 下
  找到同名的 ``*.md`` 文件（basename 去扩展名）；
- **聚合报错**：一旦有任一条违约，**收集所有违约**后再一次性抛
  :class:`DatasetValidationError`，避免用户"改一条跑一次"的往返。

对外暴露（``__all__``）：

- :class:`QAEntry`                —— 不可变的 QA 记录值对象
- :class:`DatasetValidationError` —— 聚合所有违约后的校验异常
- :func:`load_and_validate`       —— 唯一入口；runner 直接调用

**不引入生产代码依赖**：仅使用标准库（``json`` / ``pathlib`` /
``dataclasses`` / ``typing``），保持与 ``config.py`` 一致的轻量风格，
方便在 ``lite`` profile 下脱离 docker-compose 栈直接运行。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

__all__ = [
    "QAEntry",
    "DatasetValidationError",
    "load_and_validate",
]


# ---------------------------------------------------------------------------
# 常量：允许的 difficulty 取值（与 requirements.md §11.2 / §12.4 保持一致）
# ---------------------------------------------------------------------------
# 使用 frozenset 保证常量不可变，同时让成员检测是 O(1)。
_ALLOWED_DIFFICULTIES: frozenset[str] = frozenset({"easy", "medium", "hard"})


# ---------------------------------------------------------------------------
# QAEntry：不可变的 QA 记录值对象（Requirement 11.2）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class QAEntry:
    """表示一条 QA 记录。字段语义与 ``qa_zh.jsonl`` 的 JSON 对象一致。

    ``frozen=True`` 把实例变成不可变值对象，确保 runner 在评测循环中对
    同一条 QA 的多次引用都拿到相同的数据；也让它天然可哈希，便于作为
    字典键做聚合。

    字段说明（同 ``requirements.md`` §11.2）：

    - ``qid``: QA 的稳定唯一标识，跨版本保持不变。
    - ``query``: 中文查询字符串，去首尾空白后仍非空。
    - ``relevant_doc_ids``: 相关文档列表（非空），元素为 corpus 目录下
      ``*.md`` 的 basename 去扩展名。
    - ``relevant_chunk_ids``: 可选；``None`` 表示"在评分阶段回退到按
      ``document_id`` 命中判定"（见 requirements §11.6）。
    - ``answer``: 可选参考答案，v1 不参与评分，仅供人工参考或未来扩展。
    - ``difficulty``: 可选难度标签，取值于 ``{"easy","medium","hard"}``，
      用于报告中的分层统计。
    """

    # QA 的稳定唯一 ID（如 "q001"）；去空白后必须非空。
    qid: str

    # 中文查询字符串；存储原始值，但校验时要求 strip 后仍非空。
    query: str

    # 相关文档 basename 列表；必须非空，且每个元素都要对应 corpus 实文件。
    relevant_doc_ids: list[str]

    # 相关 chunk_id 列表；缺省或 JSON null 会被归一为 Python None。
    relevant_chunk_ids: list[str] | None

    # 可选的参考答案；为保持向后兼容，允许缺省或 null，归一为 None。
    answer: str | None

    # 可选难度标签；仅允许 {"easy","medium","hard"} 或 None。
    difficulty: Literal["easy", "medium", "hard"] | None


# ---------------------------------------------------------------------------
# DatasetValidationError：聚合所有违约后的异常（Requirement 11.4、11.5）
# ---------------------------------------------------------------------------
class DatasetValidationError(Exception):
    """数据集校验失败；runner 捕获后以 exit code 2 终止。

    聚合错误而不是"遇到第一条就停"，是为了让用户一次性看到所有违约条目，
    避免"修一条跑一次"的反复。``violations`` 列表的每条字符串都是形如
    ``"line 5 qid=q003: <原因>"`` 的可读描述，直接打到 stderr 即可。

    调用约定：

    - ``violations`` 非空；若无违约就不应抛出本异常。
    - runner 在 ``main()`` 的最外层用 ``except DatasetValidationError`` 捕获，
      把 ``violations`` 逐行打到 ``sys.stderr`` 后 ``sys.exit(2)``。
    """

    def __init__(self, violations: list[str]) -> None:
        # 调用父类构造，把首条违约作为 str(exc) 的展示，便于 traceback 可读。
        # 同时保留完整列表供 runner 打印所有条目。
        super().__init__(
            f"Dataset validation failed with {len(violations)} violation(s): "
            f"{violations[0] if violations else '<empty>'}"
        )
        # 以属性暴露完整列表；runner 侧迭代打印而不是依赖 str(exc)。
        self.violations: list[str] = list(violations)


# ---------------------------------------------------------------------------
# 公共入口：load_and_validate
# ---------------------------------------------------------------------------
def load_and_validate(
    dataset_path: Path,
    corpus_path: Path,
) -> list[QAEntry]:
    """逐行加载 JSONL 并严格校验字段契约。

    流程：

    1. 扫描 ``corpus_path`` 目录，构造 ``{stem for stem in *.md}`` 集合，
       作为 ``relevant_doc_ids`` 的合法取值域。
    2. 按行读取 ``dataset_path``：跳过纯空白行，对每一非空行尝试
       ``json.loads``；解析失败也记入违约列表并带上行号。
    3. 对每条 JSON 对象依次校验：
       - 必填字段（``qid``/``query``/``relevant_doc_ids``）
       - 可选字段类型（``relevant_chunk_ids``/``answer``/``difficulty``）
       - ``relevant_doc_ids`` 的元素必须命中 corpus 文件集合
       - ``qid`` 全局去重（重复亦计入违约）
    4. 所有行处理完毕后：
       - 若 ``violations`` 非空 → 抛 :class:`DatasetValidationError`；
       - 否则返回按原文件顺序排列的 ``list[QAEntry]``。

    :param dataset_path: 指向 ``qa_zh.jsonl`` 的路径。
    :param corpus_path:  指向语料 ``*.md`` 所在目录（通常是
        ``backend/eval/datasets/corpus/``）。
    :returns: 校验通过的 ``QAEntry`` 列表，顺序同原文件。
    :raises FileNotFoundError: 数据集文件不存在；runner 会将其映射为
        exit code 2（符合 requirements §16.8）。
    :raises DatasetValidationError: 任一条记录违约时抛出，
        ``violations`` 包含所有违约描述。
    """

    # --- 步骤 0：存在性前置检查 -------------------------------------------
    # 不存在的路径直接抛 FileNotFoundError（由 runner 映射为 exit 2）。
    # 不把它归并到 violations，因为这属于 I/O 层面的"前置错误"，
    # 与"逐条字段违约"的语义完全不同。
    if not dataset_path.exists():
        raise FileNotFoundError(
            f"Dataset file does not exist: {dataset_path}"
        )

    # corpus 目录缺失也直接抛 FileNotFoundError；runner 同样映射为 exit 2。
    # 若 corpus 存在但是空目录，则会在后续每条 relevant_doc_ids 校验时报错。
    if not corpus_path.exists() or not corpus_path.is_dir():
        raise FileNotFoundError(
            f"Corpus directory does not exist: {corpus_path}"
        )

    # --- 步骤 1：构造 corpus basename 集合 --------------------------------
    # 只认后缀为 .md 的文件；取 stem（文件名不含扩展名）作为合法 doc_id。
    # 例如 "doc_01_rag.md" → "doc_01_rag"。
    valid_doc_ids: frozenset[str] = frozenset(
        p.stem for p in corpus_path.glob("*.md") if p.is_file()
    )

    # --- 步骤 2：逐行读取并累积违约 ---------------------------------------
    violations: list[str] = []
    entries: list[QAEntry] = []

    # ``seen_qids`` 用于检测 qid 重复；记录已经成功构造出的 qid。
    # 即便一条记录有其他字段违约，也仍把它的 qid 记入以便复用重复检测，
    # 但为了简化，我们只记录"已构造 QAEntry 的 qid"——这样重复定义发生时
    # 第一条落地，后续重复的会被判为违约。
    seen_qids: set[str] = set()

    # 使用 UTF-8 打开；newline="" 让 \r\n / \n 差异由 Python 正常处理。
    with dataset_path.open("r", encoding="utf-8", newline="") as fp:
        for line_no, raw_line in enumerate(fp, start=1):
            # 去掉行尾换行并判断纯空白行：JSONL 规范允许空行，予以跳过。
            stripped = raw_line.strip()
            if not stripped:
                continue

            # 尝试解析 JSON；失败即入违约列表，continue 到下一行。
            try:
                obj: Any = json.loads(stripped)
            except json.JSONDecodeError as exc:
                violations.append(
                    f"line {line_no}: invalid JSON ({exc.msg} "
                    f"at col {exc.colno})"
                )
                continue

            # JSON 解析成功但顶层不是 dict：视为格式违约。
            if not isinstance(obj, dict):
                violations.append(
                    f"line {line_no}: top-level JSON must be an object, "
                    f"got {type(obj).__name__}"
                )
                continue

            # 调用单条记录校验。返回值是 (entry_or_None, [violation_strs])：
            # - entry 非 None 时代表校验通过（此时 violations 列表必为空）；
            # - 任一字段违约时 entry 为 None，返回该条所有违约字符串。
            entry, per_line_violations = _validate_record(
                line_no=line_no,
                obj=obj,
                valid_doc_ids=valid_doc_ids,
                seen_qids=seen_qids,
            )

            if per_line_violations:
                # 聚合到全局违约列表；继续处理后续行，便于一次性汇报。
                violations.extend(per_line_violations)
                continue

            # entry 一定非空：把 qid 记入 seen_qids，结果追加到 entries。
            # ``assert`` 既是运行时断言，也给类型检查器一个收窄提示。
            assert entry is not None
            seen_qids.add(entry.qid)
            entries.append(entry)

    # --- 步骤 3：聚合报错或返回 -------------------------------------------
    if violations:
        # 一次性把所有违约抛出；runner 捕获后打印并退出。
        raise DatasetValidationError(violations)

    # 校验通过，按原文件顺序返回。
    return entries


# ---------------------------------------------------------------------------
# 内部辅助：单条记录校验
# ---------------------------------------------------------------------------
def _validate_record(
    *,
    line_no: int,
    obj: dict[str, Any],
    valid_doc_ids: frozenset[str],
    seen_qids: set[str],
) -> tuple[QAEntry | None, list[str]]:
    """校验单条 JSON 对象并返回 (entry, violations)。

    约定：

    - 校验通过 → 返回 ``(QAEntry(...), [])``
    - 校验不通过 → 返回 ``(None, [<原因1>, <原因2>, ...])``

    设计选择：**逐字段累积违约**，而不是遇到第一个错误就 return。
    这样一条记录里若同时缺 qid 又缺 query，用户能一次改完两个，
    契合"收集所有违约"的整体语义。

    :param line_no: 所在行号（1-based），用于拼接可读的错误消息。
    :param obj: 单条 JSON 对象（已确认为 dict）。
    :param valid_doc_ids: corpus 目录下 ``*.md`` 的 stem 集合。
    :param seen_qids: 已成功构造的 qid 集合，用于检测 qid 重复。
    """

    # 局部违约列表。每条消息都以 "line {line_no} qid={qid}: ..." 起头，
    # 让用户在 stderr 里能直接定位到原始行。qid 缺失时用 "<missing>" 占位。
    local: list[str] = []

    # 预取 qid 以便后续消息中展示；不存在或非字符串时用占位符。
    raw_qid = obj.get("qid")
    qid_display = raw_qid if isinstance(raw_qid, str) and raw_qid else "<missing>"

    # --- qid：必填、str、去空白后非空 ------------------------------------
    # 按 requirements §11.2：qid 为字符串且稳定唯一。
    qid_ok = False
    qid_value: str = ""
    if raw_qid is None:
        local.append(
            f"line {line_no} qid={qid_display}: missing required field 'qid'"
        )
    elif not isinstance(raw_qid, str):
        local.append(
            f"line {line_no} qid={qid_display}: 'qid' must be str, "
            f"got {type(raw_qid).__name__}"
        )
    elif not raw_qid.strip():
        # 允许首尾空白被 strip，但 strip 后不能为空串。
        local.append(
            f"line {line_no} qid={qid_display}: 'qid' must be non-empty string"
        )
    else:
        # qid 合法；但若已出现过则属于重复违约（requirements §11.4 隐含要求）。
        qid_value = raw_qid
        if raw_qid in seen_qids:
            local.append(
                f"line {line_no} qid={qid_display}: duplicate 'qid' "
                f"(already defined in an earlier line)"
            )
        else:
            qid_ok = True

    # --- query：必填、str、strip 后非空 ----------------------------------
    raw_query = obj.get("query")
    query_ok = False
    query_value: str = ""
    if raw_query is None:
        local.append(
            f"line {line_no} qid={qid_display}: missing required field 'query'"
        )
    elif not isinstance(raw_query, str):
        local.append(
            f"line {line_no} qid={qid_display}: 'query' must be str, "
            f"got {type(raw_query).__name__}"
        )
    elif not raw_query.strip():
        # 纯空白的 query 对检索毫无意义，按契约判为违约。
        local.append(
            f"line {line_no} qid={qid_display}: "
            f"'query' must be non-empty after stripping whitespace"
        )
    else:
        query_value = raw_query
        query_ok = True

    # --- relevant_doc_ids：必填、list[str]、非空、每项在 corpus 中 -------
    raw_doc_ids = obj.get("relevant_doc_ids")
    doc_ids_ok = False
    doc_ids_value: list[str] = []
    if raw_doc_ids is None:
        local.append(
            f"line {line_no} qid={qid_display}: "
            f"missing required field 'relevant_doc_ids'"
        )
    elif not isinstance(raw_doc_ids, list):
        local.append(
            f"line {line_no} qid={qid_display}: "
            f"'relevant_doc_ids' must be a list, got {type(raw_doc_ids).__name__}"
        )
    elif len(raw_doc_ids) == 0:
        # requirements §11.2 明确要求 length >= 1。
        local.append(
            f"line {line_no} qid={qid_display}: "
            f"'relevant_doc_ids' must be non-empty"
        )
    else:
        # 逐项校验字符串类型与 corpus 存在性；所有错误一次性收集。
        elem_errors: list[str] = []
        missing_in_corpus: list[str] = []
        for idx, elem in enumerate(raw_doc_ids):
            if not isinstance(elem, str):
                elem_errors.append(
                    f"index {idx} is {type(elem).__name__}, expected str"
                )
            elif not elem:
                elem_errors.append(f"index {idx} is empty string")
            elif elem not in valid_doc_ids:
                # 不在 corpus 集合里 → 记录，但不直接 append 到 local，
                # 目的是让"缺 N 个 doc"凝成一条消息，stderr 更清爽。
                missing_in_corpus.append(elem)

        if elem_errors:
            local.append(
                f"line {line_no} qid={qid_display}: "
                f"'relevant_doc_ids' has invalid element(s): "
                f"{'; '.join(elem_errors)}"
            )
        if missing_in_corpus:
            # requirements §11.5：缺失的 doc 名必须在 stderr 中指出。
            local.append(
                f"line {line_no} qid={qid_display}: "
                f"'relevant_doc_ids' references non-existent corpus file(s): "
                f"{missing_in_corpus}"
            )

        if not elem_errors and not missing_in_corpus:
            # 全部通过：可以安全 cast 为 list[str]。
            doc_ids_value = list(raw_doc_ids)
            doc_ids_ok = True

    # --- relevant_chunk_ids：可选、缺省/None/list[str] -------------------
    # 允许三种形态：
    #   1) key 根本不出现        → 归一为 None
    #   2) key 存在但值是 JSON null → 归一为 None
    #   3) key 存在且值是 list[str] → 原样保留
    chunk_ids_value: list[str] | None
    if "relevant_chunk_ids" not in obj:
        chunk_ids_value = None
    else:
        raw_chunk_ids = obj["relevant_chunk_ids"]
        if raw_chunk_ids is None:
            chunk_ids_value = None
        elif isinstance(raw_chunk_ids, list):
            # 逐项确认是字符串；任何非 str 元素都是违约。
            bad = [
                f"index {i} is {type(v).__name__}"
                for i, v in enumerate(raw_chunk_ids)
                if not isinstance(v, str)
            ]
            if bad:
                local.append(
                    f"line {line_no} qid={qid_display}: "
                    f"'relevant_chunk_ids' has non-string element(s): "
                    f"{'; '.join(bad)}"
                )
                # 违约时用空列表占位，后续不会走到 QAEntry 构造。
                chunk_ids_value = []
            else:
                chunk_ids_value = list(raw_chunk_ids)
        else:
            local.append(
                f"line {line_no} qid={qid_display}: "
                f"'relevant_chunk_ids' must be list or null, "
                f"got {type(raw_chunk_ids).__name__}"
            )
            chunk_ids_value = None

    # --- answer：可选、缺省/None/str --------------------------------------
    # 同 relevant_chunk_ids 的"三态"语义。
    answer_value: str | None
    if "answer" not in obj:
        answer_value = None
    else:
        raw_answer = obj["answer"]
        if raw_answer is None:
            answer_value = None
        elif isinstance(raw_answer, str):
            answer_value = raw_answer
        else:
            local.append(
                f"line {line_no} qid={qid_display}: "
                f"'answer' must be str or null, got {type(raw_answer).__name__}"
            )
            answer_value = None

    # --- difficulty：可选、缺省/None/枚举值 -------------------------------
    # 允许缺省或 null；出现时必须是字符串并取值于 _ALLOWED_DIFFICULTIES。
    difficulty_value: Literal["easy", "medium", "hard"] | None
    if "difficulty" not in obj:
        difficulty_value = None
    else:
        raw_difficulty = obj["difficulty"]
        if raw_difficulty is None:
            difficulty_value = None
        elif not isinstance(raw_difficulty, str):
            local.append(
                f"line {line_no} qid={qid_display}: "
                f"'difficulty' must be str or null, "
                f"got {type(raw_difficulty).__name__}"
            )
            difficulty_value = None
        elif raw_difficulty not in _ALLOWED_DIFFICULTIES:
            # 按 _ALLOWED_DIFFICULTIES 的固定集合排序展示，提示可读。
            allowed_display = sorted(_ALLOWED_DIFFICULTIES)
            local.append(
                f"line {line_no} qid={qid_display}: "
                f"'difficulty' must be one of {allowed_display}, "
                f"got {raw_difficulty!r}"
            )
            difficulty_value = None
        else:
            # 此分支确保 raw_difficulty 一定是三个合法值之一；
            # 用 cast 的替代手法：类型检查器会从 in 判断收窄到 Literal。
            difficulty_value = raw_difficulty  # type: ignore[assignment]

    # --- 汇总：若存在任何违约 → 返回 None 及违约列表 ----------------------
    # 注意：只要任一必填字段有违约（包括 qid 重复），就不构造 QAEntry，
    # 以免把"半合法的记录"混入下游评测。
    if local or not (qid_ok and query_ok and doc_ids_ok):
        return None, local

    # 全部字段通过：构造并返回 QAEntry（frozen 实例）。
    entry = QAEntry(
        qid=qid_value,
        query=query_value,
        relevant_doc_ids=doc_ids_value,
        relevant_chunk_ids=chunk_ids_value,
        answer=answer_value,
        difficulty=difficulty_value,
    )
    return entry, []
