"""评测包的模块入口 —— 使 ``python -m eval.run`` 等价于调用 :func:`eval.run.main`。

本文件刻意保持**最薄**：仅做两件事：

1. 从 :mod:`eval.run` 导入 :func:`main`。
2. 以 ``raise SystemExit(main())`` 把 ``main()`` 的返回值（Unix 风格 exit code）
   透传给 Python 解释器，让 CLI 使用者通过 ``$?`` / ``%ERRORLEVEL%`` 拿到退出码。

之所以不在这里放任何业务逻辑：

- ``main()`` 已经在 :mod:`eval.run` 里封装好参数解析、事件循环策略、异常映射
  等所有入口职责，`__main__` 没有必要重复或二次包裹。
- 保持这里只剩一个入口调用，也让 ``python -m eval`` 与 ``python -m eval.run``
  两种启动方式的行为严格一致（Requirement 16.1）。
"""

from eval.run import main

# SystemExit 将 main 的返回值作为进程退出码传给解释器：
# - 0  成功（Requirement 16.7）
# - 2  参数/数据集错误（Requirement 16.8）
# - 3  运行期错误（Requirement 16.9）
# KeyboardInterrupt 由 main 原样抛出，因此本行不会捕获它，Python 默认 exit 130。
raise SystemExit(main())
