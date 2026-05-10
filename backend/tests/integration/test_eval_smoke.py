"""评测框架端到端烟测 —— 任务 14.1 / Requirements 15.4、17.1。

本模块对 ``backend/eval/`` 评测框架做 **进程内、零 Docker、零外部 I/O** 的端到端
烟测。目标有三：

1. **主用例 ``test_eval_smoke_runs_and_writes_report``**
   跑一次 ``run_eval(...)``，覆盖 *lite profile 全链路*：
   ``build_adapters → install → ingest_corpus → load_and_validate → retriever.retrieve
   × (config, k, query) → metrics 聚合 → report.render`` 一条龙，并对返回字典的
   所有关键键、Markdown 报告落盘、summary 矩阵标题、两组 ``(config, k)`` 指标
   全部断言到位。为防止一次随机波动导致整条 CI 红线，额外加一条"底线门槛"：
   至少一组指标的 ``nDCG@5 >= 0.3``；这只是 **回归门槛**——不是正确性门槛，
   达不到仅意味着 Fake 打分偶发失衡，不是被测代码出了错。

2. **辅助用例 ``test_eval_smoke_no_external_io``**
   在 ``run_eval`` 之前 monkeypatch ``httpx.AsyncClient`` 让其构造即抛异常，
   验证 *lite profile 完全走 Fakes* —— 不会因为 ingest/retrieve 链路意外触达
   真实 HTTP 客户端而泄漏外部 I/O（Requirement 15.4）。

3. 所有输入/输出路径均通过 ``__file__`` 推导出仓库根，再以绝对 :class:`Path`
   拼接。这样无论 pytest 从仓库根、``backend/`` 还是 IDE 集成里调起都能工作，
   不依赖 cwd（Requirement 20.5）。

约束与边界（故意写死、不要动）：

- **不重用** conftest 的 ``wired_pipeline`` / ``seeded_kb``。``run_eval`` 内部
  由 ``lite.install(adapters)`` 自己完成 Fakes 注入，如果再叠加 conftest 的
  monkeypatch 就会出现"注入两次、数据分布不可预期"的诡异现象。
- 输出目录统一用 pytest 的 ``tmp_path`` fixture，避免污染工作区下的
  ``backend/eval/reports/``，也保证同日多次跑用例时不会互相覆盖。
- 两条用例都挂 ``@pytest.mark.integration``；``asyncio_mode="auto"`` 已在
  ``pyproject.toml`` 开启，``async def`` 会被 pytest-asyncio 自动驱动。
"""

from __future__ import annotations

from pathlib import Path

import pytest

# 评测框架的入口与预置配置；``PRESET_BY_NAME`` 让我们按名字拿 RetrievalConfig，
# 避免手写四个 flag 时的拼写风险。
from eval.config import PRESET_BY_NAME, RunConfig
from eval.run import run_eval


# ---------------------------------------------------------------------------
# 公共辅助：把仓库根路径算出来，让测试不依赖 pytest 的 cwd。
# ---------------------------------------------------------------------------
# __file__ 路径层级（以仓库根为基准）：
#     <repo_root>/backend/tests/integration/test_eval_smoke.py
#     parents[0] = tests/integration
#     parents[1] = tests
#     parents[2] = backend
#     parents[3] = <repo_root>
# 这样无论 pytest 从哪个目录启动，都能稳稳指向仓库根；参数描述中 "cwd==项目根
# 时才对" 的相对路径陷阱就此彻底规避。
_REPO_ROOT: Path = Path(__file__).resolve().parents[3]
_DATASET_PATH: Path = _REPO_ROOT / "backend" / "eval" / "datasets" / "qa_zh.jsonl"
_CORPUS_PATH: Path = _REPO_ROOT / "backend" / "eval" / "datasets" / "corpus"


