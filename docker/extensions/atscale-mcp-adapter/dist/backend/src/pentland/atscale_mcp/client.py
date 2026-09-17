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

"""Small dependency-free AtScale Streamable HTTP MCP client."""

from __future__ import annotations

import json
import os
import ssl
from typing import Any
from urllib import request


class AtScaleMCPError(RuntimeError):
    """Raised when AtScale rejects an MCP request or returns invalid data."""


class AtScaleMCPClient:
    """Call the read-only AtScale metadata tools through Streamable HTTP."""

    def __init__(self, url: str | None = None, token: str | None = None) -> None:
        self.url = url or os.environ["ATSCALE_MCP_URL"]
        self.token = token or os.environ["ATSCALE_TOKEN"]
        self._request_id = 0

    def _post(self, payload: dict[str, Any], session_id: str | None = None) -> tuple[dict[str, Any], str | None]:
        self._request_id += 1
        payload = {**payload, "id": self._request_id, "jsonrpc": "2.0"}
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        req = request.Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        ca_bundle = os.getenv("ATSCALE_MCP_CA_BUNDLE")
        local_cato_root = "/app/docker/certs/cato-root-ca.pem"
        if not ca_bundle and os.path.exists(local_cato_root):
            ca_bundle = local_cato_root
        context = ssl.create_default_context(cafile=ca_bundle or None)
        try:
            with request.urlopen(req, context=context, timeout=60) as response:
                raw = response.read().decode("utf-8")
                response_session = response.headers.get("Mcp-Session-Id")
        except Exception as exc:  # pragma: no cover - network failures are environment-specific
            reason = getattr(exc, "reason", exc)
            raise AtScaleMCPError(f"AtScale MCP request failed: {reason}") from exc

        for line in raw.splitlines():
            if line.startswith("data:"):
                try:
                    message = json.loads(line[5:].strip())
                except json.JSONDecodeError as exc:
                    raise AtScaleMCPError("AtScale returned malformed MCP data") from exc
                if "error" in message:
                    raise AtScaleMCPError(str(message["error"]))
                return message, response_session
        raise AtScaleMCPError("AtScale returned no MCP message")

    def _call(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        _, session_id = self._post(
            {
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "superset-atscale-adapter", "version": "0.1.0"},
                },
            }
        )
        message, _ = self._post(
            {"method": "tools/call", "params": {"name": name, "arguments": arguments or {}}},
            session_id,
        )
        result = message.get("result", {})
        for content in result.get("content", []):
            if content.get("type") == "text":
                text = content.get("text", "")
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return text
        return result

    def list_models(self, force_refresh: bool = False) -> Any:
        """Return every semantic model currently exposed by AtScale."""
        return self._call("list_models", {"force_refresh": force_refresh})

    def describe_model(self, catalog: str, schema: str, table: str) -> Any:
        """Return governed dimensions, measures, and calculation groups."""
        return self._call(
            "describe_model",
            {"catalog": catalog, "schema": schema, "table": table},
        )

    def search_columns(self, search_term: str, model: str | None = None) -> Any:
        """Search AtScale's governed column and measure metadata."""
        arguments: dict[str, Any] = {"search_term": search_term}
        if model:
            arguments["model"] = model
        return self._call("search_columns", arguments)

    def run_query(self, query: str) -> Any:
        """Execute a read-only query against an AtScale semantic model."""
        return self._call("run_query", {"query": query})
