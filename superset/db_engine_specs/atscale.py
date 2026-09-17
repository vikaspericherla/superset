# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
"""Live, read-only SQLAlchemy bridge for AtScale semantic models over MCP."""

from __future__ import annotations

import csv
import io
import json
import re
from collections.abc import Sequence
from typing import Any

from sqlalchemy import types
from sqlalchemy.engine.default import DefaultDialect
from sqlalchemy.engine.reflection import Inspector
from sqlalchemy.engine.url import URL
from superset.db_engine_specs.base import BaseEngineSpec, DatabaseCategory


class AtScaleMCPDBAPIError(Exception):
    """Represent an MCP query failure as a DB-API error."""


class AtScaleMCPDBAPI:
    """Minimal DB-API facade used by SQLAlchemy's AtScale dialect."""

    paramstyle = "pyformat"
    Error = AtScaleMCPDBAPIError
    DatabaseError = AtScaleMCPDBAPIError

    @staticmethod
    def connect(*_: Any, **__: Any) -> AtScaleMCPConnection:
        """Open a lightweight connection that forwards reads through MCP."""
        return AtScaleMCPConnection()


def _client() -> Any:
    """Load the extension client only after Superset has loaded local extensions."""
    try:
        from pentland.atscale_mcp.client import AtScaleMCPClient
    except ImportError as exc:  # pragma: no cover - deployment configuration
        raise AtScaleMCPDBAPIError(
            "AtScale MCP extension is not installed. Enable atscale-mcp-adapter first."
        ) from exc
    return AtScaleMCPClient()


def _model_name(model: dict[str, Any]) -> str:
    """Return the user-facing schema name for a discovered semantic model."""
    return str(model.get("name") or model.get("table_name") or "")


def _models() -> list[dict[str, Any]]:
    """Return valid semantic model records supplied by AtScale."""
    result = _client().list_models()
    if not isinstance(result, list):
        raise AtScaleMCPDBAPIError("AtScale returned invalid semantic model metadata")
    return [model for model in result if isinstance(model, dict) and _model_name(model)]


def _find_model(schema: str | None, table: str | None) -> dict[str, Any]:
    """Resolve a Superset schema/table reference to AtScale model metadata."""
    for model in _models():
        if schema in {_model_name(model), model.get("table_schema")} and (
            table is None or table == model.get("table_name")
        ):
            return model
    raise AtScaleMCPDBAPIError("The requested AtScale semantic model is not available")


def _column_type(data_type: str | None) -> types.TypeEngine[Any]:
    """Map AtScale metadata types to SQLAlchemy types used by Superset."""
    normalized = (data_type or "").lower()
    if any(value in normalized for value in ("date", "time")):
        return types.DateTime()
    if any(
        value in normalized
        for value in ("int", "decimal", "numeric", "double", "float")
    ):
        return types.Numeric()
    if "bool" in normalized:
        return types.Boolean()
    return types.String()


def _parse_result(result: Any) -> tuple[list[str], list[tuple[Any, ...]]]:
    """Parse JSON or tabular text returned by AtScale's ``run_query`` MCP tool."""
    if isinstance(result, dict):
        rows = result.get("rows") or result.get("data")
        columns = result.get("columns") or result.get("headers")
        if isinstance(rows, list) and isinstance(columns, list):
            names = [
                str(column.get("name", "")) if isinstance(column, dict) else str(column)
                for column in columns
            ]
            return names, [
                tuple(row.values()) if isinstance(row, dict) else tuple(row)
                for row in rows
            ]
    if isinstance(result, list) and result and isinstance(result[0], dict):
        names = list(result[0])
        return names, [tuple(row.get(name) for name in names) for row in result]
    if isinstance(result, str):
        try:
            return _parse_result(json.loads(result))
        except json.JSONDecodeError:
            records = list(csv.reader(io.StringIO(result), delimiter="\t"))
            if not records:
                return [], []
            return records[0], [tuple(row) for row in records[1:]]
    raise AtScaleMCPDBAPIError("AtScale returned a query result format the bridge cannot parse")


