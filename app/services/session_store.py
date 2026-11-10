"""Bộ nhớ hội thoại trong RAM (mỗi cặp session + dataset một lịch sử riêng).

Đủ cho demo/challenge. Chạy nhiều worker hoặc cần giữ lịch sử qua restart thì thay bằng Redis/DB:
chỉ cần giữ nguyên hai hàm `history()` và `append()`.
"""

import threading
from collections import OrderedDict, deque

from app.llm.base import Message


class SessionStore:
    def __init__(self, max_turns: int = 6, max_sessions: int = 1000):
        self._max_turns = max_turns
        self._max_sessions = max_sessions
        self._data: OrderedDict[str, deque[tuple[str, str]]] = OrderedDict()
        self._lock = threading.Lock()

    def history(self, key: str) -> list[Message]:
        with self._lock:
            turns = list(self._data.get(key, ()))
        messages: list[Message] = []
        for question, answer in turns:
            messages.append(Message(role="user", content=question))
            messages.append(Message(role="assistant", content=answer))
        return messages

    def append(self, key: str, question: str, answer: str) -> None:
        with self._lock:
            turns = self._data.setdefault(key, deque(maxlen=self._max_turns))
            turns.append((question, answer))
            self._data.move_to_end(key)
            while len(self._data) > self._max_sessions:
                self._data.popitem(last=False)
