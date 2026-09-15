# Code references and adaptation boundaries

## Official MCP reference server

Source: MCP Python SDK, `examples/snippets/servers/fastmcp_quickstart.py`.
Revision: `8c2fa6eabacde869d75568e33b9d466b58c2f512` (v1.x branch checked 2026-09-15).

https://github.com/modelcontextprotocol/python-sdk/blob/8c2fa6eabacde869d75568e33b9d466b58c2f512/examples/snippets/servers/fastmcp_quickstart.py

`server.py:create_server` adapts `FastMCP` initialization and the `@mcp.tool()` and
`@mcp.prompt()` registration patterns. The sample addition/greeting functions were
replaced with coursework operations. The sample uses Streamable HTTP; this project
uses stdio. Validation, rate limiting, persistence and planning rules were written
for this project with AI assistance, not copied from the sample's business logic.

## Official MCP client example

https://github.com/modelcontextprotocol/python-sdk/blob/8c2fa6eabacde869d75568e33b9d466b58c2f512/examples/snippets/clients/stdio_client.py

`demo_checks.py` and `show_prompt.py` adapt `StdioServerParameters`, `stdio_client`,
`ClientSession`, initialization, and endpoint-call patterns. The temporary files,
exploit assertions, encrypted-storage check and recovery test are project-specific.
No sampling callback or remote model code was copied.

## Configuration and storage APIs

- `make_config.py`: JSON client configuration shape from
  https://modelcontextprotocol.io/docs/develop/connect-local-servers .
- `config.py:load_settings`: `dotenv_values` dictionary-loading pattern from
  https://bbc2.github.io/python-dotenv/#load-configuration-without-altering-the-environment .
  Adaptation: an explicit `Path`, no system-secret fallback, no interpolation, and validation.
- `init_local.py:initialize`, `task_manager.py:encrypt/decrypt`: Fernet API usage from
  https://cryptography.io/en/latest/fernet/ . Encryption itself is provided by the library.
- `task_manager.py:add_assignment/delete_assignment`: SQLite transaction behavior
  from https://www.sqlite.org/lang_transaction.html . `BEGIN IMMEDIATE` protects
  duplicate checking plus insertion, and targeted deletion, within write transactions.
- `task_manager.py:add_assignment/delete_assignment`: SQLite placeholder usage from
  https://docs.python.org/3/library/sqlite3.html#sqlite3-placeholders .

These are references to specific API patterns, not claims that complete files were
copied. Inline comments identify the relevant code. SDK license attribution appears
in `THIRD_PARTY_NOTICES.md`; installed dependencies include their own license metadata.
