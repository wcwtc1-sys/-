"""屏幕区域 OCR（文字识别）封装，基于 RapidOCR。

RapidOCR 是 PaddleOCR 模型的 ONNX 移植，中英文识别效果好、依赖轻量
（无需 C++ 编译器，避免了 PaddleX 在部分机器上的安装问题）。
"""

from rapidocr_onnxruntime import RapidOCR


class TextBox:
    """识别出的一个文字块。

    left/top/right/bottom 是块的外接矩形（相对被识别图片的坐标）。
    """

    __slots__ = ("left", "top", "right", "bottom", "text", "score")

    def __init__(self, left, top, right, bottom, text, score):
        self.left = int(left)
        self.top = int(top)
        self.right = int(right)
        self.bottom = int(bottom)
        self.text = text
        self.score = float(score)

    @property
    def width(self):
        return self.right - self.left

    @property
    def height(self):
        return self.bottom - self.top


class ScreenOCR:
    """封装 RapidOCR，从图片中提取文字。"""

    _engine = None

    def __init__(self, confidence: float = 0.5):
        self.confidence = confidence
        if ScreenOCR._engine is None:
            # 首次初始化会加载/下载 ONNX 模型
            ScreenOCR._engine = RapidOCR()

    def recognize_boxes(self, image) -> list[TextBox]:
        """识别图片中的文字，返回带坐标的文字块列表（按阅读顺序）。

        image 可以是文件路径、numpy.ndarray 或 PIL.Image。
        """
        result, _ = ScreenOCR._engine(image)
        boxes = []
        for item in result or []:
            points, text, score = item[0], item[1], item[2]
            if float(score) < self.confidence:
                continue
            t = (text or "").strip()
            if not t:
                continue
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            boxes.append(TextBox(min(xs), min(ys), max(xs), max(ys), t, score))
        return boxes

    def recognize(self, image) -> str:
        """识别图片中的文字，拼接为完整文本字符串。"""
        boxes = self.recognize_boxes(image)
        return "\n".join(box.text for box in boxes)
