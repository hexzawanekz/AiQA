"""browser-use Agent factory with custom Shopify verification tools."""

# NOTE: Do NOT use 'from __future__ import annotations' in this file.
# browser-use 0.12.x validates action parameter types at registration time
# using inspect, and PEP 563 deferred annotations break that type comparison.

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from browser_use import Agent, ActionResult, BrowserSession, Controller
from dotenv import load_dotenv

if TYPE_CHECKING:
    from aiqa.config import ClientConfig
    from aiqa.shopify_client import ShopifyStorefrontClient, ShopifyAdminClient

load_dotenv()


def _patch_browser_use_for_python314() -> None:
    """
    Monkey-patch browser-use internals to handle Python 3.14 + Pydantic V1 compat issues.

    On Python 3.14, Pydantic V1 compatibility is broken, meaning browser-use's
    dynamic ActionModel union types don't auto-coerce from dicts. We patch:
    1. AgentHistory.get_interacted_element — calls action.get_index() which fails on dicts
    """
    try:
        import browser_use.agent.views as views_module

        original_fn = views_module.AgentHistory.get_interacted_element

        def safe_get_interacted_element(model_output, selector_map):
            elements = []
            for action in model_output.action:
                try:
                    index = action.get_index()
                except (AttributeError, TypeError):
                    index = None
                if index is not None and index in selector_map:
                    try:
                        from browser_use.dom.history_tree_processor.service import DOMInteractedElement
                        el = selector_map[index]
                        elements.append(DOMInteractedElement.load_from_enhanced_dom_tree(el))
                    except Exception:
                        elements.append(None)
                else:
                    elements.append(None)
            return elements

        # Patch both the class and the module-level reference
        views_module.AgentHistory.get_interacted_element = staticmethod(safe_get_interacted_element)
    except Exception:
        pass

    # Patch agent_steps() in AgentHistoryList which calls action.model_dump()
    try:
        import browser_use.agent.views as views_module2

        original_agent_steps = views_module2.AgentHistoryList.agent_steps

        import json as _json

        def safe_agent_steps(self) -> list:
            steps = []
            for i, h in enumerate(self.history):
                step_text = f"Step {i + 1}:\n"
                if h.model_output and h.model_output.action:
                    actions_list = []
                    for action in h.model_output.action:
                        if isinstance(action, dict):
                            actions_list.append(action)
                        else:
                            try:
                                actions_list.append(action.model_dump(exclude_none=True))
                            except Exception:
                                actions_list.append({"raw": str(action)})
                    try:
                        step_text += f"Actions: {_json.dumps(actions_list, indent=1)}\n"
                    except Exception:
                        step_text += f"Actions: {actions_list}\n"
                if h.result:
                    for j, result in enumerate(h.result):
                        if result.extracted_content:
                            step_text += f"Result {j + 1}: {result.extracted_content}\n"
                        if result.error:
                            step_text += f"Error {j + 1}: {result.error}\n"
                steps.append(step_text)
            return steps

        views_module2.AgentHistoryList.agent_steps = safe_agent_steps
    except Exception:
        pass

    # Patch _log_agent_event in service which calls action.model_dump()
    try:
        import browser_use.agent.service as service_module

        original_log = service_module.Agent._log_agent_event

        def safe_log_agent_event(self, **kwargs):
            try:
                return original_log(self, **kwargs)
            except (AttributeError, TypeError) as e:
                if "model_dump" in str(e) or "dict" in str(e):
                    pass  # Silently ignore model_dump errors in logging
                else:
                    raise

        service_module.Agent._log_agent_event = safe_log_agent_event
    except Exception:
        pass


_patch_browser_use_for_python314()


@dataclass
class StepLog:
    step: int
    description: str
    status: str        # "pass", "fail", "info"
    screenshot: str = ""
    data: dict = field(default_factory=dict)


class _StructuredOutputResponse:
    """
    Thin wrapper around a parsed Pydantic model to satisfy browser-use's expectation
    that `llm.ainvoke(messages, output_format=AgentOutput)` returns an object
    with a `.completion` attribute containing the parsed structured output.
    Also exposes `.usage` (None) so the token cost tracking no-ops cleanly.
    """
    def __init__(self, completion: Any):
        self.completion = completion
        self.usage = None