class AtScaleMCPConnection:
    """DB-API connection backed by the configured AtScale MCP endpoint."""

    def cursor(self) -> AtScaleMCPCursor:
        """Create a cursor that runs a single read-only semantic-model query."""
        return AtScaleMCPCursor()

    def close(self) -> None:
        """Close the stateless MCP connection."""

    def commit(self) -> None:
        """MCP is read-only, so commits are intentionally no-ops."""

    def rollback(self) -> None:
        """MCP is read-only, so rollbacks are intentionally no-ops."""


class AtScaleMCPCursor:
    """Execute SQL by resolving semantic model aliases and invoking MCP."""

    arraysize = 1

    def __init__(self) -> None:
        self.description: Sequence[tuple[Any, ...]] | None = None
        self._rows: list[tuple[Any, ...]] = []
        self._position = 0
        self.rowcount = -1

    @staticmethod
    def _physical_query(query: str) -> str:
        """Replace Superset's model schema/table alias with AtScale's physical path."""
        pattern = re.compile(r'"(?P<schema>[^"]+)"\."(?P<table>[^"]+)"')

        def replace(match: re.Match[str]) -> str:
            model = _find_model(match.group("schema"), match.group("table"))
            catalog = str(model["table_catalog"]).replace('"', '""')
            schema = str(model["table_schema"]).replace('"', '""')
            table = str(model["table_name"]).replace('"', '""')
            return f'"{catalog}"."{schema}"."{table}"'

        return pattern.sub(replace, query)

    def execute(self, operation: str, parameters: Any = None) -> AtScaleMCPCursor:
        """Execute only a SELECT/WITH statement using AtScale governed logic."""
        if parameters:
            raise AtScaleMCPDBAPIError("AtScale MCP bridge does not support bound parameters")
        if not re.match(r"^\s*(SELECT|WITH)\b", operation, flags=re.IGNORECASE):
            raise AtScaleMCPDBAPIError("AtScale MCP bridge permits read-only SELECT queries only")
        columns, rows = _parse_result(_client().run_query(self._physical_query(operation)))
        self.description = [(column, None, None, None, None, None, None) for column in columns]
        self._rows = rows
        self._position = 0
        self.rowcount = len(rows)
        return self

    def fetchone(self) -> tuple[Any, ...] | None:
        """Return the next row in the AtScale result."""
        if self._position >= len(self._rows):
            return None
        row = self._rows[self._position]
        self._position += 1
        return row

    def fetchmany(self, size: int | None = None) -> list[tuple[Any, ...]]:
        """Return the next requested number of rows."""
        count = size or self.arraysize
        rows = self._rows[self._position : self._position + count]
        self._position += len(rows)
        return rows

    def fetchall(self) -> list[tuple[Any, ...]]:
        """Return all remaining rows."""
        rows = self._rows[self._position :]
        self._position = len(self._rows)
        return rows

    def close(self) -> None:
        """Release the cursor result buffer."""
        self._rows = []