# ---------------------------------------------------------------------------
# 主用例：端到端烟测
# ---------------------------------------------------------------------------
@pytest.mark.integration
async def test_eval_smoke_runs_and_writes_report(tmp_path: Path) -> None:
    """lite profile 端到端烟测：报告落盘 + 指标结构完整 + 底线门槛。

    覆盖路径：
    1. 构造 ``RunConfig``（lite，两个配置 × k=5，固定 seed=42，输出到 ``tmp_path``）
    2. ``await run_eval(run_config)`` 完成 ingest → retrieve × N → metrics → report
    3. 对返回字典的四大键断言；对报告文件存在性 + 关键 Markdown 标题断言
    4. 对 ``metrics`` 字典的两组 ``(config, k)`` 键存在性断言
    5. 对"至少一组 ndcg@5 >= 0.3"的底线门槛断言（回归护栏，不是正确性门槛）
    6. 对 ``wall_time_s`` 做合理区间约束（lite profile 应远快于 30s）
    """

    # ---- 1) 构造 RunConfig：两条配置各跑一次 k=5 ----
    # kb_id 使用专用的 "eval-kb-smoke" 后缀，避免与其它测试或评测报告混淆；
    # seed=42 是框架默认值，显式写出让测试意图一目了然（Requirement 18.5）。
    run_config = RunConfig(
        profile="lite",
        dataset_path=_DATASET_PATH,
        corpus_path=_CORPUS_PATH,
        # 仅取两个有代表性的预置配置：dense_only 为 baseline，hybrid 触发 sparse+RRF
        configs=[PRESET_BY_NAME["dense_only"], PRESET_BY_NAME["hybrid"]],
        k_values=[5],
        kb_id="eval-kb-smoke",
        # tmp_path 已经是 Path，Path() 再包一层既无副作用又对齐任务描述的调用形态
        output_dir=Path(tmp_path),
        seed=42,
    )

    # ---- 2) 执行评测（asyncio_mode=auto → pytest-asyncio 自动驱动协程） ----
    result = await run_eval(run_config)

    # ---- 3a) 返回字典四大键齐备（与 run_eval 文档契约一致） ----
    # 用 "in" 断言单独写出每个键，失败时定位更精确。
    assert "report_path" in result
    assert "wall_time_s" in result
    assert "metrics" in result
    assert "per_query" in result

    # ---- 3b) 报告文件真的落到了盘上 ----
    report_path = result["report_path"]
    assert report_path is not None, (
        "report_path 为 None 说明 eval.report 未被成功 import 或 render 抛异常"
    )
    # 统一转为 Path 再做 exists 检查：render() 返回的是 Path，但显式转一次
    # 兼容未来把字符串路径暴露出来的变体。
    assert Path(report_path).exists(), f"报告文件不存在：{report_path}"

    # ---- 3c) 报告内容：关键 Markdown 标题必须存在 ----
    # 用 UTF-8 读，避免 Windows 默认 GBK 把中文报告读乱码。
    report_text = Path(report_path).read_text(encoding="utf-8")
    # "# 评测报告" 是报告首行标题（render 拼的是 "# 评测报告 — <profile> — <date>"），
    # 用 "# 评测报告" 作为子串匹配，容忍未来日期 / profile 名微调。
    assert "# 评测报告" in report_text, "报告缺少一级标题 '# 评测报告'"
    # "## Summary @ k=5" 是 _render_summary_table 的固定二级标题，对应唯一的 k=5
    assert "## Summary @ k=5" in report_text, "报告缺少 '## Summary @ k=5' 段"

    # ---- 4) metrics 字典含 (config, k) 两组键 ----
    metrics = result["metrics"]
    assert ("dense_only", 5) in metrics, "metrics 缺少 ('dense_only', 5) 键"
    assert ("hybrid", 5) in metrics, "metrics 缺少 ('hybrid', 5) 键"

    # 每一组都必须至少含 ndcg 字段（其它字段由 run_eval 契约保证，这里只
    # 断言我们门槛要用的那一个，避免为已覆盖的契约重复 assert）。
    dense_ndcg = metrics[("dense_only", 5)]["ndcg"]
    hybrid_ndcg = metrics[("hybrid", 5)]["ndcg"]

    # ---- 5) 底线门槛：至少有一组 ndcg@5 >= 0.3（回归护栏，不是正确性门槛） ----
    # 说明：Fake embedder 用 SHA256 shingle 哈希构造 1024 维向量，理论上语义
    # 近似只能"凑合"，随机因素可能让某一组 nDCG 偶发低于 0.3。我们只要求
    # 两组之中**至少一组** >= 0.3，作为"框架整体可用性"的最低护栏。当本条
    # 失败时，不要第一反应去调检索逻辑——先怀疑是否数据集/语料/Fake 打分
    # 任何一环出现了漂移。若确实是 Fake 随机性过强，可将阈值放宽到 0.2，
    # 但此前请与团队确认，**不要**在单次 CI 红线下降低阈值。
    assert dense_ndcg >= 0.3 or hybrid_ndcg >= 0.3, (
        f"两组 nDCG@5 全部低于 0.3 底线："
        f"dense_only={dense_ndcg:.4f}, hybrid={hybrid_ndcg:.4f}。"
        f"这可能是 Fake 打分过于随机；确认无代码回归后可把门槛放宽到 0.2"
    )

    # ---- 6) wall_time_s 在合理区间 ----
    # 上界 30s：lite profile 纯内存 Fakes，20 条 QA × 2 配置 × 1 个 k，实测
    # 约 1.2s。设 30s 是为了给 CI 上的 I/O 抖动留 25× 安全余量；超过说明
    # 环境异常（例如真的走了 HTTP），应当立刻被看到。
    # 下界 > 0：排除 "time.time() 没动过" 这种荒谬场景。
    wall_time_s = result["wall_time_s"]
    assert wall_time_s > 0, f"wall_time_s 应为正数，实测 {wall_time_s}"
    assert wall_time_s < 30, (
        f"wall_time_s 超过 30s（实测 {wall_time_s:.3f}s）；"
        f"lite profile 应远快于此，检查是否意外走了真实 I/O"
    )


