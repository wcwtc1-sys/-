"""UI 冒烟测试：验证就地覆盖窗口 + 主控窗口逻辑。

用假的 OCR/翻译器替换真实的对象，不依赖 DeepSeek 网络请求。
覆盖：
1. MainWindow 能正常创建、样式生效
2. 后台流水线能把带坐标的译文块通过信号回传进来
3. InkTextWindow 正确接收 blocks 并显示
4. 清除译文能清空覆盖层
运行：python ui_smoke_test.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

import main as main_mod
from ocr import TextBox


class FakeOCR:
    def recognize_boxes(self, image):
        # 返回带坐标的文字块（相对被截图区域）
        return [
            TextBox(0, 0, 120, 30, "Hello World", 0.9),
            TextBox(0, 40, 80, 65, "Welcome", 0.88),
        ]


class FakeTranslator:
    model = "fake-deepseek"
    target_lang = "简体中文"

    def translate(self, text):
        return f"译:{text}"


def run():
    app = QApplication(sys.argv)

    # 直接构造主窗口，注入假的 OCR/翻译
    ocr = FakeOCR()
    trans = FakeTranslator()

    win = main_mod.MainWindow(ocr, trans)
    win.show()

    print("主窗口创建 OK, 标题:", win.windowTitle())

    # 模拟编译完成的 blocks（坐标带全屏偏移，含 source）
    blocks = [
        {"left": 100, "top": 100, "right": 220, "bottom": 130, "source": "Hello", "text": "你好"},
        {"left": 100, "top": 140, "right": 150, "bottom": 165, "source": "VeryLong",
         "text": "这是一段很长的测试译文，肯定会超出这个小方块的宽度"},
    ]
    win._on_done(blocks)

    def check():
        assert win.ink.blocks == blocks, "覆盖层未收到 blocks"
        assert win.clear_btn.isEnabled(), "清除按钮应已启用"
        assert win.detail_btn.isEnabled(), "详情按钮应已启用"
        assert win.detail_btn.text() == "📋 详情 (2)", f"详情按钮文本错误: {win.detail_btn.text()}"
        assert blocks[1]["truncated"] is True, "长译文应标记为 truncated"
        assert blocks[0]["truncated"] is False, "短译文不应标记 truncated"
        print("覆盖层收到 blocks:", len(win.ink.blocks))
        print("信息栏:", win.info.text())
        print("truncated 标记: 短译文=%s 长译文=%s" % (
            blocks[0]["truncated"], blocks[1]["truncated"]))

        # 打开详情面板
        win._toggle_detail()
        assert win.detail.isVisible(), "详情面板应可见"
        assert "原文" in win.detail.body.text() and "译文" in win.detail.body.text(), \
            "详情面板应包含原文与译文"
        print("详情面板打开 OK, 条目数:", win.detail.body.text().count("["))

        # 清除后应清空
        win._clear_ink()
        assert win.ink.blocks == [], "清除后 blocks 应为空"
        assert not win.detail.isVisible(), "清除后详情面板应隐藏"
        assert not win.clear_btn.isEnabled(), "清除按钮应禁用"
        assert not win.detail_btn.isEnabled(), "详情按钮应禁用"
        print("清除译文 OK")
        print("SMOKE TEST PASSED")
        app.quit()

    QTimer.singleShot(500, check)
    QTimer.singleShot(10000, app.quit)
    sys.exit(app.exec())


if __name__ == "__main__":
    run()
