module ConvertedFiles.Extending.IntegrationsMd

let file = """# Integrations and webhooks

An integration names an HTTP base URL, authentication data, headers, and service metadata. The `api_call` agent tool resolves a configured entry and calls a relative service path.

## Integration routes

~~~ text
GET    /api/auth/integrations
GET    /api/auth/integrations/presets
POST   /api/auth/integrations
PUT    /api/auth/integrations/{id}
DELETE /api/auth/integrations/{id}
POST   /api/auth/integrations/{id}/test
~~~

`src/integrations.py` stores entries in the configured integrations JSON file. Secret fields are encrypted before write and masked in browser replies.

## Add a service

~~~ javascript
const integration = await fetch("/api/auth/integrations", {
  method: "POST",
  credentials: "same-origin",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    name: "build-status",
    base_url: "http://192.168.10.50:9100",
    auth_type: "bearer",
    api_key: "TOKEN_VALUE",
    headers: { "Accept": "application/json" },
    description: "Read build and queue state"
  })
}).then(async response => {
  if (!response.ok) throw new Error(await response.text());
  return response.json();
});
~~~

Call it from a model tool request:

~~~ json
{
  "name": "api_call",
  "arguments": {
    "integration": "build-status",
    "method": "GET",
    "path": "/api/jobs?state=failed"
  }
}
~~~

`_normalize_integration_base_url()` validates the stored base. `_join_integration_url()` joins a relative path without allowing it to replace the configured host. `INTEGRATION_API_BLOCK_PRIVATE_IPS=true` blocks private/LAN targets for this tool; the default permits administrator-configured LAN services.

## Add a preset

Presets are declared in `src/integrations.py:INTEGRATION_PRESETS`. A preset can supply service type, default port/path, auth style, and description. Do not include a real key in the preset map.

After adding one:

1. check `GET /api/auth/integrations/presets`;
2. create an entry from the new preset;
3. run the test route with a reachable service;
4. run the test route with bad credentials;
5. call one read path through `api_call`;
6. verify a disallowed method/path is rejected;
7. confirm API replies mask the key.

## Webhooks

Webhooks send Diogenes events to an HTTP receiver:

~~~ text
GET    /api/webhooks
POST   /api/webhooks
POST   /api/webhooks/{id}/test
PATCH  /api/webhooks/{id}
DELETE /api/webhooks/{id}
~~~

`src/webhook_manager.py` validates URLs and event names, signs payloads when a secret is configured, and dispatches completion events without blocking the chat response.

~~~ javascript
const webhook = new FormData();
webhook.set("name", "chat-audit");
webhook.set("url", "https://receiver.example.test/diogenes");
webhook.set("events", "chat.completed");
webhook.set("secret", "SIGNING_SECRET");

const response = await fetch("/api/webhooks", {
  method: "POST",
  credentials: "same-origin",
  body: webhook
});
if (!response.ok) throw new Error(await response.text());
~~~

`events` is a comma-delimited form field. Accepted delivery events are `session.created`, `chat.completed`, and `chat.message`; `webhook.test` is reserved for the test route. The webhook table is administrator-wide rather than user-scoped. Test delivery uses the saved URL and secret. A delivery failure is logged and does not reverse the event that triggered it.
"""

let render() = file
