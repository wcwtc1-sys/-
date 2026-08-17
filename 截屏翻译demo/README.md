# 屏幕翻译 Ink（Windows 桌面端）

基于 **RapidOCR + DeepSeek 大模型** 的屏幕即时翻译工具：框选屏幕任意区域，自动识别外文并翻译成中文，译文**直接盖在原文字位置**（类似 Gaminik / 游戏汉化贴图的融入画面效果）。

## 功能
- 全屏透明遮罩，鼠标拖拽框选目标区域（按 Esc 取消框选）
- RapidOCR（PaddleOCR 的 ONNX 移植）识别区域内**每个文字块及其坐标**
- DeepSeek 大模型对每个文字块单独翻译成中文
- 全屏**点击穿透**覆盖层把译文"印"在原文位置（不透明圆角贴块遮住原文，不影响鼠标操作）
- **过长译文自动折叠**：译文在小块内放不下时显示省略号"⋯"，点「📋 详情」查看完整"原文↔译文"面板（可打开/关闭）
- 置顶、无边框主控窗口，可随意拖动；按 Esc 一键清除全部译文

## 项目结构
```
fanyi/
├── main.py            # 主程序（GUI + 流程编排）
├── ocr.py             # RapidOCR 文字识别封装
├── translator.py      # DeepSeek 翻译调用
├── config.py          # 配置（API Key 等）
├── ui_smoke_test.py   # UI 冒烟测试（无需 API Key / OCR）
└── requirements.txt   # 依赖
```

## 安装
```bash
python -m pip install -r requirements.txt
```

## 使用
1. 编辑 `config.py`，把 `DEEPSEEK_API_KEY` 换成你自己的 Key（在 https://platform.deepseek.com 申请）。
2. 运行：
   ```bash
   python main.py
   ```
3. 点击「开始框选翻译」，在屏幕上拖出一个矩形覆盖外文区域，松开后自动识别并逐块翻译。
4. 译文会直接盖在原文字位置上；按 **Esc** 或点击「清除译文」即可移除全部译文。

> 首次运行 RapidOCR 会下载识别模型，需要较长时间，请耐心等待。

## 测试
无需 DeepSeek Key 和本地 OCR 模型，验证 GUI 链路：
```bash
python ui_smoke_test.py
```

## 说明
- 本项目为学习/演示用途。
- 为让译文贴块与原文位置精确对应，OCR 识别出的**每个文字块会单独**交给大模型翻译（而非整段拼接），这样译文能准确盖在对应原文位置。
- 译文覆盖层为**鼠标点击穿透**，显示译文时不会阻挡鼠标操作底层应用。
