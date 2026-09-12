module DiogenesDocs.Reference.FeatureMatrixMd

let file = """# Feature matrix

This matrix maps each user surface to its route and implementation module. **Included** means the repository contains both browser and server code. **Configured** means the path also needs a model, service, account, or system package.

## Chat and agents

| Surface | State | Browser entry | Server entry |
| --- | --- | --- | --- |
| streaming chat | Included | `static/js/chat.js` | `POST /api/chat_stream` |
| detached generation and resume | Included | `static/js/chat.js` | `src/agent_runs.py`; `GET /api/chat/resume/{session_id}` |
| session create, fork, rename, archive, export | Included | session sidebar and `/chats` | session and history routes |
| reasoning display | Included | `static/js/chatRenderer.js` | normalized events from `src/llm_core.py` |
| native function calls | Configured | tool cards in chat | `src/agent_loop.py` and `src/tool_index.py` |
| tool approvals | Included | approval card | `src/tool_approvals.py` |
| file and process tools | Configured | agent toggle and workspace selector | `src/agent_tools/`; `src/tool_execution.py` |
| built-in web search and fetch | Configured | Web toggle | search services and web tool handlers |
| MCP tools | Configured | Settings → MCP | `/api/mcp`; `src/mcp_manager.py` |
| context trimming and compaction | Included | chat notice and `/compact` | `src/context_budget.py`; chat processing modules |
| model comparison | Included | Compare panel | `/api/compare`; paired chat streams |

## Models and media

| Surface | State | Browser entry | Server entry |
| --- | --- | --- | --- |
| endpoint discovery | Included | Settings → Models | model endpoint routes and `src/model_discovery.py` |
| OpenAI-compatible chat | Configured | endpoint editor | `src/endpoint_resolver.py`; `src/llm_core.py` |
| hosted provider sessions | Configured | `/setup` and endpoint editor | provider authentication routes |
| direct base64 vision | Configured | Settings → Vision | `vision_direct_base64` path in chat and LLM modules |
| progressive image resize retry | Configured | Settings → Vision | `vision_auto_resize_retry` processing |
| image generation | Configured | Gallery and chat | image routes and provider adapter |
| speech to text | Configured | microphone and media panels | `/api/stt` paths |
| text to speech | Configured | message playback | `/api/tts` paths |
| gallery and image editor | Included | `/gallery` | gallery routes and database tables |

## Research

| Surface | State | Browser entry | Server entry |
| --- | --- | --- | --- |
| research jobs | Configured | Deep Research panel | `/api/research/start`; `src/research_handler.py` |
| search and page extraction | Configured | provider controls | `services/search/`; `src/search/` |
| progress, cancel, reconnect | Included | job reader | status, stream, cancel, active-job, and disk-result routes |
| Markdown and HTML report | Included | report actions | `src/visual_report.py` |
| arXiv paper mode | Included | `document_mode=arxiv` | `ARXIV_MODE_PROMPT`; `src/research_documents.py` |
| fiction and nonfiction modes | Included | `document_mode=novel` | narrative prompts and book reader |
| attachment input | Included | research file picker | user-scoped attachment IDs on `ResearchStartRequest` |

## Workspace

| Surface | State | Browser entry | Server entry |
| --- | --- | --- | --- |
| document editor and revisions | Included | `/library` | document and version tables |
| personal document extraction | Configured | Library uploads | personal-document routes and extractors |
| RAG | Configured | Library and Settings | Chroma/embedding lanes |
| memory | Included | Brain and `/memory` | memory manager and `memories` table |
| skills | Included | Brain and `/skills` | skill manager, skill files, and tool index |
| notes | Included | `/notes` | note routes and `notes` table |
| tasks and run history | Included | `/tasks` | scheduler and task tables |
| calendars and events | Included | `/calendar` | calendar routes and tables |
| email | Configured | `/email` | IMAP/SMTP routes and mail databases |
| contacts | Configured | Email and contacts views | contacts routes and CardDAV adapters |

## Workstation controls

| Surface | State | Browser entry | Server entry |
| --- | --- | --- | --- |
| registered service inventory | Configured | Settings → Services | `/api/odysseus`; runtime catalog modules |
| Docker project controls | Configured | Services tree | `src/diogenes_docker_projects.py` |
| install, update, and integration jobs | Configured | service action controls | runtime management and job runner modules |
| mm-tools launch panel | Configured | Settings → Venvs | `src/diogenes_host_services.py` |
| operator terminal tabs | Configured | Venvs → Shell | operator tmux routes and WebSocket |
| Cookbook model serving | Configured | `/cookbook` | Cookbook routes and task manager |
| Colibri GLM and Hy3 | Configured | Cookbook engine selector | `src/ulysses_colibri*.py` |
| PrismML | Configured | Cookbook engine selector | `src/ulysses_prism*.py` |
| isolated model download | Configured | Cookbook downloads | `scripts/hf_download.py` and download jobs |

## Administration and transport

| Surface | State | Entry |
| --- | --- | --- |
| authentication and TOTP | Included | auth middleware and authentication routes |
| per-user data scoping | Included | route filters and database user columns |
| API tokens | Included | token routes and `api_tokens` table |
| webhooks | Included | webhook routes and `scripts/odysseus-webhook` |
| companion pairing | Included | companion routes and client |
| backup, verify, restore | Included | `scripts/odysseus-backup` |
| service diagnostics | Included | `/api/health`, `/api/ready`, `/api/runtime`, `/api/diagnostics/services` |
| SSE chat events | Included | `/api/chat_stream` and resume buffer |
| research event stream | Included | `/api/research/stream/{id}` |
| operator terminal WebSocket | Configured | `/api/odysseus/host-shell/sessions/{shell_id}/ws` |

## Platform notes

| Path | Linux / WSL | macOS | Windows | Container |
| --- | :---: | :---: | :---: | :---: |
| web application | yes | yes | yes | yes |
| SQLite and JSON data | yes | yes | yes | yes |
| browser UI over LAN | yes | yes | yes | yes |
| operator tmux terminal | yes | yes | no | host-dependent |
| CUDA model engines | yes | no | through WSL | GPU runtime needed |
| MLX image path | no | yes | no | no |

“Configured” is a code-path status, not an installation result. Use the page linked by the browser entry to supply the required endpoint, service, credential, model artifact, or host package.
"""

let render() = file
