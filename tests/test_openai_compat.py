"""Kiểm tra adapter OpenAI-compatible bằng httpx.MockTransport (không gọi mạng thật)."""

import json

import httpx
import pytest

from app.agent.tools import default_registry
from app.llm.base import LLMError, Message, ToolCallRequest
from app.llm.openai_compat import OpenAICompatLLM

SPECS = default_registry().specs()
MESSAGES = [Message(role="system", content="sys"), Message(role="user", content="hỏi")]


def make_llm(handler, **kwargs) -> OpenAICompatLLM:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OpenAICompatLLM(
        base_url="http://llm.test/v1/", api_key="secret", model="m1", client=client, retry_backoff=0, **kwargs
    )


def completion(message: dict) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", **message}}]})


def tool_call_message(arguments: str) -> dict:
    return {
        "content": None,
        "tool_calls": [{"id": "call_9", "type": "function", "function": {"name": "run_sql", "arguments": arguments}}],
    }


def test_request_shape_and_tool_call_parsing():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return completion(tool_call_message('{"sql": "SELECT 1"}'))

    reply = make_llm(handler).complete(MESSAGES, SPECS)

    assert seen["url"] == "http://llm.test/v1/chat/completions"
    assert seen["auth"] == "Bearer secret"
    body = seen["body"]
    assert body["model"] == "m1" and body["tool_choice"] == "auto" and "temperature" not in body
    assert [t["function"]["name"] for t in body["tools"]] == ["describe_dataset", "run_sql", "create_chart"]
    assert body["tools"][1]["function"]["parameters"]["properties"]["sql"]["type"] == "string"
    assert body["messages"][1] == {"role": "user", "content": "hỏi"}

    assert reply.role == "assistant" and reply.content is None
    assert reply.tool_calls[0].id == "call_9"
    assert reply.tool_calls[0].name == "run_sql"
    assert reply.tool_calls[0].arguments == {"sql": "SELECT 1"}


def test_plain_text_answer():
    reply = make_llm(lambda r: completion({"content": "Có 400 đơn."})).complete(MESSAGES, SPECS)
    assert reply.content == "Có 400 đơn." and reply.tool_calls == []


def test_list_style_content_is_joined():
    parts = [{"type": "text", "text": "Xin "}, {"type": "text", "text": "chào"}]
    reply = make_llm(lambda r: completion({"content": parts})).complete(MESSAGES, SPECS)
    assert reply.content == "Xin chào"


def test_invalid_json_arguments_are_flagged_not_raised():
    reply = make_llm(lambda r: completion(tool_call_message("{not json"))).complete(MESSAGES, SPECS)
    call = reply.tool_calls[0]
    assert call.arguments_error and call.raw_arguments == "{not json" and call.arguments == {}


def test_non_object_arguments_are_flagged():
    reply = make_llm(lambda r: completion(tool_call_message("[1, 2]"))).complete(MESSAGES, SPECS)
    assert reply.tool_calls[0].arguments_error


def test_temperature_is_sent_only_when_configured():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return completion({"content": "ok"})

    make_llm(handler, temperature=0.0).complete(MESSAGES, [])
    assert seen["temperature"] == 0.0 and "tools" not in seen


def test_max_tokens_and_extra_headers_for_modal_proxy_auth():
    seen = {}

    def handler(request):
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return completion({"content": "ok"})

    llm = make_llm(handler, max_tokens=256, extra_headers={"Modal-Key": "wk-1", "Modal-Secret": "ws-1"})
    llm.complete(MESSAGES, [])
    assert seen["body"]["max_tokens"] == 256
    assert seen["headers"]["modal-key"] == "wk-1" and seen["headers"]["modal-secret"] == "ws-1"
    assert seen["headers"]["authorization"] == "Bearer secret"  # vẫn gửi Bearer nếu có api_key


def test_tool_round_trip_is_serialised_in_openai_format():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return completion({"content": "xong"})

    history = [
        *MESSAGES,
        Message(role="assistant", tool_calls=[ToolCallRequest(id="c1", name="run_sql", arguments={"sql": "SELECT 1"})]),
        Message(role="tool", tool_call_id="c1", content='{"row_count": 1}'),
    ]
    make_llm(handler).complete(history, SPECS)

    assistant, tool = seen["messages"][2], seen["messages"][3]
    assert assistant["tool_calls"][0] == {
        "id": "c1",
        "type": "function",
        "function": {"name": "run_sql", "arguments": '{"sql": "SELECT 1"}'},
    }
    assert tool == {"role": "tool", "tool_call_id": "c1", "content": '{"row_count": 1}'}


def test_retries_on_429_then_succeeds():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429, text="slow down") if len(calls) == 1 else completion({"content": "ok"})

    assert make_llm(handler).complete(MESSAGES, SPECS).content == "ok"
    assert len(calls) == 2


def test_gives_up_after_retries_on_5xx():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503, text="down")

    with pytest.raises(LLMError, match="503"):
        make_llm(handler, max_retries=2).complete(MESSAGES, SPECS)
    assert len(calls) == 3


def test_does_not_retry_client_errors():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(401, text="bad key")

    with pytest.raises(LLMError, match="401"):
        make_llm(handler).complete(MESSAGES, SPECS)
    assert len(calls) == 1


def test_network_error_becomes_llm_error():
    def handler(request):
        raise httpx.ConnectError("no route")

    with pytest.raises(LLMError, match="request failed"):
        make_llm(handler, max_retries=0).complete(MESSAGES, SPECS)


def test_unexpected_response_shape():
    with pytest.raises(LLMError, match="Unexpected"):
        make_llm(lambda r: httpx.Response(200, json={"oops": True})).complete(MESSAGES, SPECS)
