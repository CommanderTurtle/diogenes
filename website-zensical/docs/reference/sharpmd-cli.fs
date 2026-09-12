module DiogenesDocs.Reference.CliMd

let file = """# Commands

Diogenes has two command surfaces: executable files under `scripts/` and slash commands parsed by `static/js/slashCommands.js`.

## Start commands

=== "Linux or WSL"

    ~~~ bash
    ./uvsetup.sh
    ./startwithuv.sh
    ~~~

=== "Docker Compose"

    ~~~ bash
    cp .env.example .env
    docker compose up -d --build
    docker compose ps
    docker compose logs --tail=120 odysseus
    ~~~

=== "Windows"

    ~~~ powershell
    powershell -ExecutionPolicy Bypass -File .\launch-windows.ps1
    ~~~

=== "macOS"

    ~~~ bash
    ./start-macos.sh
    ~~~

The Unix launcher binds port `7000`. `launch-windows.ps1` accepts `-BindHost` and `-Port`. `start-macos.sh` uses port `7860` unless its environment changes the port.

## Shell dispatcher

`scripts/odysseus` discovers executable siblings named `odysseus-*` and forwards every remaining argument.

~~~ bash
source .venv/bin/activate
./scripts/odysseus
./scripts/odysseus help research
./scripts/odysseus research list --status complete --pretty
./scripts/odysseus --version
~~~

The dispatcher tries `venv/bin/python`; otherwise it uses the interpreter that started the dispatcher. Activate `.venv` before invoking it in a source checkout.

| Command | Main operations |
| --- | --- |
| `backup` | `snapshot`, `list`, `verify`, `restore` |
| `calendar` | list/show events, list calendars, create, delete |
| `contacts` | list, search, add, show masked CardDAV configuration |
| `cookbook` | inspect hardware, artifacts, jobs, and serving state |
| `docs` | list, show, versions, export, search, delete |
| `gallery` | list, show, albums, search, delete |
| `logs` | list, tail, read, clean |
| `mail` | accounts, folders, list, read, send, scheduled/summary polling |
| `mcp` | list, show, add, enable, disable, delete |
| `memory` | list, search, show, add, delete, categories |
| `notes` | list, show, search, create, delete |
| `personal` | list, directories, add/remove directory, reload, exclude |
| `preset` | list, get, set, delete |
| `research` | list, show, report, search, delete |
| `sessions` | list, show, archive, unarchive, delete |
| `signature` | list, show, export PNG, delete |
| `skills` | list, show, categories, export, delete |
| `tasks` | list, show, pause, resume, runs |
| `theme` | list presets/users, get, set, export |
| `webhook` | list, show, rotate, revoke, print URL |

Every executable supports `--help`. Commands that return records accept `--pretty` where implemented.

### Backup sequence

~~~ bash
./scripts/odysseus backup snapshot --include-research --include-attachments
./scripts/odysseus backup list --pretty
./scripts/odysseus backup verify backups/odysseus-backup-20260908-120000.tar.gz
./scripts/odysseus backup restore backups/odysseus-backup-20260908-120000.tar.gz --yes
~~~

`restore` validates archive paths and file types, then moves the current data directory to a timestamped sibling before extraction.

## Browser slash commands

Enter these in the chat composer. `/help` prints the discovered command set. `!` can replace the first `/` because `_isCmd()` accepts both prefixes.

| Command | Forms |
| --- | --- |
| `/chats` | `new`, `delete`, `archive`, `rename`, `favorite`, `unfavorite`, `fork`, `truncate`, `switch`, `sort`, `info`, `clear`, `export` |
| `/toggle` | `web`, `bash`, `research`, `doc`, `sidebar` |
| `/workspace` | `set PATH`, `clear`, `pick` |
| `/memory` | `list`, `add TEXT`, `delete ID`, `search QUERY` |
| `/skills` | `list`, `search QUERY`, `view NAME`, `use NAME REQUEST` |
| `/reload-skills` | refresh the slash-skill catalog |
| `/todo` | add an item or list items |
| `/event` | create an event from a short date/time phrase |
| `/setup` | add a provider or local model endpoint |
| `/theme` | set a theme by name |
| `/css` | select `none`, `dots`, `synapse`, `rain`, `constellations`, `perlin-flow`, `petals`, `sparkles`, or `embers` |
| `/settings` | open a settings panel |
| `/cookbook`, `/email`, `/notes`, `/tasks` | open the named panel |
| `/brain`, `/library`, `/gallery` | open the named panel |
| `/research`, `/compare` | open the named panel |
| `/mcp` | display MCP server status |
| `/model`, `/models` | display the selected model or model list |
| `/usage` | display token and cost data for the current chat |
| `/compact` | compact older messages |
| `/note TEXT` | create a note |

Hidden utility commands remain callable: `/search`, `/find`, `/stats`, `/sh`, `/shortcuts`, `/ping`, and `/probe`. Guided tours use `/demo` and `/tour-*` commands.

### Setup examples

~~~ text
/setup local http://127.0.0.1:8000/v1
/setup openai sk-proj-...
/setup nvidia nvapi-...
/setup copilot
/setup chatgpt-subscription
~~~

`/setup local` stores an endpoint without an API key. Provider variants map a credential prefix or provider name to a known base URL before the endpoint is saved.

### Parser behavior

1. `handleSlashCommand()` resolves a direct command or alias.
2. Group commands resolve their first argument as a subcommand.
3. A published skill name can be invoked as `/<skill-name> request`.
4. A one- or two-character spelling error produces suggestions.
5. An unrecognized slash string with no close match returns `false`, so chat submission may send it to the model.

Use `/<command> --help` for a command group or `/<command> <subcommand> --help` for one operation. Slash replies are marked `source: "slash"`; they render in the transcript but are removed from model context.
"""

let render() = file