def _get_llm() -> Any:
    """
    Build a browser-use-compatible LLM from environment config.

    browser-use 0.11.x/0.12.x expects:
      1. llm.provider — attribute checked to detect ChatBrowserUse
      2. llm.model_name — read in telemetry  
      3. llm.ainvoke(messages, output_format=Schema, **kwargs) → obj with .completion
         (standard LangChain ainvoke has signature ainvoke(input, config=None, **kwargs)
          so browser-use's token_cost_service passes output_format as config, which
          breaks LangChain's ensure_config(). We override ainvoke to intercept this.)
      4. llm.ainvoke must be setattr-able (for browser-use's token cost monkey-patching)
         → requires model_config extra='allow'
    """
    provider = os.getenv("AIQA_LLM", "zai").lower()
    model = os.getenv("AIQA_MODEL", "glm-4.7")

    if provider == "zai":
        # Z.AI GLM models via OpenAI-compatible streaming API
        # Docs: https://docs.z.ai/api-reference
        # Available models: glm-4.7, glm-4-plus, glm-5
        from langchain_openai import ChatOpenAI
        from pydantic import ConfigDict

        _zai_model = model

        class BrowserUseZAILLM(ChatOpenAI):
            """
            Z.AI GLM LLM wrapped for browser-use compatibility.
            Uses streaming (stream=True) for all calls — Z.AI recommends streaming
            for better latency and to avoid proxy timeouts on long agent steps.
            """
            model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)
            provider: str = "zai"

            @property
            def model(self) -> str:
                """browser-use accesses llm.model; ChatOpenAI stores it as model_name."""
                return _zai_model

            async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
                import json as _json
                import re as _re
                from langchain_core.messages import (
                    SystemMessage as LC_System,
                    HumanMessage as LC_Human,
                    AIMessage as LC_AI,
                )

                output_format = None
                if isinstance(config, type):
                    output_format = config
                elif "output_format" in kwargs:
                    output_format = kwargs.pop("output_format")
                kwargs.pop("session_id", None)

                # Convert browser-use message types → standard LangChain messages.
                # GLM-4.7 is text-only (no vision) — strip image_url parts to avoid 400 errors.
                # GLM-5 supports vision; set AIQA_ZAI_VISION=1 in .env to enable images.
                _vision_enabled = os.getenv("AIQA_ZAI_VISION", "0") == "1"

                def _convert_content(content: Any) -> Any:
                    if isinstance(content, str):
                        return content
                    if isinstance(content, list):
                        parts = []
                        for part in content:
                            t = getattr(part, "type", None)
                            if t == "text":
                                parts.append({"type": "text", "text": part.text})
                            elif t == "image_url":
                                if _vision_enabled:
                                    parts.append({
                                        "type": "image_url",
                                        "image_url": {"url": part.image_url.url},
                                    })
                                # else: silently drop image — GLM-4.7 is text-only
                            else:
                                parts.append({"type": "text", "text": str(part)})
                        # If only images were in the list and all were stripped, return placeholder
                        if not parts:
                            return "[screenshot omitted — text-only model]"
                        # If list has only one text item, return it as plain string
                        if len(parts) == 1 and parts[0].get("type") == "text":
                            return parts[0]["text"]
                        return parts
                    return str(content)

                def _convert_msg(msg: Any) -> Any:
                    role = getattr(msg, "role", None)
                    content = _convert_content(getattr(msg, "content", str(msg)))
                    if role == "system":
                        return LC_System(content=content)
                    if role == "assistant":
                        return LC_AI(content=content)
                    return LC_Human(content=content)

                lc_messages = []
                for m in (input if isinstance(input, list) else [input]):
                    if "browser_use" in getattr(type(m), "__module__", ""):
                        lc_messages.append(_convert_msg(m))
                    else:
                        lc_messages.append(m)

                # Collect streaming chunks into a single string
                async def _stream_collect() -> str:
                    text = ""
                    async for chunk in self.astream(lc_messages, **kwargs):
                        c = getattr(chunk, "content", "")
                        if isinstance(c, str):
                            text += c
                        elif isinstance(c, list):
                            for part in c:
                                if isinstance(part, dict) and part.get("type") == "text":
                                    text += part.get("text", "")
                    return text

                if output_format is not None:
                    content = await _stream_collect()
                    content = _re.sub(r'```(?:json)?\s*', '', content).replace('```', '').strip()

                    def _build_action_union_map() -> dict:
                        import typing, logging as _log
                        action_map: dict = {}
                        try:
                            dam = getattr(self, "_dynamic_action_model", None)
                            if dam is None:
                                return action_map
                            root_field = getattr(dam, "model_fields", {}).get("root")
                            if root_field is None:
                                return action_map
                            for specific_cls in typing.get_args(root_field.annotation):
                                for field_name in getattr(specific_cls, "model_fields", {}):
                                    action_map[field_name] = (dam, specific_cls)
                        except Exception as _e:
                            _log.getLogger("aiqa.coerce").error(f"action_map error: {_e}")
                        return action_map

                    _action_map = _build_action_union_map()

                    def _coerce_single_action(item: dict) -> Any:
                        if not isinstance(item, dict) or not _action_map:
                            return item
                        for key, val in item.items():
                            if key not in _action_map:
                                continue
                            action_model_cls, specific_cls = _action_map[key]
                            field = specific_cls.model_fields.get(key)
                            if field is None:
                                continue
                            field_type = field.annotation
                            if not isinstance(val, dict):
                                if isinstance(val, int):
                                    val = {"index": val}
                                elif isinstance(val, str):
                                    names = list(getattr(field_type, "model_fields", {}).keys())
                                    val = {names[0]: val} if names else None
                                if val is None:
                                    continue
                            if isinstance(val, dict):
                                aliases = {"element_index": "index", "elem_index": "index",
                                           "selector": "index", "element": "index"}
                                val = {aliases.get(k, k): v for k, v in val.items()}
                            field_val = val
                            if isinstance(val, dict) and field_type is not None:
                                try:
                                    field_val = field_type(**val)
                                except Exception:
                                    try:
                                        field_val = field_type.model_validate(val)
                                    except Exception:
                                        pass
                            try:
                                return action_model_cls(root=specific_cls(**{key: field_val}))
                            except Exception:
                                pass
                            try:
                                return action_model_cls(root=specific_cls.model_validate({key: field_val}))
                            except Exception:
                                pass
                        return item

                    def _coerce_actions(data: dict) -> dict:
                        if "action" not in data or not isinstance(data["action"], list):
                            return data
                        return {**data, "action": [_coerce_single_action(a) for a in data["action"]]}

                    def _try_parse(s: str) -> Any:
                        try:
                            data = _coerce_actions(_json.loads(s))
                        except _json.JSONDecodeError:
                            return None
                        for attempt in (
                            lambda d: output_format.model_validate(d) if hasattr(output_format, "model_validate") else None,
                            lambda d: output_format(**d),
                            lambda d: output_format.model_construct(**d) if hasattr(output_format, "model_construct") else None,
                        ):
                            try:
                                result = attempt(data)
                                if result is not None:
                                    return result
                            except Exception:
                                pass
                        return None

                    parsed = _try_parse(content)
                    if parsed is not None:
                        return _StructuredOutputResponse(completion=parsed)

                    # Try extracting outermost JSON object
                    depth, start = 0, -1
                    for i, ch in enumerate(content):
                        if ch == '{':
                            if depth == 0:
                                start = i
                            depth += 1
                        elif ch == '}':
                            depth -= 1
                            if depth == 0 and start != -1:
                                parsed = _try_parse(content[start:i + 1])
                                if parsed is not None:
                                    return _StructuredOutputResponse(completion=parsed)
                                start = -1

                    return _StructuredOutputResponse(completion=None)

                # No output_format — streaming plain response, return as AIMessage
                content = await _stream_collect()
                return LC_AI(content=content)

        return BrowserUseZAILLM(
            model_name=model,
            openai_api_key=os.getenv("Z_AI_API_KEY"),
            openai_api_base="https://api.z.ai/api/coding/paas/v4/",
            streaming=True,
            timeout=90,
        )

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        from pydantic import ConfigDict

        _model_name = model

        class BrowserUseGeminiLLM(ChatGoogleGenerativeAI):
            """
            ChatGoogleGenerativeAI wrapped for browser-use compatibility.
            Mirrors the same ainvoke override pattern as BrowserUseAnthropicLLM.
            """
            model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)
            provider: str = "google"

            @property
            def model_name(self) -> str:
                return str(self.model)

            async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
                import json as _json
                import re as _re
                from langchain_core.messages import (
                    SystemMessage as LC_System,
                    HumanMessage as LC_Human,
                    AIMessage as LC_AI,
                )

                output_format = None
                if isinstance(config, type):
                    output_format = config
                elif "output_format" in kwargs:
                    output_format = kwargs.pop("output_format")
                kwargs.pop("session_id", None)

                def _convert_content(content: Any) -> Any:
                    if isinstance(content, str):
                        return content
                    if isinstance(content, list):
                        parts = []
                        for part in content:
                            t = getattr(part, "type", None)
                            if t == "text":
                                parts.append({"type": "text", "text": part.text})
                            elif t == "image_url":
                                img = part.image_url
                                parts.append({
                                    "type": "image_url",
                                    "image_url": {"url": img.url, "detail": img.detail},
                                })
                            else:
                                parts.append({"type": "text", "text": str(part)})
                        return parts
                    return str(content)

                def _convert_msg(msg: Any) -> Any:
                    role = getattr(msg, "role", None)
                    content = _convert_content(getattr(msg, "content", str(msg)))
                    if role == "system":
                        return LC_System(content=content)
                    if role == "assistant":
                        return LC_AI(content=content)
                    return LC_Human(content=content)

                lc_messages = []
                msgs = input if isinstance(input, list) else [input]
                for m in msgs:
                    module = getattr(type(m), "__module__", "")
                    if "browser_use" in module:
                        lc_messages.append(_convert_msg(m))
                    else:
                        lc_messages.append(m)

                if output_format is not None:
                    response = await super().ainvoke(lc_messages, config=None, **kwargs)

                    content = response.content if hasattr(response, "content") else str(response)
                    if isinstance(content, list):
                        content = "".join(
                            b.get("text", "") if isinstance(b, dict) else str(b)
                            for b in content
                        )

                    content = _re.sub(r'```(?:json)?\s*', '', content)
                    content = content.replace('```', '').strip()

                    def _build_action_union_map() -> dict:
                        import typing
                        import logging as _log
                        action_map: dict = {}
                        try:
                            dynamic_action_model = getattr(self, "_dynamic_action_model", None)
                            if dynamic_action_model is None:
                                return action_map
                            root_field = getattr(dynamic_action_model, "model_fields", {}).get("root")
                            if root_field is None:
                                return action_map
                            union_args = typing.get_args(root_field.annotation)
                            for specific_cls in union_args:
                                for field_name in getattr(specific_cls, "model_fields", {}):
                                    action_map[field_name] = (dynamic_action_model, specific_cls)
                        except Exception as _e:
                            _log.getLogger("aiqa.coerce").error(f"_build_action_union_map error: {_e}")
                        return action_map

                    _action_map = _build_action_union_map()

                    def _coerce_single_action(item: dict) -> Any:
                        if not isinstance(item, dict):
                            return item
                        if not _action_map:
                            return item
                        for key, val in item.items():
                            if key not in _action_map:
                                continue
                            action_model_cls, specific_cls = _action_map[key]
                            field = specific_cls.model_fields.get(key)
                            if field is None:
                                continue
                            field_type = field.annotation
                            if not isinstance(val, dict):
                                if isinstance(val, int) and field_type is not None:
                                    val = {"index": val}
                                elif isinstance(val, str):
                                    field_names = list(getattr(field_type, "model_fields", {}).keys())
                                    if field_names:
                                        val = {field_names[0]: val}
                                    else:
                                        continue
                                else:
                                    continue
                            if isinstance(val, dict):
                                aliases = {
                                    "element_index": "index",
                                    "elem_index": "index",
                                    "selector": "index",
                                    "element": "index",
                                }
                                val = {aliases.get(k, k): v for k, v in val.items()}
                            field_val = val
                            if isinstance(val, dict) and field_type is not None:
                                try:
                                    field_val = field_type(**val)
                                except Exception:
                                    try:
                                        if hasattr(field_type, "model_validate"):
                                            field_val = field_type.model_validate(val)
                                    except Exception:
                                        field_val = val
                            try:
                                specific_inst = specific_cls(**{key: field_val})
                                return action_model_cls(root=specific_inst)
                            except Exception:
                                pass
                            try:
                                specific_inst = specific_cls.model_validate({key: field_val})
                                return action_model_cls(root=specific_inst)
                            except Exception:
                                pass
                        import typing as _typing
                        try:
                            root_field = action_model_cls.model_fields.get("root")
                            if root_field:
                                for candidate_cls in _typing.get_args(root_field.annotation):
                                    try:
                                        specific_inst = candidate_cls(**item)
                                        return action_model_cls(root=specific_inst)
                                    except Exception:
                                        pass
                        except Exception:
                            pass
                        return item

                    def _coerce_actions(data: dict) -> dict:
                        if "action" not in data or not isinstance(data["action"], list):
                            return data
                        return {**data, "action": [_coerce_single_action(a) for a in data["action"]]}

                    def _try_parse(json_str: str) -> Any:
                        try:
                            data = _json.loads(json_str)
                        except _json.JSONDecodeError:
                            return None
                        try:
                            data = _coerce_actions(data)
                        except Exception:
                            pass
                        try:
                            if hasattr(output_format, "model_validate"):
                                return output_format.model_validate(data)
                        except Exception:
                            pass
                        try:
                            return output_format(**data)
                        except Exception:
                            pass
                        try:
                            if hasattr(output_format, "model_construct"):
                                return output_format.model_construct(**_coerce_actions(data))
                        except Exception:
                            pass
                        return None

                    parsed = _try_parse(content)
                    if parsed is not None:
                        return _StructuredOutputResponse(completion=parsed)

                    depth = 0
                    start = -1
                    for i, ch in enumerate(content):
                        if ch == '{':
                            if depth == 0:
                                start = i
                            depth += 1
                        elif ch == '}':
                            depth -= 1
                            if depth == 0 and start != -1:
                                candidate = content[start:i + 1]
                                parsed = _try_parse(candidate)
                                if parsed is not None:
                                    return _StructuredOutputResponse(completion=parsed)
                                start = -1

                    return _StructuredOutputResponse(completion=None)

                return await super().ainvoke(lc_messages, config=None, **kwargs)

        return BrowserUseGeminiLLM(
            model=model,
            google_api_key=os.getenv("GOOGLE_API_KEY"),
        )

    if provider == "claude":
        from langchain_anthropic import ChatAnthropic
        from pydantic import ConfigDict

        _model_name = model

        class BrowserUseAnthropicLLM(ChatAnthropic):
            """
            ChatAnthropic wrapped for browser-use compatibility.
            Overrides ainvoke to handle output_format via with_structured_output.
            """
            model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)
            provider: str = "anthropic"

            @property
            def model_name(self) -> str:
                return str(self.model)

            async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
                """
                Compatibility bridge between browser-use 0.9.x+ and standard LangChain LLMs.

                Two issues on Python 3.14:
                1. browser-use passes output_format as the positional 'config' arg to ainvoke.
                   LangChain's ensure_config() calls config.items() on the Pydantic class → fails.
                2. browser-use uses its own message types (browser_use.llm.messages.*) which
                   LangChain doesn't know how to coerce → "Unsupported message type" error.

                Fix: convert browser-use messages to LangChain messages, call raw ainvoke,
                parse the JSON response as AgentOutput. browser-use's system prompt already
                includes the full JSON schema so the model returns the right format.
                """
                import json as _json
                import re as _re
                from langchain_core.messages import (
                    SystemMessage as LC_System,
                    HumanMessage as LC_Human,
                    AIMessage as LC_AI,
                )

                import logging as _aiqa_log
                _al = _aiqa_log.getLogger("aiqa.ainvoke")

                output_format = None
                if isinstance(config, type):
                    output_format = config
                elif "output_format" in kwargs:
                    output_format = kwargs.pop("output_format")
                kwargs.pop("session_id", None)

                # Convert browser-use message objects to LangChain message objects
                def _convert_content(content: Any) -> Any:
                    """Convert browser-use content (str or list of parts) to LC format."""
                    if isinstance(content, str):
                        return content
                    if isinstance(content, list):
                        parts = []
                        for part in content:
                            t = getattr(part, "type", None)
                            if t == "text":
                                parts.append({"type": "text", "text": part.text})
                            elif t == "image_url":
                                img = part.image_url
                                parts.append({
                                    "type": "image_url",
                                    "image_url": {"url": img.url, "detail": img.detail},
                                })
                            else:
                                parts.append({"type": "text", "text": str(part)})
                        return parts
                    return str(content)

                def _convert_msg(msg: Any) -> Any:
                    role = getattr(msg, "role", None)
                    content = _convert_content(getattr(msg, "content", str(msg)))
                    if role == "system":
                        return LC_System(content=content)
                    if role == "assistant":
                        return LC_AI(content=content)
                    return LC_Human(content=content)  # user / fallback

                lc_messages = []
                msgs = input if isinstance(input, list) else [input]
                for m in msgs:
                    module = getattr(type(m), "__module__", "")
                    if "browser_use" in module:
                        lc_messages.append(_convert_msg(m))
                    else:
                        lc_messages.append(m)  # already a LangChain message

                if output_format is not None:
                    response = await super().ainvoke(lc_messages, config=None, **kwargs)

                    # Extract text content from the LangChain AIMessage response
                    content = response.content if hasattr(response, "content") else str(response)
                    if isinstance(content, list):
                        content = "".join(
                            b.get("text", "") if isinstance(b, dict) else str(b)
                            for b in content
                        )

                    # Strip markdown code fences if present
                    content = _re.sub(r'```(?:json)?\s*', '', content)
                    content = content.replace('```', '').strip()

                    def _build_action_union_map() -> dict:
                        """
                        Build a mapping of action_key → (ActionModel_cls, specific_action_cls).
                        browser-use creates a NEW dynamic ActionModel after action registration;
                        it's stored on `self._dynamic_action_model` (set in build_agent after
                        Agent.__init__). The base views/service ActionModel has empty model_fields.
                        """
                        import typing
                        import logging as _log
                        _logger = _log.getLogger("aiqa.coerce")
                        action_map: dict = {}
                        try:
                            # Use the dynamic ActionModel set after agent initialization
                            dynamic_action_model = getattr(self, "_dynamic_action_model", None)
                            _logger.debug(f"_build_action_union_map: dynamic_action_model={dynamic_action_model}")
                            if dynamic_action_model is None:
                                _logger.warning("_build_action_union_map: _dynamic_action_model not set on LLM!")
                                return action_map
                            root_field = getattr(dynamic_action_model, "model_fields", {}).get("root")
                            if root_field is None:
                                _logger.warning("_build_action_union_map: no 'root' field in dynamic ActionModel!")
                                return action_map
                            union_args = typing.get_args(root_field.annotation)
                            _logger.debug(f"_build_action_union_map: union_args count={len(union_args)}")
                            for specific_cls in union_args:
                                for field_name in getattr(specific_cls, "model_fields", {}):
                                    action_map[field_name] = (dynamic_action_model, specific_cls)
                            _logger.debug(f"_build_action_union_map: action_map keys={list(action_map.keys())}")
                        except Exception as _e:
                            _log.getLogger("aiqa.coerce").error(f"_build_action_union_map error: {_e}")
                        return action_map

                    _action_map = _build_action_union_map()

                    def _coerce_single_action(item: dict) -> Any:
                        """
                        Convert a single action dict like {'click': {'index': 7}} to ActionModel.
                        Strategy:
                        1. Find which specific_cls has a field matching the action key
                        2. Instantiate the field's nested type from the value dict
                        3. Wrap in specific_cls then in ActionModel(root=specific_cls)
                        """
                        if not isinstance(item, dict):
                            return item
                        if not _action_map:
                            return item

                        for key, val in item.items():
                            if key not in _action_map:
                                continue
                            action_model_cls, specific_cls = _action_map[key]
                            field = specific_cls.model_fields.get(key)
                            if field is None:
                                continue

                            field_type = field.annotation

                            # Normalize val to a dict before passing to field_type.
                            # The LLM sometimes returns:
                            #   - {'click': 8}  → should be {'click': {'index': 8}}
                            #   - {'input': {'element_index': 5, 'text': '...'}} → should use 'index'
                            if not isinstance(val, dict):
                                # If val is a scalar (e.g., int for index-based actions), wrap it
                                if isinstance(val, int) and field_type is not None:
                                    # Try wrapping as {'index': val}
                                    val = {"index": val}
                                elif isinstance(val, str):
                                    # Try wrapping as {'text': val} or {'url': val}
                                    field_names = list(getattr(field_type, "model_fields", {}).keys())
                                    if field_names:
                                        val = {field_names[0]: val}
                                else:
                                    continue  # Cannot normalize, skip this key

                            # Normalize field name aliases in val dict
                            if isinstance(val, dict):
                                # Common aliases the LLM uses
                                aliases = {
                                    "element_index": "index",
                                    "elem_index": "index",
                                    "selector": "index",
                                    "element": "index",
                                }
                                normalized = {}
                                for k, v in val.items():
                                    normalized[aliases.get(k, k)] = v
                                val = normalized

                            # Try to construct the nested field value
                            field_val = val
                            if isinstance(val, dict) and field_type is not None:
                                try:
                                    field_val = field_type(**val)
                                except Exception:
                                    try:
                                        if hasattr(field_type, "model_validate"):
                                            field_val = field_type.model_validate(val)
                                    except Exception:
                                        field_val = val

                            # Create specific action model instance
                            try:
                                specific_inst = specific_cls(**{key: field_val})
                                return action_model_cls(root=specific_inst)
                            except Exception:
                                pass

                            # Fallback: try model_validate on the item directly
                            try:
                                specific_inst = specific_cls.model_validate({key: field_val})
                                return action_model_cls(root=specific_inst)
                            except Exception:
                                pass

                        # Last resort: try all known specific_cls models from the union
                        import typing as _typing
                        try:
                            root_field = action_model_cls.model_fields.get("root")
                            if root_field:
                                for candidate_cls in _typing.get_args(root_field.annotation):
                                    try:
                                        specific_inst = candidate_cls(**item)
                                        return action_model_cls(root=specific_inst)
                                    except Exception:
                                        pass
                        except Exception:
                            pass

                        return item  # Could not coerce — return dict as-is

                    def _coerce_actions(data: dict) -> dict:
                        """
                        Ensure each item in data['action'] is a proper ActionModel instance.
                        browser-use's ActionModel is a RootModel with a discriminated union.
                        On Python 3.14, Pydantic V1 compat breaks automatic dict→model coercion.
                        We resolve the union manually using the action key as the discriminator.
                        """
                        if "action" not in data or not isinstance(data["action"], list):
                            return data
                        coerced = [_coerce_single_action(item) for item in data["action"]]
                        return {**data, "action": coerced}

                    def _try_parse(json_str: str) -> Any:
                        """Try multiple parsing strategies for AgentOutput."""
                        try:
                            data = _json.loads(json_str)
                        except _json.JSONDecodeError:
                            return None

                        # Pre-process: coerce action items to proper types
                        try:
                            data = _coerce_actions(data)
                        except Exception:
                            pass

                        # Strategy 1: model_validate (Pydantic v2 / compatible)
                        try:
                            if hasattr(output_format, "model_validate"):
                                return output_format.model_validate(data)
                        except Exception:
                            pass

                        # Strategy 2: direct construction
                        try:
                            return output_format(**data)
                        except Exception:
                            pass

                        # Strategy 3: construct skipping validation (last resort)
                        try:
                            if hasattr(output_format, "model_construct"):
                                coerced = _coerce_actions(data)
                                return output_format.model_construct(**coerced)
                        except Exception:
                            pass

                        return None

                    # Try the full content as JSON
                    parsed = _try_parse(content)
                    if parsed is not None:
                        return _StructuredOutputResponse(completion=parsed)

                    # Try finding the outermost JSON object via balanced brace matching
                    depth = 0
                    start = -1
                    for i, ch in enumerate(content):
                        if ch == '{':
                            if depth == 0:
                                start = i
                            depth += 1
                        elif ch == '}':
                            depth -= 1
                            if depth == 0 and start != -1:
                                candidate = content[start:i + 1]
                                parsed = _try_parse(candidate)
                                if parsed is not None:
                                    return _StructuredOutputResponse(completion=parsed)
                                start = -1

                    # Parsing failed — return None completion so browser-use handles the error
                    return _StructuredOutputResponse(completion=None)

                return await super().ainvoke(lc_messages, config=None, **kwargs)

        return BrowserUseAnthropicLLM(
            model=model,
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
            timeout=60,
        )

    if provider == "openai":
        from langchain_openai import ChatOpenAI
        from pydantic import ConfigDict

        class BrowserUseOpenAILLM(ChatOpenAI):
            model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)
            provider: str = "openai"

            async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
                import json as _json
                import re as _re

                output_format = None
                config_to_use = config

                if isinstance(config, type):
                    output_format = config
                    config_to_use = None
                elif "output_format" in kwargs:
                    output_format = kwargs.pop("output_format")

                kwargs.pop("session_id", None)

                if output_format is not None:
                    response = await super().ainvoke(input, config=None, **kwargs)
                    content = response.content if hasattr(response, "content") else str(response)
                    if isinstance(content, list):
                        content = "".join(
                            b.get("text", "") if isinstance(b, dict) else str(b) for b in content
                        )
                    json_match = _re.search(r'\{[\s\S]*\}', content)
                    if json_match:
                        try:
                            parsed = output_format(**_json.loads(json_match.group()))
                            return _StructuredOutputResponse(completion=parsed)
                        except Exception:
                            pass
                    return _StructuredOutputResponse(completion=None)

                return await super().ainvoke(input, config=config_to_use, **kwargs)

        return BrowserUseOpenAILLM(
            model=model,
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            timeout=60,
        )

    raise ValueError(f"Unknown AIQA_LLM: {provider}")


