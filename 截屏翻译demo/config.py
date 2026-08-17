"""全局配置。

使用前请把 DEEPSEEK_API_KEY 改成你自己的 Key（在 https://platform.deepseek.com 申请）。
"""

# DeepSeek API Key（必填）
DEEPSEEK_API_KEY = "sk-"

# DeepSeek 接口地址与模型
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

# 目标翻译语言
TARGET_LANG = "简体中文"

# OCR：识别结果按置信度阈值过滤（0~1），太低会保留噪声文本
OCR_CONFIDENCE = 0.5

# 截图翻译区域框选时的边框颜色（RGB）
SELECT_COLOR = (255, 80, 80)
