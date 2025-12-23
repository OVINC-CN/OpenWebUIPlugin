"""
title: OpenAI Deep Research API
author: OVINC CN
git_url: https://github.com/OVINC-CN/OpenWebUIPlugin.git
version: 0.0.7
licence: MIT
"""

import json
import logging
import time
import uuid
from typing import AsyncIterable, Literal, Optional

import httpx
from fastapi import Request
from open_webui.env import GLOBAL_LOG_LEVEL
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

logger = logging.getLogger(__name__)
logger.setLevel(GLOBAL_LOG_LEVEL)


class Pipe:
    class Valves(BaseModel):
        base_url: str = Field(
            default="https://api.openai.com/v1", description="base url"
        )
        api_key: str = Field(default="", description="api key")
        summary: Literal["auto", "concise", "detailed"] = Field(
            default="auto", description="summary type"
        )
        enable_code_interpreter: bool = Field(
            default=True, description="code interpreter"
        )
        enable_deep_research_workflow: bool = Field(
            default=True,
            description="enable multi-stage deep research workflow (clarification + prompt rewrite)",
        )
        intermediate_model: str = Field(
            default="gpt-5.2-chat-latest",
            description="intermediate model for clarification and prompt rewriting",
        )
        timeout: int = Field(default=600, description="timeout")
        proxy: str = Field(default="", description="proxy url")

    class UserValves(BaseModel):
        reasoning_effort: Literal["medium", "high"] = Field(
            default="medium", title="推理强度"
        )

    def __init__(self):
        self.valves = self.Valves()
        self.user_valves = self.UserValves()
        self.emitter = None

    def pipes(self):
        return [
            {"id": "o3-deep-research", "name": "o3-deep-research"},
            {"id": "o4-mini-deep-research", "name": "o4-mini-deep-research"},
        ]

    async def emit_status(self, message: str = "", done: bool = False):
        """Send status updates to UI"""
        if self.emitter:
            await self.emitter(
                {
                    "type": "status",
                    "data": {
                        "description": message,
                        "done": done,
                    },
                }
            )

    async def pipe(
        self, body: dict, __user__: dict, __request__: Request, __event_emitter__=None
    ) -> StreamingResponse:
        self.emitter = __event_emitter__
        return StreamingResponse(
            self._pipe(body=body, __user__=__user__, __request__=__request__)
        )

    async def _ask_clarification(self, user_input: str, model: str) -> AsyncIterable:
        """Ask clarifying questions to gather more information from the user"""
        clarification_instructions = """
You are talking to a user who is asking for a research task to be conducted. Your job is to gather more information from the user to successfully complete the task.

GUIDELINES:
- Be concise while gathering all necessary information
- Make sure to gather all the information needed to carry out the research task in a concise, well-structured manner.
- Use bullet points or numbered lists if appropriate for clarity.
- Don't ask for unnecessary information, or information that the user has already provided.

IMPORTANT: Do NOT conduct any research yourself, just gather information that will be given to a researcher to conduct the research task.
"""

        clarification_body = {
            "model": self.valves.intermediate_model,
            "input": user_input,
            "instructions": clarification_instructions,
            "stream": True,
        }

        try:
            async with httpx.AsyncClient(
                base_url=self.valves.base_url,
                headers={"Authorization": f"Bearer {self.valves.api_key}"},
                proxy=self.valves.proxy or None,
                trust_env=True,
                timeout=300,
            ) as client:
                async with client.stream(
                    method="POST",
                    url="/responses",
                    json=clarification_body,
                ) as response:
                    if response.status_code != 200:
                        error_text = await response.aread()
                        yield self._format_data(
                            model=model,
                            content=f"Error in clarification: {response.status_code} {error_text.decode('utf-8')}",
                            if_finished=True,
                        )
                        return

                    current_event = None
                    usage_data = None

                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        if line.startswith("event:"):
                            current_event = line[6:].strip()
                            continue
                        if not line.startswith("data:"):
                            continue

                        try:
                            payload = json.loads(line[5:].strip())
                        except Exception:
                            continue

                        # Handle usage information from response.completed event
                        if (
                            current_event == "response.completed"
                            and "response" in payload
                        ):
                            response_data = payload.get("response", {})
                            if "usage" in response_data:
                                usage_data = response_data["usage"]
                            continue

                        # Handle text output from clarification model
                        if current_event == "response.output_text.delta":
                            delta = payload.get("delta", "")
                            if delta:
                                yield self._format_data(model=model, content=delta)

                    # Send completion chunk
                    yield self._format_data(
                        model=model, content="", usage=usage_data, if_finished=True
                    )

        except Exception as err:
            logger.exception("Clarification failed: %s", err)
            yield self._format_data(
                model=model, content=f"Error in clarification: {err}", if_finished=True
            )

    def _extract_all_context(self, messages: list) -> str:
        """Extract all conversation context from messages"""
        context_parts = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            text = ""
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") == "text":
                            text += part.get("text", "")
                        elif part.get("type") == "input_text":
                            text += part.get("text", "")
                        elif part.get("type") == "output_text":
                            text += part.get("text", "")

            if text:
                context_parts.append(f"[{role.upper()}]: {text}")

        return "\n\n".join(context_parts)

    async def _rewrite_prompt(self, user_input: str) -> str:
        """Use intermediate model to enhance the research prompt"""
        prompt_rewrite_instructions = """
You will be given a research task by a user. Your job is to produce a set of instructions for a researcher that will complete the task. Do NOT complete the task yourself, just provide instructions on how to complete it.

GUIDELINES:
1. **Maximize Specificity and Detail**
- Include all known user preferences and explicitly list key attributes or dimensions to consider.
- It is of utmost importance that all details from the user are included in the instructions.

2. **Fill in Unstated But Necessary Dimensions as Open-Ended**
- If certain attributes are essential for a meaningful output but the user has not provided them, explicitly state that they are open-ended or default to no specific constraint.

3. **Avoid Unwarranted Assumptions**
- If the user has not provided a particular detail, do not invent one.
- Instead, state the lack of specification and guide the researcher to treat it as flexible or accept all possible options.

4. **Use the First Person**
- Phrase the request from the perspective of the user.

5. **Tables**
- If you determine that including a table will help illustrate, organize, or enhance the information in the research output, you must explicitly request that the researcher provide them.

6. **Headers and Formatting**
- You should include the expected output format in the prompt.
- If the user is asking for content that would be best returned in a structured format (e.g. a report, plan, etc.), ask the researcher to format as a report with the appropriate headers and formatting that ensures clarity and structure.

7. **Language**
- If the user input is in a language other than English, tell the researcher to respond in this language, unless the user query explicitly asks for the response in a different language.

8. **Sources**
- If specific sources should be prioritized, specify them in the prompt.
- For product and travel research, prefer linking directly to official or primary websites rather than aggregator sites or SEO-heavy blogs.
- For academic or scientific queries, prefer linking directly to the original paper or official journal publication rather than survey papers or secondary summaries.
- If the query is in a specific language, prioritize sources published in that language.
"""

        rewrite_body = {
            "model": self.valves.intermediate_model,
            "input": user_input,
            "instructions": prompt_rewrite_instructions,
            "stream": True,
        }

        enhanced_prompt = ""
        try:
            async with httpx.AsyncClient(
                base_url=self.valves.base_url,
                headers={"Authorization": f"Bearer {self.valves.api_key}"},
                proxy=self.valves.proxy or None,
                trust_env=True,
                timeout=300,
            ) as client:
                async with client.stream(
                    method="POST",
                    url="/responses",
                    json=rewrite_body,
                ) as response:
                    if response.status_code != 200:
                        logger.warning(
                            "Prompt rewrite failed with %d, using original input",
                            response.status_code,
                        )
                        return user_input

                    current_event = None
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        if line.startswith("event:"):
                            current_event = line[6:].strip()
                            continue
                        if not line.startswith("data:"):
                            continue

                        try:
                            payload = json.loads(line[5:].strip())
                        except Exception:
                            continue

                        # Handle text output from prompt rewriting model
                        if current_event == "response.output_text.delta":
                            delta = payload.get("delta", "")
                            if delta:
                                enhanced_prompt += delta

            # Fallback to original input if no enhanced prompt was generated
            if not enhanced_prompt.strip():
                return user_input

            logger.info("Prompt rewritten successfully")
            return enhanced_prompt

        except Exception as err:
            logger.warning("Prompt rewrite failed: %s, using original input", err)
            return user_input

    def _is_initial_request(self, messages: list) -> bool:
        """Check if this is the initial request or a follow-up with clarifications"""
        user_messages = [msg for msg in messages if msg.get("role") == "user"]
        assistant_messages = [msg for msg in messages if msg.get("role") == "assistant"]

        # If there are multiple user messages or assistant has asked clarifying questions, this is a follow-up
        if len(user_messages) > 1:
            return False

        # Check if assistant asked clarifying questions
        if len(assistant_messages) > 0:
            for msg in assistant_messages:
                content = msg.get("content", "")
                if isinstance(content, str) and (
                    "澄清" in content or "clarif" in content.lower()
                ):
                    return False
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict):
                            text = part.get("text", "")
                            if "澄清" in text or "clarif" in text.lower():
                                return False

        return True

    async def _pipe(
        self, body: dict, __user__: dict, __request__: Request
    ) -> AsyncIterable:
        model, payload = await self._build_payload(body=body)
        messages = body.get("messages", [])

        # Check if deep research workflow is enabled
        if self.valves.enable_deep_research_workflow and self.valves.intermediate_model:
            # Stage 1: Ask clarifying questions if this is the initial request
            if self._is_initial_request(messages):
                await self.emit_status(message="正在分析您的研究需求...", done=False)

                # Extract the initial user input
                user_input = ""
                if messages:
                    last_user_msg = None
                    for msg in reversed(messages):
                        if msg.get("role") == "user":
                            last_user_msg = msg
                            break

                    if last_user_msg:
                        content = last_user_msg.get("content", "")
                        if isinstance(content, str):
                            user_input = content
                        elif isinstance(content, list):
                            for part in content:
                                if (
                                    isinstance(part, dict)
                                    and part.get("type") == "text"
                                ):
                                    user_input = part.get("text", "")
                                    break

                if user_input:
                    # Ask clarifying questions
                    async for chunk in self._ask_clarification(user_input, model):
                        yield chunk

                    await self.emit_status(message="", done=True)
                    return
                else:
                    logger.warning("No user input found for clarification")

            # Stage 2 & 3: Apply prompt rewrite for follow-up requests
            else:
                try:
                    await self.emit_status(
                        message="正在整合您的需求信息...", done=False
                    )

                    # Extract ALL conversation context from messages
                    all_context = self._extract_all_context(messages)

                    if all_context:
                        # Rewrite the prompt with all context
                        enhanced_text = await self._rewrite_prompt(all_context)

                        if enhanced_text:
                            # Replace the entire input with the enhanced prompt as a single user message
                            payload["json"]["input"] = [
                                {
                                    "role": "user",
                                    "content": [
                                        {"type": "input_text", "text": enhanced_text}
                                    ],
                                }
                            ]
                            logger.info(
                                "Applied enhanced prompt with full conversation context to research request"
                            )

                    await self.emit_status(
                        message="已开始深度研究，耗时较长，请耐心等待...", done=False
                    )
                except Exception as err:
                    logger.warning("Failed to apply prompt rewrite: %s", err)
                    await self.emit_status(message="开始深度研究...", done=False)
        else:
            await self.emit_status(message="开始深度研究...", done=False)

        try:
            # call client
            async with httpx.AsyncClient(
                base_url=self.valves.base_url,
                headers={"Authorization": f"Bearer {self.valves.api_key}"},
                proxy=self.valves.proxy or None,
                trust_env=True,
                timeout=self.valves.timeout,
            ) as client:
                async with client.stream(**payload) as response:
                    if response.status_code != 200:
                        text = ""
                        async for line in response.aiter_lines():
                            text += line
                        logger.error(
                            "response invalid with %d: %s", response.status_code, text
                        )
                        response.raise_for_status()
                        return
                    is_thinking = True
                    yield self._format_data(model=model, content="<think>")
                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line:
                            continue
                        if line.startswith("event:") or not line.startswith("data:"):
                            continue
                        if line.startswith("data: "):
                            line = line[6:]
                        if isinstance(line, str):
                            line = json.loads(line)
                        match line.get("type"):
                            case "response.reasoning_summary_text.delta":
                                yield self._format_data(
                                    model=model, content=line["delta"]
                                )
                            case "response.output_text.delta":
                                if is_thinking:
                                    is_thinking = False
                                    yield self._format_data(
                                        model=model, content="</think>"
                                    )
                                yield self._format_data(
                                    model=model, content=line["delta"]
                                )
                            case "response.completed":
                                await self.emit_status(message="研究完成", done=True)
                                yield self._format_data(
                                    model=model,
                                    content="",
                                    usage=line["response"]["usage"],
                                    if_finished=True,
                                )
                            case _:
                                event_type = line["type"]
                                if event_type.endswith(
                                    "in_progress"
                                ) or event_type.endswith("completed"):
                                    event_type_split = event_type.split(".")[1:]
                                    if len(event_type_split) == 2:
                                        data = {
                                            "event": {
                                                "type": "status",
                                                "data": {
                                                    "description": " ".join(
                                                        event_type_split
                                                    ),
                                                    "done": event_type_split[1]
                                                    == "completed",
                                                },
                                            }
                                        }
                                        yield f"data: {json.dumps(data)}\n\n"
        except Exception as err:
            logger.exception("[OpenAIImagePipe] failed of %s", err)
            yield self._format_data(model=model, content=str(err), if_finished=True)

    async def _build_payload(self, body: dict) -> (str, dict):
        # build messages
        messages = []
        for message in body["messages"]:
            if isinstance(message["content"], str):
                messages.append(
                    {"content": message["content"], "role": message["role"]}
                )
            elif isinstance(message["content"], list):
                content = []
                for item in message["content"]:
                    if item["type"] == "text":
                        content.append({"type": "input_text", "text": item["text"]})
                    elif item["type"] == "image_url":
                        content.append(
                            {
                                "type": "input_image",
                                "image_url": item["image_url"]["url"],
                            }
                        )
                    else:
                        raise TypeError("Invalid message content type %s", item["type"])
                messages.append({"role": message["role"], "content": content})
            else:
                raise TypeError(
                    "Invalid message content type %s", type(message["content"])
                )

        # build body
        model = body["model"].split(".", 1)[1]
        tools = [{"type": "web_search"}]
        if self.valves.enable_code_interpreter:
            tools.append({"type": "code_interpreter", "container": {"type": "auto"}})
        data = {
            "model": model,
            "input": messages,
            "tools": tools,
            "reasoning": {
                "effort": body.get("reasoning_effort")
                or self.user_valves.reasoning_effort,
                "summary": body.get("summary") or self.valves.summary,
            },
            "stream": True,
        }
        for key, val in body.items():
            if key in ["messages"] or key in data:
                continue
            data[key] = val
        payload = {"method": "POST", "url": "/responses", "json": data}
        return model, payload

    def _format_data(
        self,
        model: Optional[str] = "",
        content: Optional[str] = "",
        usage: Optional[dict] = None,
        if_finished: bool = False,
    ) -> str:
        data = {
            "id": f"chat.{uuid.uuid4().hex}",
            "object": "chat.completion.chunk",
            "choices": [],
            "created": int(time.time()),
            "model": model,
        }
        if content:
            data["choices"] = [
                {
                    "finish_reason": "stop" if if_finished else "",
                    "index": 0,
                    "delta": {
                        "content": content,
                    },
                }
            ]
        if usage:
            data["usage"] = usage
        return f"data: {json.dumps(data)}\n\n"