# ---------------------------------------------------------------------------
# 辅助用例：lite profile 不触达 httpx —— 即"零外部 I/O"强约束
# ---------------------------------------------------------------------------
@pytest.mark.integration
async def test_eval_smoke_no_external_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """monkeypatch ``httpx.AsyncClient`` 让其构造即抛异常，验证 lite 完全不走网络。

    动机（Requirement 15.4）：
    - lite profile 的承诺是"**不发起任何对 Milvus / PG / embedding HTTP /
      reranker HTTP / DeepSeek 的真实 I/O**"。检索/改写/重排所有 HTTP 链路
      最终都会走 ``httpx.AsyncClient(...)``；所以最干净的验证方式是：
      **把 ``httpx.AsyncClient`` 换成一个构造即抛的占位类**，再跑一遍
      ``run_eval``。如果 lite 乖乖走 Fakes，那一次 AsyncClient 都不会被构造，
      用例顺利通过；如果任一路径漏了 Fake 替换、或 Fake 内部意外调了
      httpx，就会在构造瞬间把 ``RuntimeError("external I/O forbidden in
      lite profile")`` 抛出来，测试会直接红。
    - 为了节省 CI 时间，这里只跑 1 个 config × k=5（``dense_only``），因为
      "有无外部 I/O" 不依赖配置矩阵；一条完整路径走通就足以给出结论。
    """

    # ---- 1) 定义"一经构造即抛"的占位类 ----
    # 任何位置参数/关键字参数都无所谓，我们只关心 __init__ 被触发这个事实。
    class _ForbiddenAsyncClient:
        """替身 httpx.AsyncClient —— 一旦被构造就抛 RuntimeError。"""

        def __init__(self, *args: object, **kwargs: object) -> None:
            # 异常消息与任务描述保持字面一致，便于 CI 日志 grep 出来时一眼辨认。
            raise RuntimeError("external I/O forbidden in lite profile")

    # ---- 2) monkeypatch 替换 httpx.AsyncClient ----
    # 使用属性路径字符串形式；monkeypatch 会在用例结束自动还原原类，
    # 不会污染后续用例（与 conftest 的其它 fixture 隔离）。
    monkeypatch.setattr("httpx.AsyncClient", _ForbiddenAsyncClient)

    # ---- 3) 构造 RunConfig：最小配置矩阵以节省时间 ----
    run_config = RunConfig(
        profile="lite",
        dataset_path=_DATASET_PATH,
        corpus_path=_CORPUS_PATH,
        # 只跑一条配置：本用例的语义与配置集无关，只和"是否触达 httpx"有关
        configs=[PRESET_BY_NAME["dense_only"]],
        k_values=[5],
        kb_id="eval-kb-smoke-no-io",
        output_dir=Path(tmp_path),
        seed=42,
    )

    # ---- 4) 运行 run_eval：关键断言 = "不抛我们 monkeypatch 的那条 RuntimeError" ----
    # 用 try/except 精准捕获：我们不吞其它异常，以免误判成"测试通过"。
    # 若 lite 乖乖走 Fakes，这里会正常返回结果字典，用例通过；
    # 若哪一步意外构造 httpx.AsyncClient，异常文本匹配就会判失败。
    try:
        result = await run_eval(run_config)
    except RuntimeError as exc:
        # 只在异常消息匹配我们注入的文本时才算"触达 httpx"的失败；
        # 其它无关的 RuntimeError 原样外抛，避免误吞真实问题。
        if "external I/O forbidden in lite profile" in str(exc):
            pytest.fail(
                f"lite profile 意外触达了 httpx.AsyncClient（构造被拦截）："
                f"{exc!r}"
            )
        # 非目标 RuntimeError：外抛让 pytest 原样呈现
        raise

    # 顺带做一个 sanity 断言：run_eval 正常返回，说明全链路确实走通了 Fakes。
    assert result["report_path"] is not None, (
        "run_eval 在没触达 httpx 的前提下应正常产出报告"
    )
