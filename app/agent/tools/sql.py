from app.agent.tools.base import Tool, ToolContext, ToolError, ToolOutput, dumps, table_observation
from app.schemas.tools import RunSqlInput
from app.services.query_engine import QueryError


class RunSqlTool(Tool):
    name = "run_sql"
    description = (
        "Run ONE read-only SQLite statement (SELECT or WITH ... SELECT) over the dataset tables and return "
        "the rows. Prefer aggregation (GROUP BY, LIMIT) to listing raw rows."
    )
    input_model = RunSqlInput

    def run(self, args: RunSqlInput, ctx: ToolContext) -> ToolOutput:
        try:
            table = ctx.dataset.engine.run(args.sql, max_rows=ctx.settings.max_result_rows)
        except QueryError as e:
            raise ToolError(str(e)) from e
        return ToolOutput(
            observation=dumps(table_observation(table)),
            table=table,
            sql=args.sql.strip().rstrip(";"),
        )
