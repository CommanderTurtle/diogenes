module ConvertedFiles.Configuration.InterfaceMd

let file = """# Interface, themes, and shortcuts

The browser is an unbundled ES-module application. `static/index.html` defines the shell; `static/app.js` coordinates routes and panels; feature code is under `static/js/`.

## Keybindings

Default combinations come from `src/settings.py`:

| Action | Default |
| --- | --- |
| search | `Ctrl+K` |
| toggle sidebar | `Ctrl+B` |
| new session | `Ctrl+Alt+N` |
| mark session important | `Ctrl+Alt+S` |
| delete session | `Ctrl+Alt+D` |
| administrator panel | `Ctrl+Shift+U` |
| cancel | `Escape` |

`static/js/keyboard-shortcuts.js` rejects empty and non-string saved combinations before parsing. Change bindings in Settings; they are written through the global settings API.

Desktop Enter submits a chat message. On narrow/mobile layouts, Enter inserts a newline. ArrowUp recalls the prior prompt only when the composer is empty and its caret is at the top.

## Theme state

`static/js/theme.js` applies CSS variables, selected palette, text scale, accessibility font, and custom font. The selected theme is read from browser storage first and synchronized through `/api/prefs/*`.

User font files are discovered by `GET /api/fonts/custom` from `static/fonts/custom`. A filename is converted into a font-family choice by `routes/font_routes.py`.

## Panel registration

Settings panel metadata is defined in `static/js/settings/registry.js`. DOM sections remain in the Settings markup. Adding a panel requires both:

~~~ javascript
// static/js/settings/registry.js
export const groups = [
  {
    id: "models",
    label: "Models",
    panels: [{ id: "model-endpoints", label: "Endpoints", admin: true }]
  }
];
~~~

`navigation.js` activates entries, `search.js` indexes the registry, `dom.js` supplies helpers, and `sidebar.js` persists width/collapse state. Administrator entries are removed from the finder for other users.

## Modal behavior

`static/js/modalSnap.js` supplies desktop edge docking. `static/js/toolWindowZOrder.js` assigns window stacking. Feature panels use the shared modal/window patterns rather than separate drag implementations.

## Static delivery

JavaScript, CSS, and HTML responses use revalidation because file names are not content-hashed. `static/sw.js` applies:

- navigation: stale-while-revalidate;
- JavaScript and CSS: network first;
- remaining static assets: cache first with background refresh;
- API and non-GET requests: no service-worker cache.

When a module change appears stale, check the exact URL in `static/index.html`, its import path, and any matching entry in `static/sw.js`.
"""

let render() = file
