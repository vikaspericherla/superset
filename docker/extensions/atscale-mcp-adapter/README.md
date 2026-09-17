# AtScale MCP Adapter

This local extension exposes AtScale's governed semantic metadata through
Superset's protected REST and MCP surfaces. Measures, dimensions, and
calculation groups are fetched from AtScale at request time.

The adapter reads `ATSCALE_MCP_URL` and `ATSCALE_TOKEN` from the container
environment. If the AtScale certificate chain is signed by a private
corporate CA, mount that PEM bundle and set `ATSCALE_MCP_CA_BUNDLE` to its
container path. TLS verification remains enabled.

The REST endpoints are available after authentication at:

- `/extensions/pentland/atscale-mcp-adapter/models`
- `/extensions/pentland/atscale-mcp-adapter/model?catalog=...&schema=...&table=...`
- `/extensions/pentland/atscale-mcp-adapter/columns?q=...&model=...`

The same operations are available to Superset MCP clients as:

- `extensions.pentland.atscale-mcp-adapter.atscale.list_semantic_models`
- `extensions.pentland.atscale-mcp-adapter.atscale.describe_semantic_model`
- `extensions.pentland.atscale-mcp-adapter.atscale.search_semantic_columns`
