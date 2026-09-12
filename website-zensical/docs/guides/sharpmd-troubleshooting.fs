module ConvertedFiles.Guides.TroubleshootingMd

let file = """# Troubleshooting

Start at the failing layer: application process, browser module, model endpoint, tool handler, or dependency service.

## Application process

~~~ bash
curl -i http://127.0.0.1:7000/api/health
curl -i http://127.0.0.1:7000/api/ready
curl -i http://127.0.0.1:7000/api/runtime
~~~

`/api/health` proves the process responds. `/api/ready` checks database access, the data directory, and storage metadata. For administrator diagnostics:

~~~ text
GET /api/diagnostics/services
GET /api/diagnostics/logs
GET /api/db/stats
GET /api/rag/stats
~~~

Application logs are written below `data/logs` unless the data root is changed. `LOG_LEVEL` defaults to `INFO`; invalid values also select `INFO`.

## Browser modules

The frontend ships raw ES modules. If a panel fails after an edit:

1. open browser developer tools;
2. check the first module import error;
3. open the imported URL directly;
4. check `static/index.html` and the parent module for the exact path;
5. unregister or refresh `static/sw.js` if an old module remains cached;
6. run `node --check static/js/changed-file.js`.

JavaScript, CSS, and HTML use revalidation. A syntax failure in one lazy panel can leave the rest of the SPA usable.

## Chat stream

Check these routes for a session that appears stuck:

~~~ text
GET /api/chat/stream_status/{session_id}
GET /api/chat/resume/{session_id}
GET /api/history/{session_id}
~~~

The browser parser buffers split SSE frames. Terminal errors, missing completion, round exhaustion, context trimming, and provider-route changes are stored or rendered separately. If the browser switched sessions, generation can continue in `src/agent_runs.py` and be resumed.

## Model endpoint

1. call the endpoint's `/v1/models` route;
2. inspect `/api/model-endpoints/{id}/probe`;
3. confirm the selected model appears in the user-visible catalog;
4. test a minimal `/v1/chat/completions` request at the provider;
5. compare the normalized chat URL from `src/endpoint_resolver.py`;
6. inspect provider error details in the stream.

A successful model-list probe does not test tools, reasoning, image input, or streaming.

## Tool call

Inspect the agent trace in this order:

1. model-emitted name and JSON arguments;
2. schema selection in `src/tool_index.py`;
3. disabled/role policy;
4. approval card and decision;
5. handler result and exit code;
6. matching tool-call ID in the next model request.

An OpenAI schema without a registered handler returns unknown tool. A handler without a schema can still be reached by a legacy fenced call but not selected through native function calling.

## Research

Use `/api/research/status/{id}`, then `result-peek`. Test `/api/search` separately. A report with findings but no final text points at synthesis; zero findings points at provider or extraction.

## Services and model servers

Use the status route, bounded log, port probe, and generated command before reinstalling packages. For host services, compare the configured port with `ss -ltnp`. For Cookbook, inspect task status plus tmux/PID data.

## Focused source checks

~~~ bash
uv run python -m py_compile app.py routes/chat_routes.py src/agent_loop.py
uv run pytest tests/test_target.py -q
node --check static/js/changed-file.js
docker compose config
~~~

Run the affected browser route after syntax and unit checks; those checks do not exercise module imports, SSE rendering, cookies, or endpoint connectivity.
"""

let render() = file
