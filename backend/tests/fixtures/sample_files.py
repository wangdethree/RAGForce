"""样例文件字节串工厂（运行时在内存中生成 PDF / DOCX）。

本模块为测试套件提供两枚纯函数：

- :func:`make_sample_pdf_bytes` —— 使用 ``reportlab.pdfgen.canvas`` 在
  ``io.BytesIO`` 中生成 1 页 PDF 并返回 ``bytes``。生成的 PDF 必须能被
  ``pymupdf``（``fitz``）正常打开，并抽取到传入的 ``text`` 文本。
- :func:`make_sample_docx_bytes` —— 使用 ``python-docx`` 在 ``io.BytesIO``
  中生成包含单一段落的 DOCX 文档并返回 ``bytes``。

设计约束（对应 Requirements 9.6 / 8.5 / 19.6）：

- 仓库中 **SHALL NOT** 提交任何 PDF / DOCX 二进制样例，样例一律由测试在
  运行时按需生成（Requirement 9.6）。
- 全流程只走 ``io.BytesIO``，在 Windows 上也不触碰磁盘 I/O，不依赖
  系统字体包之外的资源（Requirement 20 / 9.6）。
- 仅引入 dev extras 中声明的依赖（``reportlab`` / ``python-docx``），
  不触碰生产业务代码（Requirement 19.6）。

中文渲染说明
------------
``reportlab`` 的默认 Type 1 字体（Helvetica 等）**不支持** CJK 码位，
直接写中文会在 PDF 内容流中退化为方块 / 空字符，导致 ``pymupdf``
抽不到原文。为此本模块在首次调用 :func:`make_sample_pdf_bytes` 时
注册 reportlab 自带的 Adobe CID 字体 ``STSong-Light`` 搭配
``UniGB-UCS2-H`` 编码（reportlab 发行包自带，无需系统字体），即可
正确渲染简体中文并被 ``fitz`` 抽文还原。
"""

from __future__ import annotations

import io
import threading

# —— reportlab / python-docx 均位于 [project.optional-dependencies].dev ——
# 若调用方未安装 dev extras，这里的 ImportError 会明确暴露出来，
# 提示用户安装 ``pip install -e .[dev]``。
from reportlab.pdfbase import pdfmetrics  # type: ignore[import-untyped]
from reportlab.pdfbase.cidfonts import UnicodeCIDFont  # type: ignore[import-untyped]
from reportlab.pdfgen import canvas  # type: ignore[import-untyped]
from reportlab.lib.pagesizes import A4  # type: ignore[import-untyped]

from docx import Document  # type: ignore[import-untyped]


# ---- 中文字体注册（懒加载 + 线程安全） ----
# reportlab 的字体注册表是进程级全局状态，重复注册会浪费开销，
# 因此用一个 once-guard 保证全进程只注册一次。
_CJK_FONT_NAME = "STSong-Light"
_CJK_FONT_REGISTERED = False
_CJK_FONT_LOCK = threading.Lock()


def _ensure_cjk_font() -> str:
    """确保 reportlab CID 中文字体已注册，返回字体名。

    使用 reportlab 随包自带的 Adobe CID 资源（``STSong-Light`` +
    ``UniGB-UCS2-H``），无需依赖任何系统字体文件；即使在 Windows /
    Linux 裸环境下也能工作。
    """
    global _CJK_FONT_REGISTERED
    if _CJK_FONT_REGISTERED:
        return _CJK_FONT_NAME
    with _CJK_FONT_LOCK:
        if not _CJK_FONT_REGISTERED:  # 双重检查
            # 注册基于 reportlab 内置 CID 资源的简体中文字体
            pdfmetrics.registerFont(UnicodeCIDFont(_CJK_FONT_NAME))
            _CJK_FONT_REGISTERED = True
    return _CJK_FONT_NAME


def make_sample_pdf_bytes(text: str = "示例 PDF 内容") -> bytes:
    """在内存中生成一页 PDF 并返回其字节串。

    :param text: 要写入 PDF 的一行正文；默认 ``"示例 PDF 内容"``。
    :return: PDF 文件的完整字节串，调用方可直接喂给 ``fitz.open(stream=...)``
        或作为 FastAPI ``UploadFile`` 的 multipart payload 上传。

    行为契约：

    - 生成结果必须能被 ``pymupdf`` 打开：``fitz.open(stream=b, filetype="pdf")``。
    - 页面大小固定为 A4；文本写在左上角一个稳定的基线位置，便于
      抽文测试断言其出现在 ``page.get_text()`` 的输出中。
    - 若 ``text`` 包含 CJK 字符，将通过 :func:`_ensure_cjk_font` 注册的
      ``STSong-Light`` + ``UniGB-UCS2-H`` 渲染；纯 ASCII 文本也会使用
      该字体，以保证单一渲染路径、结果可复现。
    - 全流程只使用 ``io.BytesIO``，不触碰磁盘 I/O（Requirement 9.6 / 20）。
    """
    font_name = _ensure_cjk_font()

    # 用内存缓冲承载 PDF 字节，避免 Windows 上的临时文件与字体缓存问题
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setFont(font_name, 14)

    # (x, y) 使用 reportlab 默认坐标系（原点在左下角，单位 pt）；
    # 选 72pt（≈1 英寸）的边距与 A4 顶部距离，文本落在可视区域内
    _, page_height = A4
    pdf.drawString(72, page_height - 72, text)

    # 明确 showPage + save：showPage 结束当前页并将其写入 PDF，
    # save 刷写交叉引用表与文件尾，产出完整合法的 PDF 结构
    pdf.showPage()
    pdf.save()

    return buffer.getvalue()


def make_sample_docx_bytes(text: str = "示例 DOCX 内容") -> bytes:
    """在内存中生成一个 DOCX 文档并返回其字节串。

    :param text: 要写入段落的正文；默认 ``"示例 DOCX 内容"``。
    :return: DOCX 文件的完整字节串（本质是一个 ZIP 包），
        可直接作为 multipart 上传体或喂给 ``python-docx`` 再次解析。

    行为契约：

    - 使用 ``python-docx`` 的 ``Document`` 对象构造，最终通过
      ``document.save(buffer)`` 写入 ``io.BytesIO``，不触碰磁盘。
    - 文档至少包含一个段落，其 ``text`` 等于入参 ``text``；调用方
      可据此进行抽文 / 检索相关断言。
    - DOCX 内部默认样式（Calibri 等）在渲染层面不支持中文时不影响
      **文本抽取**：``python-docx`` 与 pymupdf-docx / mammoth 都能
      从 ``w:t`` 元素读回原字符串，因此中文兜底无需额外字体注册。
    """
    document = Document()
    document.add_paragraph(text)

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


__all__ = [
    "make_sample_pdf_bytes",
    "make_sample_docx_bytes",
]
