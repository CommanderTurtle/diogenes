module ConvertedFiles.Extending.SkillsMd

let file = """# Skills and instructions

A skill is a Markdown instruction package stored below `data/skills/{category}/{name}/SKILL.md`. `services/memory/skills.py` handles disk storage; `services/memory/skill_format.py` parses and emits frontmatter.

## File format

~~~ markdown
---
name: parser-review
description: Review parser changes and require focused regression tests.
category: coding
platforms: [linux, windows]
requires_toolsets: [files]
status: published
version: 1.0.0
confidence: 0.9
---

# Parser review

1. Read the parser and its nearest tests.
2. Reproduce the failing input.
3. Change the smallest responsible unit.
4. Run the focused test before the broader suite.
~~~

Quoted scalars use JSON-style escapes. Invalid escapes are kept as text rather than doubled on every save. Usage and audit state is written to `_usage.json` beside the skill.

## Routes

~~~ text
GET    /api/skills
GET    /api/skills/index
GET    /api/skills/slash-catalog
GET    /api/skills/{id}
GET    /api/skills/{id}/markdown
POST   /api/skills/add
PUT    /api/skills/{id}
DELETE /api/skills/{id}
POST   /api/skills/search
POST   /api/skills/{id}/invoke
POST   /api/skills/{id}/test
GET    /api/skills/{id}/test-status
POST   /api/skills/audit-all
GET    /api/skills/audit-all/status
POST   /api/skills/audit-all/cancel
~~~

Built-in instruction entries have separate routes below `/api/skills/builtin` and require administrator access for changes.

## Add through the API

~~~ javascript
const response = await fetch("/api/skills/add", {
  method: "POST",
  credentials: "same-origin",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    name: "parser-review",
    description: "Review parser changes with focused tests.",
    category: "coding",
    platforms: ["linux", "windows"],
    requires_toolsets: ["files"],
    when_to_use: "A parser change needs a focused regression test.",
    procedure: [
      "Read the parser and its nearest tests.",
      "Reproduce the failing input.",
      "Change the smallest responsible unit.",
      "Run the focused test before the broader suite."
    ],
    pitfalls: ["Do not replace the parser to fix one token class."],
    verification: ["The focused regression and parser suite pass."],
    status: "published",
    confidence: 0.9
  })
});
if (!response.ok) throw new Error(await response.text());
~~~

`SkillAddRequest` in `routes/skills_routes.py` defines the accepted body. The browser payload and import payload are not identical.

## Indexing and selection

`SkillsManager.index_for()` returns published entries filtered by user, platform, and active toolsets. Chat retrieves matches, applies a confidence threshold and per-user maximum, increments usage, then inserts selected skill text as user-editable context.

The model sees a compact index first. Full skill text is loaded only for selected entries. This keeps large skill libraries out of unrelated prompts.

## Import

`POST /api/skills/import-from-url` accepts supported public repository/file URLs. `services/memory/skill_importer.py` disables automatic redirects, permits at most five checked redirects, validates every host/address, pins the connection to the validated address, and applies file/count/byte limits.

## Tests and audits

Skill tests use the configured utility model. An approval pause uses the same sealed-action mechanism as agent turns. Full-library audit jobs can be polled and cancelled.

If a test cannot find the skill, check the user field, publication state, platform list, required toolsets, and generated index before changing model prompts.
"""

let render() = file
