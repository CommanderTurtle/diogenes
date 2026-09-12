module ConvertedFiles.Extending.IndexMd

let file = """# Extending Diogenes

Diogenes can be extended at four layers: skill Markdown, MCP servers, built-in Python tools, and HTTP integrations. Each layer has a different registration and execution path.

## Choose an extension path

| Need | Path | Registration |
| --- | --- | --- |
| reusable model instructions | skill | `data/skills/.../SKILL.md` or `/api/skills` |
| tools from another process | MCP | `McpServer` row through `/api/mcp/servers` |
| in-process model function | built-in tool | handler, schema, index entry, policy entry |
| call an existing HTTP service | integration | `/api/auth/integrations` plus `api_call` |
| notify another HTTP receiver | webhook | `/api/webhooks` |
| LAN client chat access | API token or companion pair | `/api/tokens`, `/api/companion/pair` |

## Execution map

~~~ mermaid
flowchart TD
    A[model request] --> B[tool index]
    B --> C[OpenAI function schemas]
    C --> D[tool parsing]
    D --> E[policy and approval]
    E --> F{qualified MCP name?}
    F -- yes --> G[McpManager.call_tool]
    F -- no --> H[TOOL_HANDLERS]
    H --> I[in-process handler]
    G --> J[paired tool result]
    I --> J
~~~

`src/tool_index.py` selects a small schema set for each prompt. `src/tool_schemas.py` supplies OpenAI-compatible schemas. `src/tool_parsing.py` normalizes native calls and fenced call formats. `src/tool_execution.py` applies policy and invokes the selected handler.

## Development pages

- [Skills and instructions](skills.md) covers the skill file format, indexing, imports, tests, and audits.
- [MCP and built-in tools](mcp-tools.md) covers server registration and a complete in-process tool addition.
- [API, CLI, and companion](api-cli.md) covers bearer tokens, chat requests, pairing, and command dispatch.
- [Integrations and webhooks](integrations.md) covers HTTP service records, `api_call`, and event delivery.

## Minimum test set

An extension should cover:

1. valid registration;
2. malformed configuration;
3. unavailable dependency;
4. user and role filtering;
5. approval classification;
6. tool result pairing;
7. redaction of credentials;
8. browser rendering of errors.
"""

let render() = file
