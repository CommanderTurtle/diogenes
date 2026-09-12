module ConvertedFiles.Workspace.ProductivityMd

let file = """# Notes, tasks, calendar, and email

Personal-data modules use separate stores and routes. Agent tools call the same domain services used by the browser panels.

## Notes

`routes/note/note_routes.py` manages note records, folders, attachments, search, and conversion into tasks. The browser route is `/notes`; `static/js/notes.js` handles the panel.

Use the note API for durable free-form text. Use a document when revisions, structured editing, or PDF export matter.

## Tasks

`routes/task/task_routes.py` connects task CRUD with `src/task_scheduler.py`. Scheduled execution can run in the application process when `ODYSSEUS_INPROCESS_TASKS` enables the worker.

Task records include schedule, timezone, enabled state, action data, and run status. The browser surface is `/tasks`; assistant task routes under `/api/assistant` expose session, settings, run, and run-status operations.

The task launcher checks a stored action policy at execution time. Creating a visible task does not grant process or network permissions beyond that policy.

## Calendar

Calendar routes are mounted below `/api/calendar`:

~~~ text
GET    /api/calendar/calendars
POST   /api/calendar/calendars
PUT    /api/calendar/calendars/{id}
DELETE /api/calendar/calendars/{id}
GET    /api/calendar/events
POST   /api/calendar/events
PUT    /api/calendar/events/{uid}
DELETE /api/calendar/events/{uid}
POST   /api/calendar/quick-parse
POST   /api/calendar/import
GET    /api/calendar/export/{id}
POST   /api/calendar/sync
~~~

Account configuration uses `/api/calendar/config/accounts`. The test route validates the configured CalDAV connection. Imported ICS data and remote synchronization pass through the same normalization helpers used by route writes.

~~~ javascript
const event = await fetch("/api/calendar/events", {
  method: "POST",
  credentials: "same-origin",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    summary: "Review parser patch",
    dtstart: "2026-09-09T14:00:00-04:00",
    dtend: "2026-09-09T14:30:00-04:00",
    calendar_href: "CALENDAR_ID"
  })
}).then(async response => {
  if (!response.ok) throw new Error(await response.text());
  return response.json();
});
~~~

## Email and contacts

`routes/email_routes.py` implements account setup, listing, reading, search, attachments, folders, compose uploads, drafts, scheduled sends, pending approval, send, summarization, translation, and reply assistance.

Critical send routes are:

~~~ text
POST /api/email/draft
POST /api/email/schedule
GET  /api/email/pending
POST /api/email/pending/{id}/approve
POST /api/email/send
~~~

`routes/contacts/contacts_routes.py` provides list, search, add, update, import, export, configuration, and clear operations below `/api/contacts`.

## Data checks

- Calendar timestamps should include an offset or a configured IANA timezone.
- Email attachment indexes are validated against the selected message.
- Send and destructive routes perform route-side permission checks.
- Pollers can run in process when `ODYSSEUS_INPROCESS_POLLERS` is enabled; inspect application logs when inbox state stops advancing.
"""

let render() = file