class AtScaleMCPDialect(DefaultDialect):
    """SQLAlchemy reflection dialect backed by live AtScale MCP metadata."""

    name = "atscale"
    driver = "mcp"
    supports_statement_cache = False

    @classmethod
    def import_dbapi(cls) -> type[AtScaleMCPDBAPI]:
        """Return the dependency-free DB-API facade."""
        return AtScaleMCPDBAPI

    @classmethod
    def dbapi(cls) -> type[AtScaleMCPDBAPI]:
        """Support SQLAlchemy versions that use the legacy DB-API hook."""
        return cls.import_dbapi()

    def get_schema_names(self, connection: Any, **_: Any) -> list[str]:
        """Expose each AtScale semantic model as a Superset schema."""
        return [_model_name(model) for model in _models()]

    def get_table_names(
        self, connection: Any, schema: str | None = None, **_: Any
    ) -> list[str]:
        """Expose the selected semantic model as its governed logical table."""
        if schema is None:
            return []
        return [str(_find_model(schema, None)["table_name"])]

    def has_table(
        self,
        connection: Any,
        table_name: str,
        schema: str | None = None,
        **_: Any,
    ) -> bool:
        """Check whether a logical AtScale model table exists."""
        try:
            model = _find_model(schema, table_name)
        except AtScaleMCPDBAPIError:
            return False
        return table_name == model.get("table_name")

    def get_view_names(
        self, connection: Any, schema: str | None = None, **_: Any
    ) -> list[str]:
        """AtScale semantic models are logical tables, not SQL views."""
        return []

    def get_pk_constraint(
        self,
        connection: Any,
        table_name: str,
        schema: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        """Semantic models do not expose physical primary-key constraints."""
        return {"constrained_columns": [], "name": None}

    def get_foreign_keys(
        self,
        connection: Any,
        table_name: str,
        schema: str | None = None,
        **_: Any,
    ) -> list[dict[str, Any]]:
        """Semantic-model relationships are governed by AtScale, not foreign keys."""
        return []

    def get_indexes(
        self,
        connection: Any,
        table_name: str,
        schema: str | None = None,
        **_: Any,
    ) -> list[dict[str, Any]]:
        """AtScale does not expose physical indexes through MCP."""
        return []

    def get_table_comment(
        self,
        connection: Any,
        table_name: str,
        schema: str | None = None,
        **_: Any,
    ) -> dict[str, None]:
        """Return an empty physical-table comment for a semantic model."""
        return {"text": None}

    def get_columns(
        self,
        connection: Any,
        table_name: str,
        schema: str | None = None,
        **_: Any,
    ) -> list[dict[str, Any]]:
        """Reflect measures and dimensions directly from AtScale model metadata."""
        model = _find_model(schema, table_name)
        columns = _client().describe_model(
            str(model["table_catalog"]), str(model["table_schema"]), str(model["table_name"])
        )
        if not isinstance(columns, list):
            raise AtScaleMCPDBAPIError("AtScale returned invalid column metadata")
        return [
            {
                "name": str(column["column_name"]),
                "type": _column_type(column.get("data_type")),
                "nullable": True,
                "default": None,
                "comment": column.get("column_remark"),
            }
            for column in columns
            if isinstance(column, dict) and column.get("column_name")
        ]


class AtScaleMCPEngineSpec(BaseEngineSpec):
    """Superset database specification for the live AtScale MCP bridge."""

    engine = "atscale"
    engine_name = "AtScale semantic models (MCP)"
    default_driver = "mcp"
    drivers = {"mcp": "AtScale MCP"}
    disable_ssh_tunneling = True
    supports_schemas = True
    metadata = {
        "description": "Live read-only AtScale semantic models accessed through MCP.",
        "categories": [DatabaseCategory.ANALYTICAL_DATABASES],
        "pypi_packages": [],
        "connection_string": "atscale+mcp://",
        "notes": "Measures, dimensions, and calculations stay governed by AtScale.",
    }

    @classmethod
    def get_metrics(
        cls, database: Any, inspector: Inspector, table: Any
    ) -> list[dict[str, str]]:
        """Expose each governed AtScale measure as a non-duplicated SQL metric."""
        model = _find_model(table.schema, table.table)
        columns = _client().describe_model(
            str(model["table_catalog"]),
            str(model["table_schema"]),
            str(model["table_name"]),
        )
        if not isinstance(columns, list):
            raise AtScaleMCPDBAPIError("AtScale returned invalid metric metadata")
        metrics = []
        for column in columns:
            if not isinstance(column, dict) or column.get("role", "").lower() != "measure":
                continue
            name = str(column.get("column_name", ""))
            if name:
                metrics.append(
                    {
                        "metric_name": name,
                        "verbose_name": name,
                        "metric_type": "SQL",
                        "expression": f'"{name.replace(chr(34), chr(34) * 2)}"',
                    }
                )
        return metrics


from sqlalchemy.dialects import registry

registry.register("atscale.mcp", "superset.db_engine_specs.atscale", "AtScaleMCPDialect")
