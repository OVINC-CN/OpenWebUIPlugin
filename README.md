# OpenWebUI Plugins

This repository contains a collection of plugins (Filters, Pipes, and Tools) for [OpenWebUI](https://github.com/OVINC-CN/OpenWebUI). These plugins extend the functionality of OpenWebUI by adding new capabilities such as web search, code interpretation, image generation, and more.

[中文说明 (Chinese README)](README_zh-CN.md)

## 📂 Contents

### Filters
Filters allow you to modify or enhance the input/output of the LLM or enforce constraints.

| Category | File | Description |
| :--- | :--- | :--- |
| **Gemini** | [`gemini_code_interpreter.py`](filters/gemini_code_interpreter.py) | Execute code using Gemini |
| | [`gemini_url_context.py`](filters/gemini_url_context.py) | Fetch and use URL content as context |
| | [`gemini_web_search.py`](filters/gemini_web_search.py) | Web search capabilities via Gemini |
| **OpenAI** | [`openai_code_interpreter.py`](filters/openai_code_interpreter.py) | Execute code using OpenAI |
| | [`openai_web_search.py`](filters/openai_web_search.py) | Web search via OpenAI |
| **OpenRouter** | [`openrouter_web_search.py`](filters/openrouter_web_search.py) | Web search via OpenRouter |
| **Hunyuan** | [`hunyuan_enhancement.py`](filters/hunyuan_enhancement.py) | Enhancement for Hunyuan models |
| **LKEAP** | [`lkeap_web_search.py`](filters/lkeap_web_search.py) | Web search via LKEAP |
| **General** | [`max_turns_limit.py`](filters/max_turns_limit.py) | Limit the number of conversation turns |
| | [`rate_limit.py`](filters/rate_limit.py) | Enforce rate limiting on requests |
| | [`size_limit.py`](filters/size_limit.py) | Limit the size of requests/responses |
| | [`usage_event.py`](filters/usage_event.py) | Track usage events |

### Pipes
Pipes integrate external models, services, or complex workflows into OpenWebUI.

| Provider | File | Description |
| :--- | :--- | :--- |
| **Gemini** | [`gemini_chat.py`](pipes/gemini_chat.py) | Chat integration for Gemini |
| | [`gemini_deep_research.py`](pipes/gemini_deep_research.py) | Deep research capabilities using Gemini |
| | [`gemini_image.py`](pipes/gemini_image.py) | Image generation using Gemini |
| **OpenAI** | [`openai_deep_research.py`](pipes/openai_deep_research.py) | Deep research capabilities using OpenAI |
| | [`openai_image.py`](pipes/openai_image.py) | Image generation using OpenAI (DALL-E) |
| | [`openai_responses.py`](pipes/openai_responses.py) | Enhanced OpenAI responses |
| **OpenRouter** | [`openrouter_image.py`](pipes/openrouter_image.py) | Image generation using OpenRouter |
| | [`openrouter_reasoning.py`](pipes/openrouter_reasoning.py) | Integration with OpenRouter reasoning models |
| **DeepSeek** | [`deepseek_reasoning.py`](pipes/deepseek_reasoning.py) | Integration with DeepSeek reasoning models |
| **OAIPro** | [`oaipro_reasoning.py`](pipes/oaipro_reasoning.py) | Integration with OAIPro reasoning |

### Tools
Tools provide specific functionalities that can be called by the LLM (Function Calling).

| File | Description |
| :--- | :--- |
| [`amap_weather.py`](tools/amap_weather.py) | Get weather information via AMap (AutoNavi) |
| [`current_datetime.py`](tools/current_datetime.py) | Get the current date and time |
| [`web_scrape.py`](tools/web_scrape.py) | Scrape content from websites |

## 🚀 Usage

1.  **Clone or Download**: Clone this repository or download the specific `.py` file you need.
2.  **Import to OpenWebUI**:
    *   Navigate to the **Functions** (or Plugins) section in your OpenWebUI dashboard.
    *   Create a new function/pipe/tool.
    *   Paste the content of the python file into the editor.
3.  **Configuration**:
    *   Enable the plugin.
    *   Configure any necessary Valves (settings) such as API keys or preferences within the OpenWebUI interface.

## 🔗 Main Repository

This plugin repository is designed for: [https://github.com/OVINC-CN/OpenWebUI](https://github.com/OVINC-CN/OpenWebUI)
