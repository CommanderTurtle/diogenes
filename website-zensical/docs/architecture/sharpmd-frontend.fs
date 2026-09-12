module ConvertedFiles.Architecture.FrontendMd

let file = """# Frontend SPA

The browser application uses plain ES modules. There is no bundler or generated asset manifest. `static/index.html` defines the shared DOM; `static/app.js` initializes navigation and feature modules.

## Module structure

| Area | Entry point |
| --- | --- |
| chat send/stream | `static/js/chat.js` |
| transcript rendering | `static/js/chatRenderer.js` |
| sessions | `static/js/sessions.js` |
| uploads | `static/js/fileHandler.js` |
| settings | `static/js/settings.js`, `static/js/settings/*` |
| research | `static/js/research/panel.js`, `static/js/research/jobs.js` |
| compare | `static/js/compare/index.js` and sibling modules |
| documents | `static/js/document.js` |
| gallery editor | `static/js/galleryEditor.js`, `static/js/editor/*` |
| service panels | `static/js/ulysses/*` |

Feature panels load on first open. `static/js/panels.js` shares concurrent imports and allows another attempt after an import failure.

## State locations

- application data comes from API routes;
- per-user preferences come from `/api/prefs/*`;
- theme and some panel geometry use browser storage plus preference sync;
- active stream state and object URLs exist in module memory;
- editor drafts and chat messages are written server-side.

When adding browser storage, define migration and reset behavior. Do not use it as the permission check for server records.

## Streaming

`chat.js` reads the fetch response body and buffers bytes until complete SSE frames exist. It routes event types to transcript, tool trace, approval, research, model routing, metrics, and completion handlers.

When the user changes sessions during generation, DOM writes stop for that session while the server run can continue. `sessions.js` checks stream status when the session is reopened and attaches to the resume route.

Preserve user scroll position while a response is updating. Auto-follow should engage only when the viewport was already near the bottom; expanding reasoning or tool panes must not force the article to the final message.

## Shared UI patterns

`static/js/modalSnap.js` handles desktop edge docking. `static/js/toolWindowZOrder.js` handles stack order. Settings navigation uses the registry below `static/js/settings/`. New panels should reuse these helpers and the existing focus/escape patterns.

## Service worker

`static/sw.js` applies:

- navigation: stale-while-revalidate;
- JavaScript and CSS: network first;
- other static files: cache first with background refresh;
- API requests and non-GET requests: no service-worker cache.

Because filenames are stable, HTML, CSS, and JavaScript responses require revalidation. Update lazy-panel precache entries when adding a module needed during offline panel use.

## Add a panel module

1. Add its stable container to `static/index.html` or create it through the feature entry module.
2. Export one initialization function from a new ES module.
3. Load it through `panels.js` or the nearest domain registry.
4. Scope DOM queries to the panel where repeated IDs/classes are possible.
5. Remove event listeners and object URLs during close/reload.
6. Add keyboard and narrow-screen behavior.
7. Run `node --check` on every changed module.
8. Test first load, second open, failed import retry, browser refresh, and service-worker refresh.

## CSP

`core/middleware.py` creates the Content Security Policy. `app.py` injects a nonce into SPA and login HTML. A new inline script or remote module will not execute until represented in that policy. Prefer checked-in modules referenced by `src`.
"""

let render() = file
