"""Markdown 报告渲染器（Requirement 17、18.6、20.5）。

本模块把 ``run_eval`` 产出的聚合结果（metrics + per-query hit + 元数据）
渲染成 GitHub 兼容的 Markdown 报告，落盘到 ``run_config.output_dir``。

对外接口（``__all__``）：

- :func:`render` —— 唯一入口；接受关键字参数并返回实际写入的 :class:`Path`

约束（对应 ``design.md`` LLD-13、``requirements.md`` §17）：

- 文件命名：``YYYY-MM-DD-<profile>.md``，同日同 profile 覆盖写入
- 内容顺序：**标题 → 元数据块 → Summary 矩阵（每个 k 一张）→ Per-query
  breakdown（前 10 条）→ How to reproduce**
- 脱敏：**不输出** API key / secret / 内网主机名 / IP / 绝对路径；路径统一
  走 ``Path.as_posix()`` 保持正斜杠，兼容 GitHub 渲染
- 数值格式化：Recall/MRR/nDCG/p50/p95 统一保留 4 位小数（``f"{x:.4f}"``）
- 无模板依赖：仅用 f-string + 列表推导 + ``"\n".join(...)`` 拼接

本模块是纯函数式的"文档渲染器"，没有任何 I/O 副作用（除了最后一次
``Path.write_text``）。所有路径都通过 :class:`pathlib.Path` 处理，
Windows 与 POSIX 无差异。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

# 仅依赖评测框架自身的配置对象；不 import 任何生产模块，避免测试期的副作用。
from eval.config import RunConfig

__all__ = ["render"]


# ---------------------------------------------------------------------------
# 内部辅助：路径脱敏（Requirement 17.7、18.6、20.5）
# ---------------------------------------------------------------------------
def _safe_relative_path(p: Path) -> str:
    """把路径脱敏为 POSIX 风格字符串，避免在报告里暴露绝对路径。

    逻辑分支：

    - 已经是相对路径 → 直接 ``as_posix()``，把 Windows 的 ``\\`` 规范为 ``/``
    - 绝对路径 → 先尝试 ``relative_to(Path.cwd())`` 缩减为相对形式；
      若无法缩减（路径在 cwd 之外、或跨盘符），退回 ``p.name`` 仅保留
      basename。这样即使输入是 ``D:\\python_code\\ragforce\\backend\\...``
      或 ``/tmp/xxx/...``，报告里也不会泄露绝对路径信息。

    约束：**任何情况下都不返回含盘符冒号或以 ``/`` 起始的绝对路径**。
    """

    # 已经是相对路径（如 ``Path("backend/eval/datasets/qa_zh.jsonl")``）
    # → 用 as_posix 保证 GitHub 渲染时不出现反斜杠转义问题。
    if not p.is_absolute():
        return p.as_posix()

    # 绝对路径：优先裁剪为"相对 CWD"的 POSIX 风格
    try:
        return p.relative_to(Path.cwd()).as_posix()
    except ValueError:
        # Path 位于 CWD 之外 / 跨盘符 → 退回最小披露：仅保留 basename
        return p.name


# ---------------------------------------------------------------------------
# 内部辅助：数值格式化（Requirement 17.3）
# ---------------------------------------------------------------------------
def _fmt4(v: float) -> str:
    """保留 4 位小数的统一数值格式化（指标与延迟毫秒同宽）。"""

    # 使用 f-string 的 ``.4f`` 格式：对 NaN/inf 也会给出可读字符串，不抛异常
    return f"{v:.4f}"


# ---------------------------------------------------------------------------
# 分段渲染：元数据块
# ---------------------------------------------------------------------------
def _render_metadata(
    *,
    run_config: RunConfig,
    entries_count: int,
    wall_time_s: float,
    started_at: datetime,
) -> str:
    """渲染"运行元数据"段（Requirement 17.2）。

    以 bullet list 呈现 8 个字段：profile、数据集路径（脱敏）、数据条目数、
    参与配置、k 值、seed、wall time、生成时刻。配置名与 k 值用反引号包裹，
    便于 GitHub 渲染器显示为内联代码。
    """

    # 路径字段统一走脱敏函数；避免绝对路径、盘符、内网前缀泄露到报告里
    dataset_display = _safe_relative_path(run_config.dataset_path)

    # 参与配置名：按 run_config.configs 的原始顺序列出（= CLI 出现顺序）
    config_names = [cfg.name for cfg in run_config.configs]
    configs_str = ", ".join(f"`{n}`" for n in config_names) if config_names else "_(空)_"

    # k 值列表：逗号分隔的整数字符串
    k_values_str = ", ".join(str(k) for k in run_config.k_values)

    # wall time 按 Requirement 17.2 保留 3 位小数；isoformat 给 ISO 8601 本地时间
    lines = [
        "## 运行元数据",
        "",
        f"- **Profile**: `{run_config.profile}`",
        f"- **数据集路径**: `{dataset_display}`",
        f"- **数据条目数**: {entries_count}",
        f"- **参与配置**: {configs_str}",
        f"- **k 值**: {k_values_str}",
        f"- **seed**: {run_config.seed}",
        f"- **wall time**: {wall_time_s:.3f} s",
        f"- **生成时刻**: {started_at.isoformat()}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 分段渲染：Summary 矩阵（每个 k 一张表）
# ---------------------------------------------------------------------------
def _render_summary_table(
    *,
    run_config: RunConfig,
    k: int,
    metrics: dict[tuple[str, int], dict[str, float]],
) -> str:
    """渲染某个 k 的 Summary 矩阵表（Requirement 17.3）。

    **列顺序固定**：``| Config | Recall@k | MRR@k | nDCG@k | p50 ms | p95 ms |``
    —— 即便某个 (config, k) 组合在 ``metrics`` 中缺失，也会用 0.0 占位
    （保持表格结构稳定，方便人工横向对比）。

    **行顺序**：与 ``run_config.configs`` 一致，与 CLI 参数出现顺序对齐。
    数值列右对齐（Markdown 对齐语法 ``---:``），以便 p95 等多位数时数字右
    端对齐、视觉更整齐。
    """

    # 表头：左对齐 Config，数值列右对齐（GitHub 支持 ``---:`` 语法）
    header = f"| Config | Recall@{k} | MRR@{k} | nDCG@{k} | p50 ms | p95 ms |"
    separator = "|---|---:|---:|---:|---:|---:|"

    # 每个 config 一行；缺失键时退回全零字典，避免 KeyError
    default_row = {
        "recall": 0.0,
        "mrr": 0.0,
        "ndcg": 0.0,
        "p50_ms": 0.0,
        "p95_ms": 0.0,
    }
    rows: list[str] = []
    for cfg in run_config.configs:
        m = metrics.get((cfg.name, k), default_row)
        rows.append(
            f"| `{cfg.name}` "
            f"| {_fmt4(m.get('recall', 0.0))} "
            f"| {_fmt4(m.get('mrr', 0.0))} "
            f"| {_fmt4(m.get('ndcg', 0.0))} "
            f"| {_fmt4(m.get('p50_ms', 0.0))} "
            f"| {_fmt4(m.get('p95_ms', 0.0))} |"
        )

    # 段落结构：## 标题 + 空行 + 表头 + 分隔 + 数据行
    lines = [f"## Summary @ k={k}", "", header, separator, *rows]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 分段渲染：Per-query breakdown（前 10 条）
# ---------------------------------------------------------------------------
def _render_per_query(
    *,
    run_config: RunConfig,
    per_query: list[dict[str, Any]],
) -> str:
    """渲染前 10 条 query 在各 config 下的命中矩阵（Requirement 17.4）。

    - 只展示 **第一个 k 值** 下的命中情况（避免表格过宽）
    - 每行：``qid`` + ``query`` 前 40 字符 + 每个 config 的 ✓ / ✗
    - ``per_query`` 为空时退化为一句占位文案

    per_query 元素形如 ``{"qid", "config_name", "k", "hit", "query"(可选)}``；
    按 ``(qid, config_name)`` 两键重索引成嵌套字典后再组装表格。
    """

    # 段落标题 + 空行
    lines: list[str] = ["## 逐条命中（前 10 条）", ""]

    # 空输入退化：给一段人类可读的占位，避免空表格让报告看起来"坏掉"
    if not per_query:
        lines.append("_(没有逐条记录)_")
        return "\n".join(lines)

    # 第一个 k 值；若 k_values 为空（退化保护）则直接把所有记录当作同一批
    first_k = run_config.k_values[0] if run_config.k_values else None

    # 按 qid 聚合：{qid: {config_name: hit_bool}}；同时保留首次出现顺序
    by_qid: dict[str, dict[str, bool]] = {}
    query_text_of: dict[str, str] = {}
    qid_order: list[str] = []

    for pq in per_query:
        # 仅保留第一个 k 值的记录（若 first_k 为 None，则全量记录都保留）
        if first_k is not None and pq.get("k") != first_k:
            continue

        qid = str(pq.get("qid", ""))
        if not qid:
            # 没有 qid 的记录无法定位，直接跳过（而不是污染表格）
            continue
        if qid not in by_qid:
            by_qid[qid] = {}
            qid_order.append(qid)
        by_qid[qid][str(pq.get("config_name", ""))] = bool(pq.get("hit", False))
        # query 文本是可选字段；优先用记录自带的，否则留空串
        if qid not in query_text_of:
            query_text_of[qid] = str(pq.get("query", ""))

    # 只展示前 10 条 qid（保持文件顺序；Requirement 17.4）
    qid_order = qid_order[:10]

    # 若过滤后为空（例如 first_k 不匹配任何记录），同样落到占位文案
    if not qid_order:
        lines.append("_(没有逐条记录)_")
        return "\n".join(lines)

    # 表头：qid + query 前 40 字符 + 每个 config 列
    config_names = [cfg.name for cfg in run_config.configs]
    header_cells = ["qid", "query（前 40 字）"] + [f"`{n}`" for n in config_names]
    header_line = "| " + " | ".join(header_cells) + " |"
    # 分隔行：qid/query 左对齐，hit 列居中（GitHub 支持 ``:---:`` 语法）
    sep_cells = ["---", "---"] + [":---:"] * len(config_names)
    sep_line = "|" + "|".join(sep_cells) + "|"

    lines.append(header_line)
    lines.append(sep_line)

    # 数据行：每个 qid 一行；✓/✗ 取决于该 (qid, config) 在 first_k 下是否命中
    for qid in qid_order:
        # 截断 query 前 40 字符，避免过长破坏表格；缺失则留空串
        query_snippet = query_text_of.get(qid, "")[:40]
        # 清理 query 中的 ``|``（Markdown 表格分隔符）与换行，避免破坏表格
        query_snippet = query_snippet.replace("|", "\\|").replace("\n", " ")

        cells = [qid, query_snippet]
        for name in config_names:
            hit = by_qid.get(qid, {}).get(name, False)
            cells.append("✓" if hit else "✗")
        lines.append("| " + " | ".join(cells) + " |")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 分段渲染：How to reproduce（Requirement 17.5）
# ---------------------------------------------------------------------------
def _render_how_to_reproduce(*, run_config: RunConfig) -> str:
    """渲染"如何复现"段 —— 给出可复制的 bash 命令与准备步骤。

    命令行使用 **相对路径**（``_safe_relative_path`` 脱敏），并串起本次运行
    的关键参数：``--profile``、``--configs``、``--k``、``--dataset``、
    ``--corpus``、``--seed``。读者复制整段即可在 ``backend/`` 目录下重跑。
    """

    # 参数字段：配置名 / k 值 / 路径 / seed；均以逗号分隔或直接透传
    configs_csv = ",".join(cfg.name for cfg in run_config.configs)
    k_csv = ",".join(str(k) for k in run_config.k_values)
    dataset_display = _safe_relative_path(run_config.dataset_path)
    corpus_display = _safe_relative_path(run_config.corpus_path)

    # bash fenced code block：先 cd 到 backend，再调用 python -m eval.run
    # 该命令与 Requirement 16.1 的入口完全一致，直接可复制执行。
    command_lines = [
        "cd backend",
        (
            f"python -m eval.run"
            f" --profile {run_config.profile}"
            f" --configs {configs_csv}"
            f" --k {k_csv}"
            f" --dataset {dataset_display}"
            f" --corpus {corpus_display}"
            f" --seed {run_config.seed}"
        ),
    ]

    lines = [
        "## 如何复现",
        "",
        "环境准备（首次执行时）：",
        "",
        "```bash",
        "cd backend",
        'pip install -e ".[dev]"',
        "```",
        "",
        "复现本次评测：",
        "",
        "```bash",
        *command_lines,
        "```",
        "",
        f"报告将写入 `{_safe_relative_path(run_config.output_dir)}/"
        f"<YYYY-MM-DD>-{run_config.profile}.md`（同日同 profile 会被覆盖）。",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 公共入口：render
# ---------------------------------------------------------------------------
def render(
    *,
    run_config: RunConfig,
    entries_count: int,
    metrics: dict[tuple[str, int], dict[str, float]],
    per_query: list[dict[str, Any]],
    wall_time_s: float,
    started_at: datetime,
) -> Path:
    """渲染评测 Markdown 报告并写入文件，返回实际写入的路径。

    参数
    ----
    run_config:
        本次评测的全局配置；决定 profile 名、输出目录、参与配置、k 值、
        seed、数据集/语料路径等元数据。
    entries_count:
        本次评测实际参与的 QA 条目数（通常等于
        ``len(load_and_validate(...))``）。
    metrics:
        以 ``(config_name, k)`` 为键的聚合指标字典。每个值应包含五个浮点
        字段：``recall / mrr / ndcg / p50_ms / p95_ms``。缺失的 (config, k)
        组合会以 0.0 占位。
    per_query:
        按 ``(qid, config_name, k)`` 展开的每条 QA 命中记录。字段契约：
        ``{"qid": str, "config_name": str, "k": int, "hit": bool,
        "query": str (可选)}``。
    wall_time_s:
        从 ``run_eval`` 开始到 metrics 聚合结束的墙钟耗时（秒），由 runner
        传入；报告中保留 3 位小数。
    started_at:
        报告生成时刻。同时被用于：
        - 文件名日期部分 ``started_at.strftime("%Y-%m-%d")``
        - 元数据块中的 ``生成时刻`` ISO 8601 字段

    返回
    ----
    ``Path``：实际写入的 Markdown 文件绝对或相对路径；与
    ``run_config.output_dir / "<YYYY-MM-DD>-<profile>.md"`` 一致。

    副作用
    ------
    - 若 ``run_config.output_dir`` 不存在，会 ``mkdir(parents=True,
      exist_ok=True)`` 创建；
    - 若同日同 profile 的报告文件已存在，会被覆盖写入。

    脱敏保证（Requirement 17.7、18.6）
    ---------------------------------
    - 所有路径字段都走 :func:`_safe_relative_path`：绝对路径会被裁剪为
      相对 CWD 或退回 basename，不会把盘符、内网主机名或 IP 泄露到报告里；
    - 报告中仅包含配置名、指标、路径（脱敏后）与 query 文本前 40 字，
      **不包含** API key、secret、连接串、embedding HTTP URL 等敏感字段。
    """

    # ---- 1) 输出目录：不存在则递归创建 ----
    # parents=True 允许一次性创建多级目录；exist_ok=True 兼容覆盖写入场景。
    output_dir = run_config.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    # ---- 2) 文件名：<YYYY-MM-DD>-<profile>.md ----
    # 使用 started_at 的本地日期；同日同 profile 会命中同一个文件名 → 覆盖。
    date_str = started_at.strftime("%Y-%m-%d")
    file_path = output_dir / f"{date_str}-{run_config.profile}.md"

    # ---- 3) 逐段渲染 Markdown ----
    # 每段是一个字符串；段与段之间用一个空行分隔（"\n\n".join）。
    sections: list[str] = []

    # 标题：Requirement 17.1 要求首行为 `# ...`，便于 GitHub 自动生成 TOC
    sections.append(f"# 评测报告 — {run_config.profile} — {date_str}")

    # 元数据块
    sections.append(
        _render_metadata(
            run_config=run_config,
            entries_count=entries_count,
            wall_time_s=wall_time_s,
            started_at=started_at,
        )
    )

    # Summary 矩阵：每个 k 一张表，按 k_values 原顺序渲染
    for k in run_config.k_values:
        sections.append(
            _render_summary_table(run_config=run_config, k=k, metrics=metrics)
        )

    # Per-query breakdown（前 10 条）
    sections.append(_render_per_query(run_config=run_config, per_query=per_query))

    # How to reproduce
    sections.append(_render_how_to_reproduce(run_config=run_config))

    # ---- 4) 拼接并写入文件 ----
    # 末尾补一个换行，保证 POSIX 工具链（cat、less 等）显示正常。
    file_path.write_text("\n\n".join(sections) + "\n", encoding="utf-8")

    return file_path
