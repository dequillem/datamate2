import json

import pytest

from app.agent.tools import default_registry
from app.agent.tools.base import ToolContext, ToolError
from app.schemas.tools import CreateChartInput, DescribeDatasetInput, RunSqlInput

registry = default_registry()


@pytest.fixture
def ctx(sales, settings):
    return ToolContext(dataset=sales, settings=settings)


def test_registry_exposes_three_tools_with_json_schema():
    specs = {s.name: s for s in registry.specs()}
    assert set(specs) == {"describe_dataset", "run_sql", "create_chart"}
    assert "sql" in specs["run_sql"].parameters["properties"]
    assert specs["create_chart"].parameters["properties"]["chart_type"]["enum"] == ["bar", "line", "pie", "scatter"]


def test_describe_all_columns(ctx):
    out = registry.get("describe_dataset").run(DescribeDatasetInput(), ctx)
    (table,) = json.loads(out.observation)["tables"]
    assert table["name"] == "sales" and table["n_rows"] == 400 and len(table["columns"]) == 9


def test_describe_specific_columns_is_case_insensitive(ctx):
    out = registry.get("describe_dataset").run(DescribeDatasetInput(columns=["REGION"]), ctx)
    (table,) = json.loads(out.observation)["tables"]
    assert [c["name"] for c in table["columns"]] == ["region"]


def test_describe_unknown_table(ctx):
    with pytest.raises(ToolError, match="Unknown table"):
        registry.get("describe_dataset").run(DescribeDatasetInput(table="nope"), ctx)


def test_describe_multi_table_database(settings):
    from app.services.dataset_store import DatasetStore
    from tests.test_dataset_store import make_sqlite

    make_sqlite(settings.sample_dir / "school.sqlite")
    ctx = ToolContext(dataset=DatasetStore(settings).get("school"), settings=settings)
    tool = registry.get("describe_dataset")

    tables = json.loads(tool.run(DescribeDatasetInput(), ctx).observation)["tables"]
    assert {t["name"] for t in tables} == {"dept", "emp"}
    emp = next(t for t in tables if t["name"] == "emp")
    assert emp["foreign_keys"] == [{"column": "dept_id", "ref_table": "dept", "ref_column": "id"}]

    with pytest.raises(ToolError, match="set `table`"):
        tool.run(DescribeDatasetInput(columns=["name"]), ctx)
    one = json.loads(tool.run(DescribeDatasetInput(table="dept", columns=["name"]), ctx).observation)["tables"]
    assert [c["name"] for c in one[0]["columns"]] == ["name"]


def test_describe_unknown_column_lists_valid_ones(ctx):
    with pytest.raises(ToolError, match="Available"):
        registry.get("describe_dataset").run(DescribeDatasetInput(columns=["nope"]), ctx)


def test_run_sql_returns_table_and_compact_observation(ctx):
    out = registry.get("run_sql").run(RunSqlInput(sql="SELECT * FROM sales;"), ctx)
    assert out.table.row_count == 50 and out.table.truncated  # settings.max_result_rows = 50
    obs = json.loads(out.observation)
    assert len(obs["rows"]) == 20 and obs["truncated"] is True  # LLM chỉ nhận 20 dòng đầu
    assert out.sql == "SELECT * FROM sales"


def test_run_sql_error_is_a_soft_tool_error(ctx):
    with pytest.raises(ToolError, match="SQLite error"):
        registry.get("run_sql").run(RunSqlInput(sql="SELECT nope FROM sales"), ctx)


def test_create_chart_builds_spec(ctx):
    args = CreateChartInput(
        sql="SELECT region, SUM(revenue) AS total FROM sales GROUP BY 1",
        chart_type="bar",
        x="region",
        y="TOTAL",  # không phân biệt hoa thường
    )
    out = registry.get("create_chart").run(args, ctx)
    assert out.chart.chart_type == "bar" and out.chart.y == "total"
    assert out.chart.title == "total by region"
    assert len(out.chart.data) == 5 and set(out.chart.data[0]) == {"region", "total"}


def test_create_chart_rejects_missing_column(ctx):
    args = CreateChartInput(sql="SELECT region FROM sales", chart_type="bar", x="region", y="total")
    with pytest.raises(ToolError, match="Result columns"):
        registry.get("create_chart").run(args, ctx)


def test_create_chart_rejects_non_numeric_y(ctx):
    args = CreateChartInput(sql="SELECT region, category FROM sales", chart_type="bar", x="region", y="category")
    with pytest.raises(ToolError, match="numeric"):
        registry.get("create_chart").run(args, ctx)


def test_tool_inputs_forbid_unknown_fields():
    with pytest.raises(ValueError):
        RunSqlInput.model_validate({"sql": "SELECT 1", "query": "oops"})
