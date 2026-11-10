from app.agent.tools.base import Tool
from app.agent.tools.chart import CreateChartTool
from app.agent.tools.describe import DescribeDatasetTool
from app.agent.tools.sql import RunSqlTool
from app.schemas.tools import ToolSpec


class ToolRegistry:
    def __init__(self, tools: list[Tool]):
        self._tools = {t.name: t for t in tools}

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    @property
    def names(self) -> list[str]:
        return list(self._tools)

    def specs(self) -> list[ToolSpec]:
        return [t.spec() for t in self._tools.values()]


def default_registry() -> ToolRegistry:
    """Danh sách tool agent được dùng. Thêm tool mới thì khai báo ở đây."""
    return ToolRegistry([DescribeDatasetTool(), RunSqlTool(), CreateChartTool()])
