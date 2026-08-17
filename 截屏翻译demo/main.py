"""屏幕翻译 Demo 主程序（Windows 桌面端）。

流程：用户框选屏幕区域 → 截图 → OCR 识别文字块 → DeepSeek 逐块翻译 →
全屏点击穿透覆盖层在原文位置绘制译文块（Gaminik 式就地贴图融入画面）。

启动：
    python main.py
"""

import sys
import threading

import mss
import numpy as np
from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QKeySequence,
    QPainter,
    QPen,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import config
from ocr import ScreenOCR
from translator import DeepSeekTranslator


# ---------------------------------------------------------------------------
# 后台流水线：截图 -> OCR 文字块 -> 逐块翻译 -> 带坐标的译文块
# ---------------------------------------------------------------------------
def _run_pipeline(ocr, translator, region, win):
    """在后台线程执行 截图->OCR->逐块翻译，结果通过主窗口信号回传。

    得到的每个译文块带全屏坐标，由主线程在对应位置绘制就地覆盖层。
    """
    try:
        with mss.mss() as sct:
            monitor = {
                "left": region["left"],
                "top": region["top"],
                "width": region["width"],
                "height": region["height"],
            }
            shot = sct.grab(monitor)
            img = np.array(shot)

        boxes = ocr.recognize_boxes(img)
        blocks = []
        for box in boxes:
            text = (box.text or "").strip()
            if not text:
                continue
            try:
                translated = translator.translate(text)
            except Exception as exc:  # noqa: BLE001
                translated = f"(译:{exc})"
            # 坐标平移到全屏坐标系
            blocks.append(
                {
                    "left": region["left"] + box.left,
                    "top": region["top"] + box.top,
                    "right": region["left"] + box.right,
                    "bottom": region["top"] + box.bottom,
                    "source": text,
                    "text": (translated or "").strip() or "(无)",
                }
            )

        win.pipelineDone.emit(blocks)
    except Exception as exc:  # noqa: BLE001
        win.pipelineFailed.emit(str(exc))


def start_pipeline(win, region):
    """启动后台翻译流水线，结果通过 win.pipelineDone/pipelineFailed 信号回传主线程。"""
    threading.Thread(
        target=_run_pipeline,
        args=(win.ocr, win.translator, region, win),
        daemon=True,
    ).start()


def _is_trunc(block, min_font=10):
    """判断译文在当前文字块内是否放得下。

    以最小可读字号 min_font 度量译文宽度，超过可用宽度判定为"放不下"，
    需要折叠成省略标记并走详情面板查看完整译文。
    """
    w = max(block["right"] - block["left"], 10)
    h = max(block["bottom"] - block["top"], 10)
    font_size = min(int(h * 0.72), min_font)
    fm = QFontMetrics(QFont("Microsoft YaHei", font_size))
    return fm.horizontalAdvance(block["text"]) > w - 6


# ---------------------------------------------------------------------------
# 详情面板：完整译文列表面板（原文 ↔ 译文），可打开/关闭
# ---------------------------------------------------------------------------
class DetailWindow(QMainWindow):
    """可开关的完整译文详情面板，配合覆盖层里的"⋯"省略标记使用。"""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.blocks = []
        self._build_ui()

    def _build_ui(self):
        panel = QWidget()
        panel.setObjectName("panel")
        panel.setStyleSheet(
            "#panel { background: rgba(18, 22, 34, 242); border: 1px solid #3a4458;"
            " border-radius: 14px; }"
        )
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(10)

        # 标题
        header = QHBoxLayout()
        title = QLabel("📋 译文明细")
        title.setStyleSheet("color:#6fb3ff; font-size:14px; font-weight:bold;")
        close_btn = QPushButton("✕ 关闭")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet(
            "QPushButton { color:#c6d0e6; background:rgba(255,255,255,0.06);"
            " border:1px solid #3a4458; border-radius:6px; font-size:12px; }"
            "QPushButton:hover { color:#ff6b6b; }"
        )
        close_btn.clicked.connect(self.hide)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(close_btn)
        layout.addLayout(header)

        self.body = QLabel("")
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.body.setStyleSheet(
            "color:#d4dbf0; font-size:12px; background:transparent;"
        )
        layout.addWidget(self.body)

        self.setCentralWidget(panel)
        self._drag = None

    def set_blocks(self, blocks):
        self.blocks = blocks
        rows = []
        for i, blk in enumerate(blocks, 1):
            src = blk.get("source", "")
            dst = blk.get("text", "")
            rows.append(
                f"[{i}] 原文：{src}\n    译文：{dst}\n"
            )
        self.body.setText("\n".join(rows) if rows else "（无内容）")
        self.adjustSize()

    # 让详情面板也可拖动
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, event):
        self._drag = None


