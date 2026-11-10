from app.agent.tools.base import Tool, ToolContext, ToolError, ToolOutput, dumps
from app.schemas.tools import DescribeDatasetInput


class DescribeDatasetTool(Tool):
    name = "describe_dataset"
    description = (
        "Return a detailed profile (dtype, null %, distinct count, min, max, example values, primary/foreign keys) "
        "of the database's tables and columns. Omit `table` to profile every table; omit `columns` for every column."
    )
    input_model = DescribeDatasetInput

    def run(self, args: DescribeDatasetInput, ctx: ToolContext) -> ToolOutput:
        meta = ctx.dataset.meta
        by_table = {t.name.lower(): t for t in meta.tables}

        if args.table:
            table = by_table.get(args.table.lower())
            if table is None:
                raise ToolError(f"Unknown table '{args.table}'. Available: {[t.name for t in meta.tables]}")
            tables = [table]
        else:
            tables = meta.tables

        if args.columns and len(tables) > 1:
            raise ToolError(f"Several tables exist; set `table` to one of {[t.name for t in tables]}.")

        result = []
        for table in tables:
            columns = table.columns
            if args.columns:
                by_name = {c.name.lower(): c for c in table.columns}
                missing = [c for c in args.columns if c.lower() not in by_name]
                if missing:
                    raise ToolError(f"Unknown column(s): {missing}. Available: {[c.name for c in table.columns]}")
                columns = [by_name[c.lower()] for c in args.columns]
            result.append(
                {
                    "name": table.name,
                    "n_rows": table.n_rows,
                    "primary_key": table.primary_key,
                    "foreign_keys": [f.model_dump() for f in table.foreign_keys],
                    "columns": [c.model_dump() for c in columns],
                }
            )
        return ToolOutput(observation=dumps({"tables": result}))
