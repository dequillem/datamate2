"""Adapter cho mọi endpoint theo chuẩn OpenAI `POST {base_url}/chat/completions` có tool calling.

Cấu hình bằng LLM_BASE_URL / LLM_API_KEY / LLM_MODEL. Chỉ dùng httpx, không cần SDK.
"""

import json
import logging
import time
from typing import Any

import httpx

from app.llm.base import LLMError, Message, ToolCallRequest
from app.schemas.tools import ToolSpec

log = logging.getLogger(__name__)

_RETRY_STATUS = {429, 500, 502, 503, 504}


class OpenAICompatLLM:
    name = "openai_compat"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model: str,
        timeout: float = 120.0,
        temperature: float | None = None,
        max_tokens: int | None = None,
        extra_headers: dict[str, str] | None = None,
        max_retries: int = 2,
        retry_backoff: float = 1.0,
        client: httpx.Client | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._extra_headers = dict(extra_headers or {})
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff
        self._client = client or httpx.Client(timeout=timeout)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    # ---------------------------------------------------------------- gọi
    def complete(self, messages: list[Message], tools: list[ToolSpec]) -> Message:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [self._to_wire(m) for m in messages],
        }
        if self._temperature is not None:
            payload["temperature"] = self._temperature
        if self._max_tokens is not None:
            payload["max_tokens"] = self._max_tokens
        if tools:
            payload["tools"] = [
                {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
                for t in tools
            ]
            payload["tool_choice"] = "auto"

        resp = self._post_with_retry(f"{self._base_url}/chat/completions", payload)
        try:
            raw = resp.json()["choices"][0]["message"]
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise LLMError(f"Unexpected LLM response shape: {resp.text[:300]}") from e

        calls = [
            self._parse_call(tc.get("id") or f"call_{i}", tc.get("function") or {})
            for i, tc in enumerate(raw.get("tool_calls") or [])
        ]
        return Message(role="assistant", content=self._text(raw.get("content")), tool_calls=calls)

    def _post_with_retry(self, url: str, payload: dict[str, Any]) -> httpx.Response:
        headers = {"Content-Type": "application/json", **self._extra_headers}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        last_error = "unknown error"
        for attempt in range(self._max_retries + 1):
            try:
                resp = self._client.post(url, json=payload, headers=headers)
            except httpx.HTTPError as e:
                last_error = f"request failed: {e}"
            else:
                if resp.status_code < 400:
                    return resp
                last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
                if resp.status_code not in _RETRY_STATUS:
                    break
            if attempt < self._max_retries:
                log.warning("LLM call failed (%s); retrying", last_error)
                time.sleep(self._retry_backoff * (attempt + 1))
        raise LLMError(f"LLM call failed ({last_error})")

    # ------------------------------------------------------- chuyển đổi định dạng
    @staticmethod
    def _to_wire(m: Message) -> dict[str, Any]:
        if m.role == "tool":
            return {"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content or ""}
        if m.role == "assistant" and m.tool_calls:
            return {
                "role": "assistant",
                "content": m.content or "",
                "tool_calls": [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {
                            "name": c.name,
                            "arguments": c.raw_arguments
                            if c.raw_arguments is not None
                            else json.dumps(c.arguments, ensure_ascii=False),
                        },
                    }
                    for c in m.tool_calls
                ],
            }
        return {"role": m.role, "content": m.content or ""}

    @staticmethod
    def _parse_call(call_id: str, fn: dict[str, Any]) -> ToolCallRequest:
        name = fn.get("name") or ""
        raw = fn.get("arguments")
        if isinstance(raw, dict):  # một số server trả sẵn object thay vì chuỗi JSON
            return ToolCallRequest(id=call_id, name=name, arguments=raw, raw_arguments=json.dumps(raw))
        text = raw or "{}"
        try:
            parsed = json.loads(text)
            if not isinstance(parsed, dict):
                raise ValueError("arguments must be a JSON object")
        except ValueError as e:
            return ToolCallRequest(id=call_id, name=name, raw_arguments=text, arguments_error=str(e))
        return ToolCallRequest(id=call_id, name=name, arguments=parsed, raw_arguments=text)

    @staticmethod
    def _text(content: Any) -> str | None:
        if content is None or isinstance(content, str):
            return content
        if isinstance(content, list):  # content dạng các phần {"type": "text", "text": ...}
            return "".join(p.get("text", "") for p in content if isinstance(p, dict))
        return str(content)
