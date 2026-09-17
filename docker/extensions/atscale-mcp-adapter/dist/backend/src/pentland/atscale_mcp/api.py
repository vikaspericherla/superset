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

from __future__ import annotations

from flask import Response, request
from flask_appbuilder.api import expose, protect, safe
from superset import db
from superset.connectors.sqla.models import SqlaTable
from superset.models.core import Database
from superset_core.rest_api.api import RestApi
from superset_core.rest_api.decorators import api

from .client import AtScaleMCPClient, AtScaleMCPError


@api(
    id="atscale_mcp_api",
    name="AtScale MCP Adapter",
    description="Expose AtScale semantic models and governed metadata dynamically.",
)
class AtScaleMCPAPI(RestApi):
    """REST facade for AtScale model discovery."""

    openapi_spec_tag = "AtScale MCP"
    class_permission_name = "AtScaleMCP"

    @expose("/models", methods=("GET",))
    @protect()
    @safe
    def models(self) -> Response:
        """List all AtScale semantic models."""
        return self._call(lambda: AtScaleMCPClient().list_models(request.args.get("force_refresh") == "true"))

    @expose("/model", methods=("GET",))
    @protect()
    @safe
    def model(self) -> Response:
        """Return the governed metadata for one semantic model."""
        required = ("catalog", "schema", "table")
        values = {key: request.args.get(key) for key in required}
        if any(not value for value in values.values()):
            return self.response(400, message="catalog, schema, and table are required")
        return self._call(lambda: AtScaleMCPClient().describe_model(**values))

    @expose("/columns", methods=("GET",))
    @protect()
    @safe
    def columns(self) -> Response:
        """Search governed AtScale dimensions and measures."""
        search_term = request.args.get("q")
        if not search_term:
            return self.response(400, message="q is required")
        return self._call(lambda: AtScaleMCPClient().search_columns(search_term, request.args.get("model")))

    @expose("/dataset", methods=("POST",))
    @protect()
    @safe
    def dataset(self) -> Response:
        """Create or refresh a live dataset and return its Explore URL."""
        payload = request.get_json(silent=True) or {}
        model_name = payload.get("model")
        if not isinstance(model_name, str) or not model_name:
            return self.response(400, message="model is required")
        try:
            models = AtScaleMCPClient().list_models()
            model = next(
                item
                for item in models
                if isinstance(item, dict)
                and model_name in {item.get("name"), item.get("table_name")}
            )
            schema = str(model.get("name") or model["table_name"])
            table_name = str(model["table_name"])
            database = (
                db.session.query(Database)
                .filter_by(database_name="AtScale MCP")
                .one_or_none()
            )
            if database is None:
                return self.response(409, message="AtScale MCP database is not configured")
            dataset = (
                db.session.query(SqlaTable)
                .filter_by(
                    database_id=database.id,
                    schema=schema,
                    table_name=table_name,
                )
                .one_or_none()
            )
            if dataset is None:
                dataset = SqlaTable(
                    table_name=table_name,
                    schema=schema,
                    database=database,
                )
                db.session.add(dataset)
            dataset.fetch_metadata()
            db.session.commit()
            return self.response(
                200,
                result={"dataset_id": dataset.id, "explore_url": dataset.explore_url},
            )
        except (AtScaleMCPError, KeyError, StopIteration) as exc:
            db.session.rollback()
            return self.response(502, message=str(exc))

    def _call(self, operation: object) -> Response:
        try:
            return self.response(200, result=operation())  # type: ignore[operator]
        except (AtScaleMCPError, KeyError) as exc:
            return self.response(502, message=str(exc))
