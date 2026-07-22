"""LiteLLM 服务抽象与统一调用包装器 (infrastructure/llm/provider.py)"""

from __future__ import annotations

import json
from typing import Any, Optional, Type, TypeVar
import litellm
import structlog
from pydantic import BaseModel

from config.settings import settings

logger = structlog.get_logger()
T = TypeVar("T", bound=BaseModel)


class LiteLLMProvider:
    """统一收拢 LiteLLM 模型的异步调用、Token 计数、日志记录与结构化解析"""

    def __init__(
        self,
        primary_model: Optional[str] = None,
        small_model: Optional[str] = None,
    ) -> None:
        self.primary_model = primary_model or settings.PRIMARY_LLM
        self.small_model = small_model or settings.SMALL_LLM

    async def generate(
        self,
        messages: list[dict[str, Any]],
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        use_small_model: bool = False,
    ) -> str:
        """异步调用大语言模型，返回纯文本响应。"""
        target_model = model or (self.small_model if use_small_model else self.primary_model)
        logger.info("llm.generating", model=target_model, message_count=len(messages))

        try:
            kwargs: dict[str, Any] = {
                "model": target_model,
                "messages": messages,
                "temperature": temperature,
            }
            if max_tokens:
                kwargs["max_tokens"] = max_tokens

            response = await litellm.acompletion(**kwargs)
            content = response.choices[0].message.content or ""

            # 记录 Token 使用量
            usage = getattr(response, "usage", None)
            if usage:
                logger.info(
                    "llm.tokens_used",
                    model=target_model,
                    prompt_tokens=getattr(usage, "prompt_tokens", 0),
                    completion_tokens=getattr(usage, "completion_tokens", 0),
                    total_tokens=getattr(usage, "total_tokens", 0),
                )

            return content.strip()
        except Exception as e:
            logger.error("llm.generation_failed", model=target_model, error=str(e))
            raise

    async def generate_json(
        self,
        messages: list[dict[str, Any]],
        schema: Optional[Type[T]] = None,
        model: Optional[str] = None,
        temperature: float = 0.0,
        use_small_model: bool = False,
    ) -> Any:
        """结构化 JSON 输出提取，自动过滤 markdown 标记并校验。"""
        raw_text = await self.generate(
            messages=messages,
            model=model,
            temperature=temperature,
            use_small_model=use_small_model,
        )

        # 自动清洗 ```json ... ``` 标记
        cleaned = raw_text
        if "```json" in cleaned:
            cleaned = cleaned.split("```json")[1].split("```")[0].strip()
        elif "```" in cleaned:
            cleaned = cleaned.split("```")[1].split("```")[0].strip()

        try:
            parsed_dict = json.loads(cleaned)
            if schema:
                return schema.model_validate(parsed_dict)
            return parsed_dict
        except Exception as parse_err:
            logger.error("llm.json_parse_failed", raw_text=raw_text, error=str(parse_err))
            raise ValueError(f"无法解析 LLM 结构化输出为 JSON: {parse_err}") from parse_err
