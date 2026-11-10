"""Vòng lặp agent: LLM -> (gọi tool -> đưa kết quả lại cho LLM)* -> câu trả lời cuối.

`run_stream` là generator phát ra StreamEvent sau mỗi bước, nên dùng chung được cho
cả endpoint thường (lấy event cuối) lẫn endpoint SSE.
"""

import logging
import time
from collections.abc import Iterator

from pydantic import ValidationError

from app.agent.prompts import build_system_prompt
from app.agent.tools import ToolRegistry
from app.agent.tools.base import ToolContext, ToolError, ToolOutput, dumps
from app.config import Settings
from app.errors import LLMUnavailable
from app.llm.base import LLMClient, LLMError, Message, ToolCallRequest
from app.schemas.chat import AgentStep, ChatResponse, StreamEvent
from app.schemas.common import ErrorInfo
from app.schemas.results import ChartSpec, TableResult
from app.services.dataset_store import LoadedDataset

log = logging.getLogger(__name__)


def _format_validation(e: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(p) for p in err['loc']) or 'arguments'}: {err['msg']}" for err in e.errors())


class AgentOrchestrator:
    def __init__(self, llm: LLMClient, registry: ToolRegistry, settings: Settings):
        self._llm = llm
        self._registry = registry
        self._settings = settings

    def run_stream(
        self,
        *,
        question: str,
        dataset: LoadedDataset,
        session_id: str,
        history: list[Message],
    ) -> Iterator[StreamEvent]:
        started = time.perf_counter()
        ctx = ToolContext(dataset=dataset, settings=self._settings)
        messages = [
            Message(role="system", content=build_system_prompt(dataset.meta, self._settings.max_result_rows)),
            *history,
            Message(role="user", content=question),
        ]
        specs = self._registry.specs()

        steps: list[AgentStep] = []
        sql: str | None = None
        table: TableResult | None = None
        chart: ChartSpec | None = None

        def response(answer: str, error: ErrorInfo | None = None) -> ChatResponse:
            return ChatResponse(
                session_id=session_id,
                dataset_id=dataset.meta.id,
                answer=answer,
                sql=sql,
                table=table,
                chart=chart,
                steps=steps,
                error=error,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
            )

        for _ in range(self._settings.agent_max_steps):
            try:
                reply = self._llm.complete(messages, specs)
            except LLMError as e:
                raise LLMUnavailable(str(e)) from e

            if not reply.tool_calls:
                answer = (reply.content or "").strip() or "(The model returned an empty answer.)"
                yield StreamEvent(type="final", response=response(answer))
                return

            messages.append(reply)
            for call in reply.tool_calls:
                step, output, observation = self._execute(call, ctx, index=len(steps) + 1)
                steps.append(step)
                if output is not None:
                    sql = output.sql or sql
                    table = output.table or table
                    chart = output.chart or chart
                messages.append(Message(role="tool", tool_call_id=call.id, content=observation))
                yield StreamEvent(type="step", step=step)

        yield StreamEvent(
            type="final",
            response=response(
                "Mình chưa tìm ra câu trả lời trong giới hạn số bước cho phép. Bạn thử hỏi cụ thể hơn nhé.",
                error=ErrorInfo(
                    code="max_steps_exceeded",
                    message=f"Agent did not finish within {self._settings.agent_max_steps} steps.",
                ),
            ),
        )

    def _execute(
        self, call: ToolCallRequest, ctx: ToolContext, index: int
    ) -> tuple[AgentStep, ToolOutput | None, str]:
        t0 = time.perf_counter()
        output: ToolOutput | None = None
        try:
            tool = self._registry.get(call.name)
            if tool is None:
                raise ToolError(f"Unknown tool '{call.name}'. Available tools: {self._registry.names}")
            if call.arguments_error:
                raise ToolError(f"Tool arguments are not a valid JSON object: {call.arguments_error}")
            try:
                args = tool.input_model.model_validate(call.arguments)
            except ValidationError as e:
                raise ToolError("Invalid arguments: " + _format_validation(e)) from e
            output = tool.run(args, ctx)
            observation, status = output.observation, "ok"
        except ToolError as e:
            observation, status = dumps({"error": str(e)}), "error"
        except Exception:  # lỗi bất ngờ trong tool: ghi log, báo LLM chung chung
            log.exception("Tool %s crashed", call.name)
            observation, status = dumps({"error": "Internal tool error."}), "error"

        preview = observation if len(observation) <= 300 else observation[:299] + "…"
        step = AgentStep(
            index=index,
            tool=call.name,
            arguments=call.arguments,
            status=status,
            observation_preview=preview,
            duration_ms=int((time.perf_counter() - t0) * 1000),
        )
        return step, output, observation
