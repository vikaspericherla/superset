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

from superset_core.mcp.decorators import tool

from .client import AtScaleMCPClient


@tool(name="atscale.list_semantic_models", tags=["atscale", "metadata", "read-only"])
def list_semantic_models(force_refresh: bool = False) -> object:
    """Discover all semantic models and their governed model metadata."""
    return AtScaleMCPClient().list_models(force_refresh)


@tool(name="atscale.describe_semantic_model", tags=["atscale", "metadata", "read-only"])
def describe_semantic_model(catalog: str, schema: str, table: str) -> object:
    """Discover the measures, dimensions, and calculation groups for a model."""
    return AtScaleMCPClient().describe_model(catalog, schema, table)


@tool(name="atscale.search_semantic_columns", tags=["atscale", "metadata", "read-only"])
def search_semantic_columns(search_term: str, model: str | None = None) -> object:
    """Search AtScale's governed dimensions and measures without local duplication."""
    return AtScaleMCPClient().search_columns(search_term, model)
