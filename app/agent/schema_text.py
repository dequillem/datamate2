"""Biến metadata dataset thành đoạn text schema đưa vào prompt (dạng CREATE TABLE, SLM đọc quen nhất)."""

import json

from app.schemas.dataset import DatasetMeta, TableMeta


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def render_table(table: TableMeta, with_examples: bool = True) -> str:
    lines = []
    for col in table.columns:
        line = f"  {_q(col.name)} {col.dtype}"
        lines.append(line)

    constraints = []
    if table.primary_key:
        constraints.append(f"  PRIMARY KEY ({', '.join(_q(c) for c in table.primary_key)})")
    for fk in table.foreign_keys:
        target = f"{_q(fk.ref_table)}" + (f"({_q(fk.ref_column)})" if fk.ref_column else "")
        constraints.append(f"  FOREIGN KEY ({_q(fk.column)}) REFERENCES {target}")

    body = []
    all_lines = lines + constraints
    for i, text in enumerate(all_lines):
        comma = "," if i < len(all_lines) - 1 else ""
        comment = ""
        if with_examples and i < len(table.columns):
            examples = table.columns[i].examples
            if examples:
                comment = "  -- e.g. " + ", ".join(json.dumps(e, ensure_ascii=False) for e in examples)
        body.append(f"{text}{comma}{comment}")

    return f"CREATE TABLE {_q(table.name)} (\n" + "\n".join(body) + f"\n);  -- {table.n_rows} rows"


def render_schema(meta: DatasetMeta, with_examples: bool = True) -> str:
    return "\n\n".join(render_table(t, with_examples) for t in meta.tables)
