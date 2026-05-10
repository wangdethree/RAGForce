"""测试套件的 pytest 基础配置（conftest）。

本模块负责搭建测试会话启动阶段所需的**基础环境**，具体包括：

1. 在 Windows 平台上把 `asyncio` 事件循环策略切换为
   :class:`asyncio.WindowsSelectorEventLoopPolicy`。
   - 背景：Python 3.8+ 在 Windows 默认使用 ProactorEventLoop，
     但 ``aiosqlite`` 与 ``httpx`` 的底层 pipe/socket 在 Proactor 循环
     下关闭时偶发 ``NotImplementedError`` / ``RuntimeError``。切换为
     Selector 策略可以规避这些兼容性问题（见 Requirement 20.1、20.3、20.6）。
   - 必须在 import 阶段（而非 fixture 内）就完成切换：某些 pytest 插件
     会在 conftest 加载时即触发事件循环相关的初始化。

2. 为测试运行环境补齐两个必要的环境变量兜底：
   - ``DEEPSEEK_API_KEY``：生产配置要求此变量存在，测试层统一置为 ``"test"``
     占位，确保即便开发机未配置真实 key 也能顺利 import 生产模块
     （见 Requirement 9.5）。
   - ``UPLOAD_DIR``：文件上传目录，测试使用相对路径 ``./.test_uploads``，
     避免污染生产上传目录；同时预先创建该目录，以便后续 API
     契约测试可以直接写入临时文件。

3. 暴露一个 session 级 ``event_loop`` fixture，复用同一个事件循环贯穿
   整个测试会话，避免 aiosqlite / httpx 在事件循环频繁切换时出现关闭顺序
   异常（见 Requirement 20.6）；这也是 pytest-asyncio 在 session 作用域
   fixture 场景下的刚需。

4. 预留数据库 / FastAPI / Fakes 三类 fixtures 的**锚点注释区**，
   子任务 3.4 / 3.5 / 3.6 会按顺序 append 到本文件末尾，形成完整的
   测试基础设施层。

   当前文件已包含：
   - 基础块（Windows 事件循环策略、环境变量兜底、session 级 event_loop）；
   - **数据库块（async_engine / db_session）** —— 由任务 3.4 落地：
     基于 ``sqlite+aiosqlite:///:memory:`` + ``StaticPool`` 的 session 级
     引擎，启动阶段 ``import src.models`` 注册全部表并 ``create_all``；
     ``db_session`` 为每个用例提供独立 ``AsyncSession``，
     ``expire_on_commit=False`` 与生产保持一致，避免 async 场景的
     ``MissingGreenlet`` 异常。
"""

from __future__ import annotations

# 标准库依赖：按 PEP 8 分组，仅引入本基础块真正需要的模块。
import asyncio
import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool


# --------------------------------------------------------------------------- #
# 1. Windows 事件循环策略切换（import 阶段执行）
# --------------------------------------------------------------------------- #
# 说明：必须在 conftest 被 pytest 加载时立即执行，不能推迟到 fixture 内。
#   - aiosqlite 在 Proactor 循环下关闭连接会触发 NotImplementedError；
#   - httpx 的 ASGITransport 在 Proactor 下也偶发事件循环错误。
# 因此一律将 Windows 上的事件循环策略替换为 Selector 策略，保持与 Linux/macOS
# 一致的行为，解决 Requirement 20.1 / 20.3 / 20.6。
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


# --------------------------------------------------------------------------- #
# 2. 环境变量兜底（import 阶段执行）
# --------------------------------------------------------------------------- #
# 使用 ``setdefault`` 而非直接赋值：若 CI 或开发者已显式设置了这些变量，
# 则尊重其原值，不会被测试基础块覆盖。
# - DEEPSEEK_API_KEY：生产 settings 要求非空；测试层不会真的发起 HTTP
#   请求（由 FakeDeepSeekChat 拦截），因此占位 "test" 即可。
# - UPLOAD_DIR：文件上传目录，使用项目根下的隐藏目录 ``./.test_uploads``，
#   便于 .gitignore 统一屏蔽。
os.environ.setdefault("DEEPSEEK_API_KEY", "test")
os.environ.setdefault("UPLOAD_DIR", "./.test_uploads")