# ---------------------------------------------------------------------------
# 框选层
# ---------------------------------------------------------------------------
class OverlayWindow(QMainWindow):
    """全屏透明框选层：鼠标拖拽出一个矩形区域。"""

    regionSelected = Signal(dict)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.CrossCursor)
        self.setGeometry(QApplication.primaryScreen().geometry())
        self._start = None
        self._current = None

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 60))
        if self._start and self._current:
            pen = QPen(QColor(*config.SELECT_COLOR))
            pen.setWidth(2)
            painter.setPen(pen)
            rect = QRect(self._start, self._current).normalized()
            painter.drawRect(rect)

    def _to_region_dict(self):
        rect = QRect(self._start, self._current).normalized()
        return {
            "left": rect.left(),
            "top": rect.top(),
            "width": rect.width(),
            "height": rect.height(),
        }

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._start = event.position().toPoint()
            self._current = self._start

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._start:
            self._current = event.position().toPoint()
            self.update()

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton and self._start:
            self._current = event.position().toPoint()
            region = self._to_region_dict()
            if region["width"] > 5 and region["height"] > 5:
                self.regionSelected.emit(region)
        self._start = None
        self._current = None


# ---------------------------------------------------------------------------
# 就地覆盖层：在原文位置绘制译文块
# ---------------------------------------------------------------------------
class InkTextWindow(QMainWindow):
    """全屏点击穿透覆盖层，把译文块"印"到屏幕上对应位置。

    译文块采用不透明深色背景 + 自动适配字号，遮住原文字。
    通过 WA_TransparentForMouseEvents 让鼠标点击穿透，不干扰下方应用。
    """

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setGeometry(QApplication.primaryScreen().geometry())
        self.blocks = []

    def set_blocks(self, blocks):
        self.blocks = blocks
        self.update()
        self.show()
        self.raise_()

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        for blk in self.blocks:
            x, y = blk["left"], blk["top"]
            w = max(blk["right"] - blk["left"], 10)
            h = max(blk["bottom"] - blk["top"], 10)
            rect = QRect(x, y, w, h)

            # 不透明背景块，遮住原文
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(20, 24, 35, 245))
            painter.drawRoundedRect(rect.adjusted(0, 0, -1, -1), 4, 4)

            # 深色描边，更像"贴上去"的补丁
            painter.setPen(QPen(QColor(60, 70, 95, 255), 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect.adjusted(1, 1, -2, -2), 4, 4)

            if blk.get("truncated"):
                # 译文过长，块内放不下 -> 折叠成省略标记，完整内容看详情面板
                fm = QFontMetrics(QFont("Microsoft YaHei", 10))
                ellipsis = "⋯"
                if fm.horizontalAdvance(ellipsis) > w - 6:
                    ellipsis = "·"
                painter.setPen(QColor(120, 200, 255, 220))
                painter.setFont(QFont("Microsoft YaHei", max(int(h * 0.6), 9)))
                painter.drawText(
                    rect, Qt.AlignCenter | Qt.TextSingleLine, ellipsis
                )
                continue

            # 根据块高决定字号，译文长则进一步缩小
            font_size = max(int(h * 0.72), 10)
            font = QFont("Microsoft YaHei", font_size)
            painter.setPen(QColor(245, 245, 250))
            painter.setFont(font)
            fm = painter.fontMetrics()
            text = blk["text"]
            # 文字超出块宽则缩小字号直到能放下（或到最小字号）
            while (
                fm.horizontalAdvance(text) > w - 6
                and font_size > 8
            ):
                font_size -= 1
                font = QFont("Microsoft YaHei", font_size)
                painter.setFont(font)
                fm = painter.fontMetrics()
            if font_size <= 8:
                # 太小就逐字截断
                while fm.horizontalAdvance(text) > w - 6 and text:
                    text = text[:-1]
            painter.drawText(
                rect, Qt.AlignCenter | Qt.TextSingleLine, text
            )


# ---------------------------------------------------------------------------
# 主控窗口
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    """主控制窗口。"""

    # 由后台线程 emit（发信对象在主线程），Qt 自动把槽投递到主线程，确保 UI 更新在主线程
    pipelineDone = Signal(object)   # blocks: list[dict]
    pipelineFailed = Signal(str)

    def __init__(self, ocr, translator):
        super().__init__()
        self.ocr = ocr
        self.translator = translator
        self.overlay = None
        self.ink = InkTextWindow()
        self.detail = DetailWindow()
        self.pipelineDone.connect(self._on_done)
        self.pipelineFailed.connect(self._on_error)
        self._build_ui()

    def _build_ui(self):
        self.setWindowTitle("屏幕翻译 Ink · DeepSeek")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(320)   # 仅固定宽度，高度自适应内容

        # 圆角卡片式面板
        panel = QWidget()
        panel.setObjectName("panel")
        panel.setStyleSheet(
            "#panel { background: rgba(18, 22, 34, 235); border: 1px solid #3a4458;"
            " border-radius: 14px; }"
        )

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        # 标题栏（可拖动窗口）
        title_row = QHBoxLayout()
        title = QLabel("🖋  屏幕翻译")
        title.setStyleSheet(
            "color:#6fb3ff; font-size:17px; font-weight:bold; background:transparent;"
        )
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(26, 26)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet(
            "QPushButton { color:#9aa4bd; background:transparent; border:none;"
            " font-size:15px; border-radius:13px; }"
            "QPushButton:hover { color:#ff6b6b; background:rgba(255,255,255,0.06);}"
        )
        close_btn.clicked.connect(QApplication.instance().quit)
        title_row.addWidget(title)
        title_row.addStretch()
        title_row.addWidget(close_btn)
        layout.addLayout(title_row)

        self.info = QLabel("框选屏幕上的外文区域，译文会直接盖在原位置。")
        self.info.setWordWrap(True)
        self.info.setStyleSheet(
            "color:#aab4cc; font-size:12px; background:transparent;"
        )
        layout.addWidget(self.info)

        self.start_btn = QPushButton("开始框选翻译")
        self.start_btn.setFixedHeight(42)
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.setStyleSheet(
            "QPushButton { background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            " stop:0 #4a90e2, stop:1 #6d5bd0); color:white; border:none;"
            " border-radius:8px; font-size:14px; font-weight:bold; }"
            "QPushButton:hover { background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            " stop:0 #5aa0f2, stop:1 #7d6be0); }"
            "QPushButton:pressed { background:#3a7bd5; }"
        )
        self.start_btn.clicked.connect(self._open_overlay)
        layout.addWidget(self.start_btn)

        # 底部操作区：清除译文 + 查看详情 两个小按钮并排
        small_style = (
            "QPushButton { color:#c6d0e6; background:rgba(255,255,255,0.06);"
            " border:1px solid #3a4458; border-radius:6px; font-size:12px; }"
            "QPushButton:hover { background:rgba(255,255,255,0.10); }"
            "QPushButton:disabled { color:#5a637a; background:transparent;"
            " border-color:#2a3144; }"
        )
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)

        self.clear_btn = QPushButton("🗑 清除译文")
        self.clear_btn.setFixedHeight(30)
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        self.clear_btn.setEnabled(False)
        self.clear_btn.setStyleSheet(small_style)
        self.clear_btn.clicked.connect(self._clear_ink)
        bottom_row.addWidget(self.clear_btn)

        self.detail_btn = QPushButton("📋 详情 (N)")
        self.detail_btn.setFixedHeight(30)
        self.detail_btn.setCursor(Qt.PointingHandCursor)
        self.detail_btn.setEnabled(False)
        self.detail_btn.setStyleSheet(small_style)
        self.detail_btn.clicked.connect(self._toggle_detail)
        bottom_row.addWidget(self.detail_btn)

        layout.addLayout(bottom_row)

        self.model_label = QLabel(
            f"{self.translator.model} · 目标：{self.translator.target_lang} · Esc 关闭译文"
        )
        self.model_label.setWordWrap(True)
        self.model_label.setStyleSheet(
            "color:#79839e; font-size:11px; background:transparent;"
        )
        layout.addWidget(self.model_label)

        self.setCentralWidget(panel)
        self.adjustSize()   # 让高度随内容自适应，避免按钮挤压
        self._drag = None

        # 全局 Esc：无论焦点在哪个窗口，都能关闭译文覆盖层
        esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        esc.setContext(Qt.ApplicationShortcut)
        esc.activated.connect(self._on_esc)

    # ---- 无边框窗口拖动 ----
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, event):
        self._drag = None

    def keyPressEvent(self, event):
        # Esc 已由全局 QShortcut 处理（_on_esc），保持父类行为即可
        super().keyPressEvent(event)

    def _open_overlay(self):
        self._clear_ink()
        self.overlay = OverlayWindow()
        self.overlay.regionSelected.connect(self._on_region_selected)
        self.overlay.show()
        self.overlay.activateWindow()
        self.overlay.setFocus()

    def _on_region_selected(self, region):
        if self.overlay:
            self.overlay.close()
            self.overlay = None
        self.info.setText("识别中…")
        self.clear_btn.setEnabled(False)
        self.detail_btn.setEnabled(False)
        self.detail.hide()
        start_pipeline(self, region)

    def _on_done(self, blocks):
        n_trunc = 0
        for blk in blocks:
            blk["truncated"] = _is_trunc(blk)
            if blk["truncated"]:
                n_trunc += 1
        self.info.setText(
            f"已完成 {len(blocks)} 处翻译" + (f"，{n_trunc} 处过长见详情" if n_trunc else "")
        )
        self.clear_btn.setEnabled(bool(blocks))
        # 详情面板始终可用（查看原文↔译文），有折叠项时提示数量
        self.detail_btn.setEnabled(bool(blocks))
        self.detail_btn.setText(f"📋 详情 ({len(blocks)})")
        self.detail.set_blocks(blocks)
        self.ink.set_blocks(blocks)

    def _on_error(self, message):
        self.info.setText(f"出错了：{message}")
        self.raise_()

    def _toggle_detail(self):
        if self.detail.isVisible():
            self.detail.hide()
        else:
            # 放在主控窗口右下角附近，避免与译文覆盖层重叠太多
            self.detail.adjustSize()
            pos = self.frameGeometry().topRight()
            self.detail.move(pos.x() - self.detail.width(), pos.y())
            self.detail.show()
            self.detail.raise_()

    def _clear_ink(self):
        self.ink.set_blocks([])
        self.ink.hide()
        self.detail.hide()
        self.detail_btn.setEnabled(False)
        self.detail_btn.setText("📋 详情 (N)")
        self.clear_btn.setEnabled(False)
        self.info.setText("框选屏幕上的外文区域，译文会直接盖在原位置。")

    def _on_esc(self):
        if self.detail.isVisible():
            self.detail.hide()
        if self.ink.isVisible():
            self._clear_ink()
        elif self.overlay is not None:
            self.overlay.close()
            self.overlay = None
        else:
            self.close()


def main():
    app = QApplication(sys.argv)
    translator = DeepSeekTranslator(
        api_key=config.DEEPSEEK_API_KEY,
        base_url=config.DEEPSEEK_BASE_URL,
        model=config.DEEPSEEK_MODEL,
        target_lang=config.TARGET_LANG,
    )
    ocr = ScreenOCR(confidence=config.OCR_CONFIDENCE)
    win = MainWindow(ocr, translator)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
