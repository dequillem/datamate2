"""Tiện ích dùng chung cho test: LLM kịch bản (scripted) để kiểm soát từng bước của agent."""

from app.llm.base import LLMError, Message, ToolCallRequest


class ScriptedLLM:
    """Trả lần lượt các reply định sẵn; ghi lại messages ở mỗi lần gọi để test kiểm tra."""

    name = "scripted"

    def __init__(self, replies: list[Message | Exception]):
        self._replies = list(replies)
        self.calls: list[list[Message]] = []

    def complete(self, messages, tools):
        self.calls.append(list(messages))
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def close(self) -> None:
        pass


def tool_call(name: str, args: dict, call_id: str = "c1") -> Message:
    return Message(role="assistant", tool_calls=[ToolCallRequest(id=call_id, name=name, arguments=args)])


def text(content: str) -> Message:
    return Message(role="assistant", content=content)


def llm_down() -> LLMError:
    return LLMError("LLM call failed (HTTP 500: boom)")
