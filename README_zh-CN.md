# OpenWebUI 插件库

本仓库包含一系列适用于 [OpenWebUI](https://github.com/OVINC-CN/OpenWebUI) 的插件（Filters, Pipes 和 Tools）。这些插件通过添加联网搜索、代码解释、图像生成等新功能来扩展 OpenWebUI 的能力。

[English README](README.md)

## 📂 内容列表

### Filters (过滤器)
过滤器用于修改或增强 LLM 的输入/输出，或者实施限制。

| 分类 | 文件名 | 描述 |
| :--- | :--- | :--- |
| **Gemini** | [`gemini_code_interpreter.py`](filters/gemini_code_interpreter.py) | 使用 Gemini 执行代码 |
| | [`gemini_url_context.py`](filters/gemini_url_context.py) | 获取 URL 内容作为上下文 |
| | [`gemini_web_search.py`](filters/gemini_web_search.py) | 通过 Gemini 进行联网搜索 |
| **OpenAI** | [`openai_code_interpreter.py`](filters/openai_code_interpreter.py) | 使用 OpenAI 执行代码 |
| | [`openai_web_search.py`](filters/openai_web_search.py) | 通过 OpenAI 进行联网搜索 |
| **OpenRouter** | [`openrouter_web_search.py`](filters/openrouter_web_search.py) | 通过 OpenRouter 进行联网搜索 |
| **Hunyuan** | [`hunyuan_enhancement.py`](filters/hunyuan_enhancement.py) | 混元 (Hunyuan) 模型增强 |
| **LKEAP** | [`lkeap_web_search.py`](filters/lkeap_web_search.py) | 通过 LKEAP 进行联网搜索 |
| **通用 (General)** | [`max_turns_limit.py`](filters/max_turns_limit.py) | 限制对话轮数 |
| | [`rate_limit.py`](filters/rate_limit.py) | 实施请求速率限制 |
| | [`size_limit.py`](filters/size_limit.py) | 限制请求/响应的大小 |
| | [`usage_event.py`](filters/usage_event.py) | 跟踪使用事件 |

### Pipes (管道)
管道用于将外部模型、服务或复杂工作流集成到 OpenWebUI 中。

| 提供商 | 文件名 | 描述 |
| :--- | :--- | :--- |
| **Gemini** | [`gemini_chat.py`](pipes/gemini_chat.py) | Gemini 聊天集成 |
| | [`gemini_deep_research.py`](pipes/gemini_deep_research.py) | 使用 Gemini 进行深度研究 |
| | [`gemini_image.py`](pipes/gemini_image.py) | 使用 Gemini 生成图像 |
| **OpenAI** | [`openai_deep_research.py`](pipes/openai_deep_research.py) | 使用 OpenAI 进行深度研究 |
| | [`openai_image.py`](pipes/openai_image.py) | 使用 OpenAI (DALL-E) 生成图像 |
| | [`openai_responses.py`](pipes/openai_responses.py) | 增强的 OpenAI 响应 |
| **OpenRouter** | [`openrouter_image.py`](pipes/openrouter_image.py) | 使用 OpenRouter 生成图像 |
| | [`openrouter_reasoning.py`](pipes/openrouter_reasoning.py) | 集成 OpenRouter 推理模型 |
| **DeepSeek** | [`deepseek_reasoning.py`](pipes/deepseek_reasoning.py) | 集成 DeepSeek 推理模型 |
| **OAIPro** | [`oaipro_reasoning.py`](pipes/oaipro_reasoning.py) | 集成 OAIPro 推理 |
| **Doubao** | [`doubao_image.py`](pipes/doubao_image.py) | 使用 Doubao Seedream 生成图像 |

### Tools (工具)
工具提供可由 LLM 调用的特定功能 (Function Calling)。

| 文件名 | 描述 |
| :--- | :--- |
| [`amap_weather.py`](tools/amap_weather.py) | 通过高德地图获取天气信息 |
| [`current_datetime.py`](tools/current_datetime.py) | 获取当前日期和时间 |
| [`web_scrape.py`](tools/web_scrape.py) | 抓取网页内容 |

## 🚀 使用方法

1.  **克隆或下载**: 克隆本仓库或下载您需要的特定 `.py` 文件。
2.  **导入到 OpenWebUI**:
    *   在 OpenWebUI 仪表板中导航至 **Functions** (或 Plugins) 部分。
    *   创建一个新的 function/pipe/tool。
    *   将 Python 文件的内容粘贴到编辑器中。
3.  **配置**:
    *   启用插件。
    *   在 OpenWebUI 界面中配置必要的 Valves (设置)，例如 API 密钥或偏好设置。

## 🔗 主仓库

本插件仓库服务于: [https://github.com/OVINC-CN/OpenWebUI](https://github.com/OVINC-CN/OpenWebUI)