# 确保上传目录真实存在：
#   - 使用 pathlib.Path 保证跨平台路径分隔符正确（Requirement 20.5）；
#   - parents=True 允许父目录缺失时一并创建；
#   - exist_ok=True 保证并行测试会话重复调用时不报错。
_upload_dir = Path(os.environ["UPLOAD_DIR"])
_upload_dir.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------- #
# 3. session 级 event_loop fixture
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
def event_loop():
    """为整个测试会话提供**同一个**事件循环。

    - 作用域（scope）设为 ``session`` 的原因：
      某些 session 级 async fixture（如后续 3.4 的 ``async_engine``）依赖
      pytest-asyncio 能够拿到 session 级 loop，否则会抛
      ``ScopeMismatch`` 错误。
    - 生命周期：
      1. 启动时使用 ``asyncio.new_event_loop()`` 创建新循环；
        在 Windows 上由于上方已设置 Selector 策略，此处得到的是
        :class:`SelectorEventLoop`，aiosqlite/httpx 均可正常工作。
      2. yield 给 pytest-asyncio 使用；
      3. 所有测试结束后显式 ``loop.close()``，避免 ResourceWarning。
    """

    loop = asyncio.new_event_loop()
    try:
        yield loop
    finally:
        loop.close()


# --------------------------------------------------------------------------- #
# 4. 数据库 fixtures — 内存 SQLite 引擎与 AsyncSession
# --------------------------------------------------------------------------- #
# 说明（对应任务 3.4、Requirement 9.5 / 19.2 / 20.6）：
#
# - 使用 ``sqlite+aiosqlite:///:memory:`` 作为测试后端：零外部依赖、秒级启动，
#   且能在单一进程内完全替代 PostgreSQL，满足"零 Docker 即可运行"的契约。
#
# - 在建表之前**必须**显式 ``import src.models``：
#   SQLAlchemy 的声明式表结构只有在对应模型模块被 import 时才会
#   注册到 ``Base.metadata``。如果省略这一步，``Base.metadata.create_all``
#   只会建出一个空 schema，测试运行时会抛 ``no such table`` 之类的
#   错误（Requirement 20.6 明确要求测试会话期间不得出现此类异常）。
#
# - 引擎使用 ``StaticPool`` 并关闭 ``check_same_thread``：
#   ``sqlite:///:memory:`` 的数据只存在于**单一连接**内；若使用默认
#   的 AsyncAdaptedQueuePool，则每个 session 会获得各自的内存库，
#   建表写入的元数据无法被后续 session 读到。``StaticPool`` 保证
#   整个 engine 生命周期内复用同一条底层连接，让 3.5 子任务（FastAPI
#   dependency override）也能看到同一张表。
#
# - ``async_engine`` 作用域设为 ``session`` 以复用"建表"这一次性代价；
#   ``db_session`` 作用域为 function（per-test），保证用例之间的写入互不
#   影响（每个 session 结束时若有写入也会随着事务结束被丢弃，除非显式 commit）。
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture(scope="session")
async def async_engine():
    """构造 session 级的 in-memory SQLite async engine 并建好全部表。

    契约：
    - 返回的 engine 已完成 ``Base.metadata.create_all``，调用方可以直接
      对任意 ORM 模型（``KnowledgeBase`` / ``Document`` / ``DocumentChunk``
      / ``AuditLog``）做 CRUD，而不会遇到 ``no such table``；
    - 整个 test session 结束后通过 ``engine.dispose()`` 释放底层连接池，
      避免 aiosqlite 在事件循环关闭阶段残留资源（Requirement 20.6）。
    """

    # 关键步骤：在建表之前显式 import 模型聚合模块，确保所有 ORM 类
    # 都在 import 时被 ``DeclarativeBase`` 子类 metaclass 注册到
    # ``Base.metadata`` 中。必须在引擎创建后、``create_all`` 之前完成。
    # 使用局部 import：避免 conftest 顶层 import 时污染 collect 阶段的
    # 依赖图（某些单元测试可能不需要 ORM，但一旦本 fixture 被使用则
    # 所有表都会就位）。
    from models.base import Base  # noqa: WPS433  —— 局部 import 属有意为之
    import models  # noqa: F401, WPS433  —— 触发 ORM 类注册到 Base.metadata

    # 创建 async engine：
    # - URL 使用 ``sqlite+aiosqlite:///:memory:`` 得到一个纯内存库；
    # - ``connect_args={"check_same_thread": False}``：aiosqlite 在不同
    #   线程上下文中重用连接时的刚需；
    # - ``poolclass=StaticPool``：保证所有 session 共享同一条底层连接，
    #   从而看到同一张内存数据库里的数据（否则每个 session 都会创建
    #   一个全新的空库）；
    # - ``future=True``：启用 SQLAlchemy 2.x 风格（与生产 engine 对齐）。
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )

    # 一次性建出所有注册到 Base.metadata 的表；``run_sync`` 把
    # 同步的 ``create_all`` 适配到 async 连接。
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        yield engine
    finally:
        # 显式 dispose 以触发 aiosqlite 连接清理，规避 Windows 上
        # 事件循环关闭阶段的 ResourceWarning（Requirement 20.6）。
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(async_engine) -> AsyncSession:
    """为每个测试用例提供独立的 :class:`AsyncSession`。

    设计要点：

    - 会话工厂使用 ``async_sessionmaker`` 绑定到 session 级的
      ``async_engine``，保证所有用例看到同一张内存数据库；
    - ``expire_on_commit=False``：
        * 默认情况下 SQLAlchemy 会在 ``commit()`` 之后把所有 ORM 实例
          标记为 "expired"，下次访问任一字段都会触发额外的 SELECT。
        * 这与 **async** 场景极不友好——属性访问在 async 上下文中不能
          自动触发 lazy-load，会直接抛 ``MissingGreenlet`` 异常。
        * 设为 ``False`` 后，commit 之后实例仍可被测试代码直接读取字段，
          这也是生产 ``async_session_factory``（见 ``core/database.py``）
          采用的相同策略，保持测试行为与生产一致。
    - 通过 ``async with factory() as session`` 确保每个用例结束时自动
      关闭 session，防止连接泄漏；未显式 commit 的写入会被丢弃，
      保证用例之间的数据隔离。
    """

    # 在函数内构造 factory 可避免 fixture 间的共享状态：
    # 每个用例都拿到一个全新的 sessionmaker 实例 → 全新的 session。
    factory = async_sessionmaker(
        async_engine,
        class_=AsyncSession,
        expire_on_commit=False,  # 见上方 docstring 中关于 async 场景的说明
    )
    async with factory() as session:
        yield session


