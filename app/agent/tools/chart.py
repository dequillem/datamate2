from app.agent.tools.base import Tool, ToolContext, ToolError, ToolOutput, dumps
from app.schemas.results import ChartSpec
from app.schemas.tools import CreateChartInput
from app.services.query_engine import QueryError


class CreateChartTool(Tool):
    name = "create_chart"
    description = (
        "Run a read-only SQL query and turn its result into a chart that the UI renders. The query must return "
        "the columns named in x and y (and color, if given). Use bar for category comparison, line for time "
        "series, pie for shares of a whole, scatter for two numeric columns."
    )
    input_model = CreateChartInput

    def run(self, args: CreateChartInput, ctx: ToolContext) -> ToolOutput:
        try:
            table = ctx.dataset.engine.run(args.sql, max_rows=ctx.settings.max_result_rows)
        except QueryError as e:
            raise ToolError(str(e)) from e

        if not table.rows:
            raise ToolError("The SQL returned no rows, so there is nothing to chart.")

        lookup = {c.lower(): i for i, c in enumerate(table.columns)}

        def column(name: str, role: str) -> tuple[str, int]:
            i = lookup.get(name.lower())
            if i is None:
                raise ToolError(f"{role} column '{name}' is not in the SQL result. Result columns: {table.columns}")
            return table.columns[i], i

        x, _ = column(args.x, "x")
        y, y_idx = column(args.y, "y")
        color = column(args.color, "color")[0] if args.color else None

        for row in table.rows:
            v = row[y_idx]
            if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))):
                raise ToolError(f"y column '{y}' must be numeric but contains {v!r}. Aggregate it (SUM/AVG/COUNT).")

        chart = ChartSpec(
            chart_type=args.chart_type,
            title=args.title or f"{y} by {x}",
            x=x,
            y=y,
            color=color,
            data=[dict(zip(table.columns, row)) for row in table.rows],
        )
        observation = dumps(
            {
                "chart_created": True,
                "chart_type": chart.chart_type,
                "columns": table.columns,
                "row_count": table.row_count,
                "rows_preview": table.rows[:10],
            }
        )
        return ToolOutput(observation=observation, table=table, chart=chart, sql=args.sql.strip().rstrip(";"))