def build_agent(
    task: str,
    screenshots_dir: Path,
    client_config: Any,
    storefront: Any = None,
    admin: Any = None,
    max_steps: int = 25,
) -> tuple:
    """
    Build a browser-use Agent with custom Shopify verification tools.
    Returns (agent, step_logs) — step_logs is mutated during agent.run().
    """
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    step_logs: list[StepLog] = []
    step_counter = [0]

    controller = Controller()

    @controller.action("Take a screenshot and save it with the given label")
    async def take_screenshot(label: str, browser_session: BrowserSession) -> ActionResult:
        step_counter[0] += 1
        timestamp = datetime.now().strftime("%H%M%S")
        filename = f"{step_counter[0]:02d}-{label.replace(' ', '_')}-{timestamp}.png"
        filepath = screenshots_dir / filename

        try:
            # Use BrowserSession.take_screenshot which accepts a path parameter directly
            await browser_session.take_screenshot(path=str(filepath), full_page=False)
        except Exception as e:
            import logging as _logging
            _logging.getLogger("aiqa").error(f"Screenshot via BrowserSession failed: {type(e).__name__}: {e}")
            # Fallback: try getting page directly and using playwright screenshot
            try:
                page = await browser_session.get_current_page()
                await page.screenshot(path=str(filepath), full_page=False)
            except Exception as e2:
                _logging.getLogger("aiqa").error(f"Screenshot via page failed: {type(e2).__name__}: {e2}")
                return ActionResult(extracted_content=f"Screenshot failed: {type(e).__name__}: {e}")

        step_logs.append(StepLog(
            step=step_counter[0],
            description=f"Screenshot: {label}",
            status="info",
            screenshot=str(filepath),
        ))
        return ActionResult(extracted_content=f"Screenshot saved: {filepath}")

    @controller.action(
        "Search for a product using the Shopify Storefront API and return its title, price, and variant ID"
    )
    async def verify_product_in_storefront_api(product_title: str) -> ActionResult:
        if storefront is None:
            return ActionResult(extracted_content="SKIP: No storefront API token configured")
        try:
            products = await storefront.search_products(product_title, limit=5)
            if not products:
                return ActionResult(
                    extracted_content=f"FAIL: No products found for '{product_title}' in Storefront API"
                )
            p = products[0]
            result = {
                "found": True,
                "title": p.title,
                "price_min": p.price_min,
                "price_max": p.price_max,
                "currency": p.currency,
                "variant_id": p.variants[0].variant_id if p.variants else None,
                "available": p.variants[0].available if p.variants else False,
            }
            step_logs.append(StepLog(
                step=step_counter[0],
                description=f"Storefront API: verified product '{p.title}'",
                status="pass",
                data=result,
            ))
            return ActionResult(extracted_content=json.dumps(result))
        except Exception as e:
            return ActionResult(extracted_content=f"FAIL: Storefront API error — {e}")

    @controller.action(
        "Create a cart with the given variant ID and quantity, then return the cart ID and total"
    )
    async def create_cart_via_api(variant_id: str, quantity: int = 1) -> ActionResult:
        if storefront is None:
            return ActionResult(extracted_content="SKIP: No storefront API token configured")
        try:
            cart = await storefront.create_cart(variant_id, quantity)
            result = {
                "cart_id": cart.cart_id,
                "total": cart.total_amount,
                "currency": cart.currency,
                "checkout_url": cart.checkout_url,
                "lines": [
                    {"title": l.title, "quantity": l.quantity, "price": l.price}
                    for l in cart.lines
                ],
            }
            step_logs.append(StepLog(
                step=step_counter[0],
                description=f"Storefront API: created cart — total {cart.total_amount} {cart.currency}",
                status="pass",
                data=result,
            ))
            return ActionResult(extracted_content=json.dumps(result))
        except Exception as e:
            return ActionResult(extracted_content=f"FAIL: Cart creation error — {e}")

    @controller.action(
        "Verify cart contents via the Storefront API using the cart ID — returns items and total"
    )
    async def verify_cart_via_api(cart_id: str) -> ActionResult:
        if storefront is None:
            return ActionResult(extracted_content="SKIP: No storefront API token configured")
        try:
            cart = await storefront.get_cart(cart_id)
            result = {
                "cart_id": cart.cart_id,
                "total": cart.total_amount,
                "currency": cart.currency,
                "line_count": len(cart.lines),
                "discount_codes": cart.discount_codes,
                "lines": [
                    {"title": l.title, "quantity": l.quantity, "price": l.price}
                    for l in cart.lines
                ],
            }
            step_logs.append(StepLog(
                step=step_counter[0],
                description=f"Storefront API: cart verified — {len(cart.lines)} line(s), total {cart.total_amount} {cart.currency}",
                status="pass",
                data=result,
            ))
            return ActionResult(extracted_content=json.dumps(result))
        except Exception as e:
            return ActionResult(extracted_content=f"FAIL: Cart verification error — {e}")

    @controller.action(
        "Look up a product in the Shopify Admin API by title and return price and inventory"
    )
    async def verify_product_in_admin_api(product_title: str) -> ActionResult:
        if admin is None:
            return ActionResult(extracted_content="SKIP: No admin API token configured")
        try:
            products = await admin.get_products(product_title, limit=5)
            if not products:
                return ActionResult(
                    extracted_content=f"FAIL: No products found for '{product_title}' in Admin API"
                )
            p = products[0]
            price_range = p.get("priceRangeV2", {})
            result = {
                "found": True,
                "title": p["title"],
                "status": p.get("status"),
                "total_inventory": p.get("totalInventory"),
                "price_min": price_range.get("minVariantPrice", {}).get("amount"),
                "currency": price_range.get("minVariantPrice", {}).get("currencyCode"),
            }
            step_logs.append(StepLog(
                step=step_counter[0],
                description=f"Admin API: verified product '{p['title']}'",
                status="pass",
                data=result,
            ))
            return ActionResult(extracted_content=json.dumps(result))
        except Exception as e:
            return ActionResult(extracted_content=f"FAIL: Admin API error — {e}")

    @controller.action(
        "Look up the latest order for a given email address in the Shopify Admin API"
    )
    async def verify_latest_order_for_email(email: str) -> ActionResult:
        if admin is None:
            return ActionResult(extracted_content="SKIP: No admin API token configured")
        try:
            order = await admin.get_latest_order_for_email(email)
            if not order:
                return ActionResult(
                    extracted_content=f"No orders found for {email} in Admin API"
                )
            price = order.get("totalPriceSet", {}).get("shopMoney", {})
            result = {
                "order_id": order["id"],
                "order_name": order["name"],
                "email": order["email"],
                "total": price.get("amount"),
                "currency": price.get("currencyCode"),
                "financial_status": order.get("financialStatus"),
                "discount_codes": order.get("discountCodes", []),
            }
            step_logs.append(StepLog(
                step=step_counter[0],
                description=f"Admin API: found order {order['name']} for {email}",
                status="pass",
                data=result,
            ))
            return ActionResult(extracted_content=json.dumps(result))
        except Exception as e:
            return ActionResult(extracted_content=f"FAIL: Order lookup error — {e}")

    llm = _get_llm()
    agent = Agent(
        task=task,
        llm=llm,
        controller=controller,
        max_actions_per_step=5,
    )
    # After agent initialization, the dynamic ActionModel is populated with registered actions.
    # Store it on the LLM so ainvoke can use the correct model for action coercion.
    try:
        llm._dynamic_action_model = agent.ActionModel
    except Exception:
        pass
    return agent, step_logs


async def run_task(
    task: str,
    screenshots_dir: Path,
    client_config: Any,
    storefront: Any = None,
    admin: Any = None,
    max_steps: int = 25,
) -> tuple:
    """
    Run a single task string through the browser agent.
    Returns (final_result_text, step_logs).
    """
    agent, step_logs = build_agent(
        task=task,
        screenshots_dir=screenshots_dir,
        client_config=client_config,
        storefront=storefront,
        admin=admin,
        max_steps=max_steps,
    )
    result = await agent.run(max_steps=max_steps)
    final_text = result.final_result() if hasattr(result, "final_result") else str(result)
    return final_text or "", step_logs
