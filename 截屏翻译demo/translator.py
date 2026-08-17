"""DeepSeek 大模型翻译模块。

调用 DeepSeek 的 OpenAI 兼容接口，把 OCR 识别出的屏幕文字翻译成中文。
支持配置 API Key、模型名称与目标语言。
"""

import json
import urllib.request


class DeepSeekTranslator:
    """基于 DeepSeek Chat 的翻译器。"""

    DEFAULT_BASE_URL = "https://api.deepseek.com"
    DEFAULT_MODEL = "deepseek-chat"

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        target_lang: str = "简体中文",
        timeout: int = 30,
    ):
        if not api_key:
            raise ValueError("缺少 DeepSeek API Key，请在 config.py 中填写 sk-xxxx")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.target_lang = target_lang
        self.timeout = timeout

    def translate(self, text: str) -> str:
        """把一段文本翻译为目标语言，返回译文。"""
        text = text.strip()
        if not text:
            return ""

        prompt = (
            f"你是一个屏幕文字即时翻译器。请把下面引号中的文字翻译成{self.target_lang}，"
            f"只输出译文，不要任何解释、前缀或其他内容。如果原文本来就是{self.target_lang}"
            f"且没有别国语言，直接原样输出。\n\n\"{text}\""
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是一位专业、准确的翻译助手。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            raise RuntimeError(f"DeepSeek 接口请求失败: {e}") from e

        choices = body.get("choices") or []
        if not choices:
            raise RuntimeError(f"DeepSeek 返回异常: {body}")
        content = choices[0].get("message", {}).get("content", "")
        return content.strip()