# --------------------------------------------------------------------------- #
# 5. FastAPI fixtures — app 与 async_client
# --------------------------------------------------------------------------- #
# [Anchor: 3.5 FastAPI fixtures]
#
# 说明（对应任务 3.5、Requirement 7.6 / 19.2 / 19.5）：
#
# - ``app`` fixture 从生产代码 ``src/main.py`` 直接导入已构造好的
#   FastAPI 实例，然后通过 ``app.dependency_overrides[get_db]`` 把
#   生产数据库依赖 **切换** 为测试用的 SQLite 会话工厂；这样所有路由
#   里 ``Depends(get_db)``（含经由 ``api.deps.DBSession`` 注解间接
#   依赖的场景）都会命中 3.4 提供的内存数据库，而不会去连真实的
#   PostgreSQL。避免了对生产代码做任何结构性改造（Requirement 19.1 / 19.4）。
#
# - 每个用例结束时 **必须** 调用 ``app.dependency_overrides.clear()``：
#   FastAPI 的 ``dependency_overrides`` 是 **模块级字典**，残留条目会
#   被后续用例看到，从而产生 "上一个测试注入的会话仍在使用"、
#   "MissingGreenlet"、"Session is closed" 等难以复现的 flakiness。
#   在 fixture 拆解（yield 之后）阶段清空，保证跨用例的完全隔离
#   （Requirement 19.2 明确要求）。
#
# - ``async_client`` fixture 使用 ``httpx.AsyncClient`` + ``ASGITransport``：
#   * **进程内 ASGI 驱动**：请求不经过 TCP/socket，httpx 会直接把
#     ASGI scope 喂给 FastAPI 的 app；无需启动 uvicorn，也无需绑定端口，
#     几十毫秒内就能完成一次请求往返，是 CI 上保持整套测试 30 秒内
#     跑完的关键前提（Requirement 9.1 / 9.3）。
#   * ``base_url="http://test"`` 是 httpx ASGITransport 的惯用占位主机名，
#     仅用于拼接完整 URL；真实网络并不会被触发。
#   * 使用 ``async with`` 语法确保 client 关闭时正确释放底层异步资源，
#     避免 Windows 事件循环关闭阶段出现 ResourceWarning（Requirement 20.6）。
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def app(async_engine):
    """构造带 ``dependency_overrides`` 的 FastAPI 实例供 API 契约测试使用。

    契约：
    - 返回的 app 实例已把 ``core.database.get_db`` 覆写为"基于内存 SQLite
      的 async session 生成器"：
        * 与生产 ``get_db`` 的行为一致——请求成功则 ``commit()``，异常则
          ``rollback()``，退出时关闭 session；
        * 所有 session 共享同一个 session 级 ``async_engine``，也就是
          3.4 里由 ``StaticPool`` 固定的那条内存连接，因此路由看到的
          数据与 ``db_session`` fixture 内测试代码操作的数据是 **同一份**。
    - fixture 拆解阶段显式清空 ``dependency_overrides``，防止后续用例
      意外复用本次注入（Requirement 19.2）。

    参数：
    - ``async_engine``：3.4 提供的 session 级 in-memory engine；此处仅
      用它构造 session factory，不直接触碰引擎底层连接。
    """

    # 延迟 import 生产模块：
    #   - 之所以放到函数体而非文件顶部，是为了让 conftest 在 pytest
    #     collect 阶段不会强制 import ``main``（进而 import 整条生产
    #     依赖链），确保单元测试等不需要 FastAPI 的用例也能快速 collect
    #     完成（Requirement 9.1 的 30 秒预算要靠这类细节攒出来）。
    #   - ``noqa: WPS433`` —— 本文件允许局部 import。
    from main import app as fastapi_app  # noqa: WPS433
    from core.database import get_db  # noqa: WPS433

    # 构造绑定到测试 engine 的 session factory；``expire_on_commit=False``
    # 与生产 ``async_session_factory``（见 core/database.py）保持一致，
    # 避免 commit 后访问 ORM 字段触发 async 场景下的 lazy-load 异常
    # （即 MissingGreenlet）。详见 3.4 ``db_session`` fixture 的 docstring。
    factory = async_sessionmaker(
        async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def _override_get_db():
        """覆写后的 ``get_db``：复刻生产语义但改用内存数据库。

        行为对照（与 ``src/core/database.py::get_db`` 对齐）：
        - 正常路径：yield session → 请求处理器完成 → ``await commit()``；
        - 异常路径：捕获后 ``await rollback()`` 再重新抛出；
        - 最终一定调用 ``session`` 的上下文管理器关闭连接，释放资源。
        """
        # async with 确保即便请求处理器抛出未捕获异常，session 也会被
        # aiosqlite 正常关闭，不会泄漏底层连接。
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                # 任何路由/依赖链内的异常都回滚，保证用例之间互不污染。
                await session.rollback()
                raise

    # 注入覆写：key 必须使用生产 ``get_db`` 的原始函数对象，FastAPI
    # 的 dependency_overrides 是基于函数身份比对的。
    fastapi_app.dependency_overrides[get_db] = _override_get_db
    try:
        yield fastapi_app
    finally:
        # 清空所有覆写（不是只删我们注入的那一条）：
        # - 这样 3.6 的 Fakes 注入 fixtures 以及后续用例/任务追加的
        #   其它 dependency_overrides 也会在每个用例结束时被一并复原，
        #   避免"上一个用例的桩"泄露到下一个用例。
        fastapi_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def async_client(app):
    """进程内 ASGI 驱动的 ``httpx.AsyncClient``，用于发起 API 契约请求。

    设计要点：

    - **不启动 uvicorn**：``ASGITransport(app=app)`` 让 httpx 直接把请求
      投递给 FastAPI 的 ASGI app，调用栈全程在同一进程同一事件循环内
      完成，因此：
        * 无需分配端口、也不会与本机其它服务冲突；
        * 请求延迟在微秒量级，帮助整套 API 契约测试在 Requirement 9.3
          要求的 10 秒预算内完成；
        * Windows 上无需处理 Proactor 事件循环下的 socket 兼容问题
          （Requirement 20.3）。

    - ``base_url="http://test"``：ASGITransport 要求一个占位主机名用于
      拼接绝对 URL，测试代码里即可写相对路径（如 ``"/api/v1/knowledge-bases"``）
      而无需关心 host。``http://test`` 是社区惯例，也不会误导读者
      以为真的发起了外部网络请求。

    - ``async with`` 自动 close：httpx 的 AsyncClient 在退出上下文时会
      关闭底层传输，释放未完成的流式响应；这对 Windows 下
      ``WindowsSelectorEventLoopPolicy`` 的事件循环关闭顺序尤为关键
      （Requirement 20.6）。
    """

    # 局部 import：同 ``app`` fixture 的考量，避免在 collect 阶段强制
    # 拉入 httpx；只有真正用到本 fixture 的 API 层测试才会付出这份
    # import 代价。
    from httpx import AsyncClient, ASGITransport  # noqa: WPS433

    # 构造进程内 ASGI 传输：不经过网络栈，直接与 FastAPI 的 ASGI 协议层
    # 对话。此处的 app 已经包含 3.5 注入的 dependency_overrides。
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # yield 后由 pytest-asyncio 驱动用例执行；退出上下文时 httpx
        # 会负责 flush 和关闭底层连接池。
        yield client


# --------------------------------------------------------------------------- #
# 6. 后续子任务的 fixtures 追加锚点
# --------------------------------------------------------------------------- #
# 下列一块由 3.6 子任务 append 到本文件末尾，请保持注释标题以便追加
# 脚本定位（切勿删除下方占位说明）：
#
# [Anchor: 3.6 Fakes 注入 fixtures]
#   - fake_embedding / fake_dense / fake_sparse / fake_reranker /
#     fake_query_rewriter / fake_deepseek；
#   - 组合 fixture ``wired_pipeline`` 与 ``seeded_kb``。
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# 6. Fakes 注入 fixtures — 通过 monkeypatch 替换生产模块级单例
# --------------------------------------------------------------------------- #
# [Anchor: 3.6 Fakes 注入 fixtures]
#
# 说明（对应任务 3.6、Requirement 3.1 / 3.5 / 19.1 / 19.3 / 19.5）：
#
# 本块提供"端口-适配器"模式下的 **6 个单体 Fake fixture** 与 **2 个组合
# fixture**：
#
#   单体：fake_embedding / fake_dense / fake_sparse / fake_reranker /
#         fake_query_rewriter / fake_deepseek
#   组合：wired_pipeline（5 个检索管线 Fakes 一键接入）、
#         seeded_kb（基于 wired_pipeline 把样例 chunk seed 到内存 dense/sparse）
#
# 全部通过 ``monkeypatch.setattr(module, attr, fake_instance)`` 注入；
# pytest 会在用例结束时自动回滚 monkeypatch，因此不需要写 teardown
# （与 Requirement 19.1 "不修改生产代码" 配合，实现零侵入替换）。
#
# 作用域选择：
#   - 全部声明为 **function 级**（pytest 默认作用域）。原因：
#     ① monkeypatch 本身就是 function-scoped，更高作用域会报错；
#     ② 每个用例拿到全新 Fake 实例，避免 ``calls`` 调用日志、
#       ``store`` 内存数据跨用例串味（Requirement 18.3 的确定性前提）。
#
# 注入点清单（与 ``eval/profiles/lite.py::install`` 对齐，便于一致性维护）：
#   - ``services.retrieval.retriever.embedding_service``   ← FakeEmbeddingService
#   - ``services.ingestion.embedder.embedding_service``    ← FakeEmbeddingService
#     （ingest 路径也用到 embedding_service 单例；两处同步替换才能保证
#      "retrieve 用 Fake 向量、ingest 也用 Fake 向量"这一对称性，
#      否则 seeded_kb 与 retrieve 的向量会来自不同来源）
#   - ``services.retrieval.retriever.dense_searcher``      ← InMemoryDenseSearcher
#   - ``services.retrieval.retriever.sparse_searcher``     ← InMemorySparseSearcher
#   - ``services.retrieval.retriever.reranker_service``    ← FakeRerankerService
#   - ``services.retrieval.retriever.query_rewriter``      ← FakeQueryRewriter
#   - ``api.v1.chat.deepseek_chat``                        ← FakeDeepSeekChat
#
# 如果未来生产模块重构（例如把模块级单例改成工厂函数），``monkeypatch.setattr``
# 会以 ``AttributeError`` 明确失败，而不是悄悄走回真实 I/O 路径（Requirement 19.5）。
# --------------------------------------------------------------------------- #


@pytest.fixture
def fake_embedding(monkeypatch):
    """注入 :class:`FakeEmbeddingService` 到 retrieve 与 ingest 两处 embedding 单例。

    作用域：function。每个用例拿到一个全新的 Fake 实例，其 ``calls`` 调用日志
    从空列表开始累积，便于测试精确断言 "embedding 是否被调用、被调用了几次、
    入参是什么"（Requirement 6.3 的 "空 query 不得触发 embedding 批量调用"
    依赖这一点）。

    注入点（Requirement 19.1 / 19.3）：

    - ``services.retrieval.retriever.embedding_service``：检索路径读取的单例
    - ``services.ingestion.embedder.embedding_service``：入库路径读取的单例

    两处同步替换，保证 "同一条 content 在 ingest 与 retrieve 时得到同一向量"
    —— 这是 ``seeded_kb`` 能在 Fake 稠密检索器里被正确命中的前提。

    拆解行为：monkeypatch 在用例结束时自动还原生产单例；本 fixture 不需要
    显式写 teardown 代码。
    """

    # 局部 import：与 app / async_client 同样的考量 —— 避免 collect 阶段
    # 强制拉起 tests.fakes 整条 import 链，保持 collect 快速。
    from tests.fakes.embedding import FakeEmbeddingService  # noqa: WPS433

    # 每个用例新建实例 → calls/内部状态彻底隔离
    fake = FakeEmbeddingService()

    # 注入点 1：检索路径
    # 生产 retriever.py 通过 ``from ... import embedding_service`` 把单例
    # 绑定到自身模块命名空间，因此必须在 retriever 模块上重新赋值，
    # 仅改源头模块不会影响已被绑定的引用。
    monkeypatch.setattr(
        "services.retrieval.retriever.embedding_service", fake
    )
    # 注入点 2：入库路径（ingest → embedder）
    # Embedder 也以模块级单例形式暴露向量化服务；若不在这里同步替换，
    # seeded_kb 会走 Fake 向量，而 retrieve 命中时又走 Fake 向量 —— 看似
    # 一致，但 ingestion 链路其它测试（如 test_ingestion_pipeline）会
    # 触发真实 HTTP 调用。两处同步替换是最稳妥的做法。
    monkeypatch.setattr(
        "services.ingestion.embedder.embedding_service", fake
    )

    return fake


@pytest.fixture
def fake_dense(monkeypatch):
    """注入 :class:`InMemoryDenseSearcher` 到 ``services.retrieval.retriever``。

    作用域：function。每个用例获得独立的内存 ``store``，测试可通过
    ``fake_dense.seed(kb_id, records)`` 预置数据；``fake_dense.search(...)``
    以 cosine 相似度打分返回 top_k 命中。

    注入点（Requirement 19.1 / 19.3）：

    - ``services.retrieval.retriever.dense_searcher``
      —— 生产 Retriever 内部读取的稠密检索单例（生产实现为 Milvus 客户端）。

    拆解行为：monkeypatch 自动还原；每个用例开始时 ``fake.store == {}``，
    天然满足测试隔离。
    """

    # 局部 import 保持 collect 快速；避免 tests.fakes.dense_searcher 被
    # 不需要它的测试用例间接拉起。
    from tests.fakes.dense_searcher import InMemoryDenseSearcher  # noqa: WPS433

    # 全新实例 → 内存 store/调用日志从零开始，跨用例完全隔离
    fake = InMemoryDenseSearcher()

    # 仅替换 retriever 模块引用的 dense_searcher；不动 dense_searcher 源头模块，
    # 以免同一进程内其它可能 import 到源头模块的消费者被意外影响
    # （当前仅 retriever 一处，但显式保持最小影响面是更安全的选择）。
    monkeypatch.setattr(
        "services.retrieval.retriever.dense_searcher", fake
    )

    return fake


@pytest.fixture
def fake_sparse(monkeypatch):
    """注入 :class:`InMemorySparseSearcher` 到 ``services.retrieval.retriever``。

    作用域：function。Fake 以词元重叠作为 BM25 替身的打分函数；
    每次 ``search`` 调用都会记录到 ``fake.calls``，集成测试据此断言
    "``use_hybrid=False`` 时 sparse_searcher.search 未被调用"
    （Requirement 3.2）。

    注入点（Requirement 19.1 / 19.3）：

    - ``services.retrieval.retriever.sparse_searcher``
      —— 生产 Retriever 内部读取的稀疏检索单例（生产实现为 PG BM25）。

    拆解行为：monkeypatch 自动还原；每个用例 ``fake.calls == []``、
    ``fake.store == {}``。
    """

    # 局部 import：保持 collect 阶段轻量
    from tests.fakes.sparse_searcher import InMemorySparseSearcher  # noqa: WPS433

    # 全新实例 → calls 调用日志与 store 都从零开始
    fake = InMemorySparseSearcher()

    # 仅替换 retriever 引用；其它路径暂无消费者
    monkeypatch.setattr(
        "services.retrieval.retriever.sparse_searcher", fake
    )

    return fake


@pytest.fixture
def fake_reranker(monkeypatch):
    """注入 :class:`FakeRerankerService` 到 ``services.retrieval.retriever``。

    作用域：function。Fake 严格保证 "仅重打分、不引入新候选" —— 输出
    ``chunk_id`` 集合必为输入 ``candidates`` 的 ``chunk_id`` 集合的子集
    （Requirement 4.1 / 4.2）；这是集成与属性测试的关键契约。

    注入点（Requirement 19.1 / 19.3）：

    - ``services.retrieval.retriever.reranker_service``
      —— 生产 Retriever 内部读取的重排单例（生产实现为 BGE-Reranker HTTP 客户端）。

    拆解行为：monkeypatch 自动还原。
    """

    # 局部 import
    from tests.fakes.reranker import FakeRerankerService  # noqa: WPS433

    # 每次一个新实例（Fake 本身无状态，但保持与其它 fake 一致的构造节奏）
    fake = FakeRerankerService()

    # 仅替换 retriever 引用
    monkeypatch.setattr(
        "services.retrieval.retriever.reranker_service", fake
    )

    return fake


@pytest.fixture
def fake_query_rewriter(monkeypatch):
    """注入 :class:`FakeQueryRewriter` 到 ``services.retrieval.retriever``。

    作用域：function。默认以恒等变换工作（``rewrite(q) -> [q]``），
    测试如需验证 "多变体命中同一 chunk 时最终结果去重"（Requirement 3.4），
    可以直接在用例内改写 ``fake.variants``（需要先重建实例或
    ``monkeypatch.setattr`` 一个带 variants 的新实例，**不要**在用例里
    直接修改只读属性）。

    注入点（Requirement 19.1 / 19.3）：

    - ``services.retrieval.retriever.query_rewriter``
      —— 生产 Retriever 内部读取的查询改写单例（生产实现为 DeepSeek 客户端）。

    拆解行为：monkeypatch 自动还原。
    """

    # 局部 import
    from tests.fakes.query_rewriter import FakeQueryRewriter  # noqa: WPS433

    # 默认恒等变换；测试如需注入额外变体可构造 FakeQueryRewriter(variants=[...])
    # 并再次 monkeypatch.setattr 覆盖
    fake = FakeQueryRewriter()

    # 仅替换 retriever 引用
    monkeypatch.setattr(
        "services.retrieval.retriever.query_rewriter", fake
    )

    return fake


@pytest.fixture
def fake_deepseek(monkeypatch):
    """注入 :class:`FakeDeepSeekChat` 到 ``api.v1.chat``。

    作用域：function。Fake 返回罐头 ``ChatResponse``（``answer`` 含上下文
    摘要、``citations`` 由 context_chunks 派生、``content`` 截断到 200 字符）
    以及最小化 SSE stream delta，**永不发起真实网络请求**
    （Requirement 7.4 / 9.5）。

    注入点（Requirement 19.1 / 19.3）：

    - ``api.v1.chat.deepseek_chat`` —— 生产 chat 路由里通过
      ``from services.generation.deepseek_chat import deepseek_chat`` 绑定
      的单例；路由里有非流式 ``deepseek_chat.generate(...)`` 与流式
      ``deepseek_chat.generate_stream(...)`` 两条分支，两条分支都由本
      Fake 覆盖。

    拆解行为：monkeypatch 自动还原；``fake.calls`` 在下一用例自动清零。
    """

    # 局部 import：保持 collect 快速；避免 tests.fakes.deepseek 被
    # 不需要对话功能的单元测试间接拉起
    from tests.fakes.deepseek import FakeDeepSeekChat  # noqa: WPS433

    # 每个用例一个全新实例 → calls 调用日志从零开始
    fake = FakeDeepSeekChat()

    # 路由里以名字 ``deepseek_chat`` 绑定；必须在 ``api.v1.chat`` 模块上
    # 重新赋值，而不是去改源头 ``services.generation.deepseek_chat``
    # （那里的单例已被 chat.py 在 import 时拷贝到自己的命名空间）
    monkeypatch.setattr("api.v1.chat.deepseek_chat", fake)

    return fake


# --------------------------------------------------------------------------- #
# 组合 fixture — wired_pipeline：一键接入检索管线所需的 5 个 Fakes
# --------------------------------------------------------------------------- #
@pytest.fixture
def wired_pipeline(
    fake_embedding,
    fake_dense,
    fake_sparse,
    fake_reranker,
    fake_query_rewriter,
):
    """一次性装配 ``Retriever.retrieve(...)`` 所需的 5 个 Fakes。

    作用域：function（与依赖的 5 个单体 fake fixture 一致）。

    设计动机：
    - 检索管线的绝大多数集成测试同时依赖 embedding / dense / sparse /
      reranker / query_rewriter 五个 Fake；如果每个用例显式声明这 5 个
      fixture，写法冗长且容易遗漏。本组合 fixture 作为一个 "打包入口"，
      测试只需 ``async def test_xxx(wired_pipeline, ...)`` 即可完成注入。
    - 返回一个 dict 暴露 5 个实例（键名与 ``eval/profiles/lite.py``
      ``build_adapters()`` 对齐：``embedding / dense / sparse / reranker /
      query_rewriter``），便于测试直接断言 ``wired_pipeline["sparse"].calls``
      这类调用日志，避免再依赖单体 fake fixture。

    不包含 ``fake_deepseek``：对话路径仅出现在 ``test_chat_api.py`` 一处，
    与检索管线测试正交，刻意不合并以免所有管线测试都被迫 import DeepSeek
    Fake。

    拆解行为：5 个单体 fake fixture 自行通过 monkeypatch 还原，无额外清理。
    """

    # 字典键顺序与 lite.py build_adapters() 对齐，便于读者对照 profiles
    # 与测试接线的一致性
    return {
        "embedding": fake_embedding,
        "dense": fake_dense,
        "sparse": fake_sparse,
        "reranker": fake_reranker,
        "query_rewriter": fake_query_rewriter,
    }


# --------------------------------------------------------------------------- #
# 组合 fixture — seeded_kb：把样例 chunk seed 到内存 dense/sparse 检索器
# --------------------------------------------------------------------------- #
@pytest_asyncio.fixture
async def seeded_kb(wired_pipeline):
    """向 Fake dense/sparse 存储预置 5 条中文 chunk，返回 kb 元信息与 Fakes 引用。

    作用域：function（组合 fixture，继承 ``wired_pipeline`` 的 function 作用域）。

    行为拆解：

    1. 从 :mod:`tests.fixtures.seeded_kb` 调用
       :func:`build_seed_records(kb_id, fake_embedding)`：生成 5 条跨 3 个
       document 的中文 chunk，并为每条 content 计算 Fake 向量（等价于
       ``await fake_embedding.embed_single(r["content"])``，顺序稳定以满足
       Requirement 18.4）。
    2. 把**完整 record**（含 ``embedding`` 字段）同时 seed 到 ``fake_dense``
       与 ``fake_sparse`` 的内存 store；dense 走 cosine，sparse 走词元重叠，
       两路互不干扰。
    3. 返回一个字典，暴露 ``kb_id`` / 完整 ``records`` 列表 / 以及三个核心
       Fake 实例，便于用例直接断言（例如
       ``assert seeded_kb["dense"].store["eval-kb"][0]["embedding"]``）。

    返回值 schema:

        {
            "kb_id": "eval-kb",
            "records": list[dict],        # 含 embedding 的完整记录
            "embedding": FakeEmbeddingService,
            "dense":     InMemoryDenseSearcher,
            "sparse":    InMemorySparseSearcher,
        }

    kb_id 固定为 ``"eval-kb"`` ——  与 ``eval/config.py::RunConfig.kb_id``
    默认值一致，便于评测 runner 与集成测试共用同一套样例数据
    （Requirement 3.1 / 3.5）。

    拆解行为：无需显式清理 —— ``fake_dense`` / ``fake_sparse`` 的 store 由
    monkeypatch 拆解时连同 Fake 实例一起被回收（下一个用例会拿到全新 Fake
    实例，内存 store 自然清空）。
    """

    # 局部 import：避免 collect 阶段拉起 models/embedding 整条依赖链
    from tests.fixtures.seeded_kb import build_seed_records  # noqa: WPS433

    # 固定 kb_id 为 "eval-kb"：与 eval/config.py 默认 kb_id 对齐
    # 评测 profile (lite) 与集成测试共用同一套样例数据，降低认知负担
    kb_id = "eval-kb"

    # 取三个核心 Fake 实例：embedding 用于计算向量，dense/sparse 用于 seed
    fake_embedding = wired_pipeline["embedding"]
    fake_dense = wired_pipeline["dense"]
    fake_sparse = wired_pipeline["sparse"]

    # build_seed_records 内部会按 record 顺序依次调用 embed_single，
    # 返回每条 record 追加 "embedding" 字段后的新字典列表；
    # 稳定顺序 + 确定性 embedding → 跨用例/跨运行完全可复现
    records = await build_seed_records(kb_id, fake_embedding)

    # 同一批 record 同时喂给 dense 与 sparse：
    # - dense.seed 利用 record["embedding"] 做 cosine 相似度打分
    # - sparse.seed 利用 record["content"] 做词元重叠打分
    # 这样一次 seed 就能覆盖 hybrid 检索的两路输入
    fake_dense.seed(kb_id, records)
    fake_sparse.seed(kb_id, records)

    # 返回字典暴露 kb 元信息 + 3 个核心 Fake 引用；
    # 用例既可以通过 seeded_kb["records"] 拿到完整样例，也可以通过
    # seeded_kb["dense"].store[kb_id] 直接窥探内存存储
    return {
        "kb_id": kb_id,
        "records": records,
        "embedding": fake_embedding,
        "dense": fake_dense,
        "sparse": fake_sparse,
    }


# --------------------------------------------------------------------------- #
# [Anchor: 章节收尾] 后续子任务如需新增 fixtures，请在此锚点下方继续追加，
# 保持本文件的"基础块 → 数据库块 → FastAPI 块 → Fakes 块 → 可扩展块"
# 层次结构，便于未来脚本化追加时定位。
# --------------------------------------------------------------------------- #
