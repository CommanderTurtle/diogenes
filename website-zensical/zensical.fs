module DiogenesDocs.ZensicalToml

let file = """[project]
site_name = "diogenes"
site_url = "https://dio.shel.sh"
site_description = "bloated with materialism, nihilistic in theory."
repo_url = "https://github.com/CommanderTurtle/diogenes"
docs_dir = "docs"
copyright = "AGPL-3.0-or-later"
extra_css = [
    "assets/stylesheets/extra.css",
]
extra_javascript = [
    "assets/javascripts/mathjax.js",
    "https://unpkg.com/mathjax@3.2.2/es5/tex-mml-chtml.js",
]

[project.markdown_extensions.abbr]

[project.markdown_extensions.admonition]

[project.markdown_extensions.attr_list]

[project.markdown_extensions.def_list]

[project.markdown_extensions.footnotes]

[project.markdown_extensions.md_in_html]

[project.markdown_extensions.pymdownx.caret]

[project.markdown_extensions.pymdownx.details]

[project.markdown_extensions.pymdownx.snippets]

[project.markdown_extensions.pymdownx.inlinehilite]

[project.markdown_extensions.pymdownx.smartsymbols]

[project.markdown_extensions.pymdownx.mark]

[project.markdown_extensions.pymdownx.tilde]

[project.markdown_extensions.pymdownx.keys]

[project.markdown_extensions.pymdownx.highlight]
line_spans = "__span"
anchor_linenums = true
linenums_style = "pymdownx-inline"
pygments_lang_class = true
auto_title = true

[project.markdown_extensions.pymdownx.superfences]
custom_fences = [
    { name = "mermaid", class = "mermaid", format = "pymdownx.superfences.fence_code_format" },
]

[project.markdown_extensions.pymdownx.tabbed]
alternate_style = true
combine_header_slug = true

[project.markdown_extensions.pymdownx.emoji]
emoji_index = "zensical.extensions.emoji.twemoji"
emoji_generator = "zensical.extensions.emoji.to_svg"

[project.markdown_extensions.pymdownx.arithmatex]
generic = true

[project.markdown_extensions.pymdownx.magiclink]
normalize_issue_symbols = true
repo_url_shorthand = true
user = "CommanderTurtle"
repo = "diogenes"

[project.markdown_extensions.pymdownx.tasklist]
custom_checkbox = true

[project.markdown_extensions.pymdownx.betterem]
smart_enable = "all"

[project.markdown_extensions.zensical.extensions.glightbox]
auto_themed = true

[project.markdown_extensions.toc]
permalink = true

[project.extra]
generator = false
social = [
    { icon = "fontawesome/brands/github", link = "https://github.com/CommanderTurtle/diogenes", name = "Diogenes on GitHub" },
]

[project.theme]
variant = "modern"
logo = "assets/logos/Diogenes-navbar.svg"
favicon = "assets/logos/Diogenes-favicon.svg"
features = [
    "content.code.annotate",
    "content.code.copy",
    "content.code.select",
    "content.footnote.tooltips",
    "content.tabs.link",
    "content.tooltips",
    "navigation.footer",
    "navigation.indexes",
    "navigation.instant",
    "navigation.instant.prefetch",
    "navigation.instant.progress",
    "navigation.path",
    "navigation.sections",
    "navigation.top",
    "navigation.tracking",
    "search.highlight",
    "search.share",
    "search.suggest",
    "toc.follow",
]
custom_dir = "overrides"

[[project.theme.palette]]
media = "(prefers-color-scheme)"
primary = "custom"
accent = "custom"

[project.theme.palette.toggle]
icon = "lucide/sun-moon"
name = "Use light mode"

[[project.theme.palette]]
media = "(prefers-color-scheme: light)"
scheme = "default"
primary = "custom"
accent = "custom"

[project.theme.palette.toggle]
icon = "lucide/sun"
name = "Use dark mode"

[[project.theme.palette]]
media = "(prefers-color-scheme: dark)"
scheme = "slate"
primary = "custom"
accent = "custom"

[project.theme.palette.toggle]
icon = "lucide/moon-star"
name = "Use system preference"

[[project.nav]]
Home = "README.md"

[[project.nav]]

[[project.nav."Getting Started"]]
Overview = "getting-started/index.md"

[[project.nav."Getting Started"]]
Installation = "getting-started/installation.md"

[[project.nav."Getting Started"]]
Quickstart = "getting-started/quickstart.md"

[[project.nav."Getting Started"]]
"Your First Session" = "getting-started/first-session.md"

[[project.nav]]

[[project.nav.Configuration]]
Overview = "configuration/index.md"

[[project.nav.Configuration]]
"Settings & Environment" = "configuration/settings.md"

[[project.nav.Configuration]]
"Models & Providers" = "configuration/models.md"

[[project.nav.Configuration]]
"Interface, Themes & Shortcuts" = "configuration/interface.md"

[[project.nav.Configuration]]
"Instructions, Approvals & Security" = "configuration/security.md"

[[project.nav]]

[[project.nav.Workspace]]
Overview = "workspace/index.md"

[[project.nav.Workspace]]
"Chat & Sessions" = "workspace/chat-sessions.md"

[[project.nav.Workspace]]
"Tools & Agents" = "workspace/tools-agents.md"

[[project.nav.Workspace]]
"Memory, Skills & RAG" = "workspace/memory-rag.md"

[[project.nav.Workspace]]
"Documents & Editor" = "workspace/documents.md"

[[project.nav.Workspace]]
"Email, Notes, Tasks & Calendar" = "workspace/productivity.md"

[[project.nav.Workspace]]
"Gallery, Media & Voice" = "workspace/media.md"

[[project.nav]]

[[project.nav."Deep Research"]]
Overview = "research/index.md"

[[project.nav."Deep Research"]]
"Modes & Workflow" = "research/modes.md"

[[project.nav."Deep Research"]]
"Report Data & HTML" = "research/sources.md"

[[project.nav."Deep Research"]]
"arXiv Reports" = "research/arxiv.md"

[[project.nav."Deep Research"]]
"Narrative Studio" = "research/narrative.md"

[[project.nav."Deep Research"]]
"Recovery & Export" = "research/recovery.md"

[[project.nav]]

[[project.nav.Operations]]
Overview = "operations/index.md"

[[project.nav.Operations]]
"Services Control Plane" = "operations/services.md"

[[project.nav.Operations]]
"Venvs & Operator Shell" = "operations/venvs-shell.md"

[[project.nav.Operations]]
"Cookbook & Native Engines" = "operations/engines.md"

[[project.nav.Operations]]
"Runtime Topology" = "operations/runtime-topology.md"

[[project.nav.Operations]]
"Deployment, Backup & Restore" = "operations/deployment.md"

[[project.nav]]

[[project.nav.Extending]]
Overview = "extending/index.md"

[[project.nav.Extending]]
"Skills & Instructions" = "extending/skills.md"

[[project.nav.Extending]]
"MCP & Custom Tools" = "extending/mcp-tools.md"

[[project.nav.Extending]]
"API, CLI & Companion" = "extending/api-cli.md"

[[project.nav.Extending]]
"Integrations & Extension Points" = "extending/integrations.md"

[[project.nav]]

[[project.nav.Guides]]
"Steering & Workflow Recipes" = "guides/workflows.md"

[[project.nav.Guides]]
"Multi-Agent & Automation" = "guides/multi-agent.md"

[[project.nav.Guides]]
Troubleshooting = "guides/troubleshooting.md"

[[project.nav]]

[[project.nav.Architecture]]
Overview = "architecture/index.md"

[[project.nav.Architecture]]
"Backend & Request Pipeline" = "architecture/backend.md"

[[project.nav.Architecture]]
"Frontend SPA" = "architecture/frontend.md"

[[project.nav.Architecture]]
"Persistence, Security & Tests" = "architecture/data-security.md"

[[project.nav]]

[[project.nav.Reference]]
"CLI & Launchers" = "reference/cli.md"

[[project.nav.Reference]]
"Configuration Catalog" = "reference/configuration.md"

[[project.nav.Reference]]
"Data & Runtime Layout" = "reference/storage.md"

[[project.nav.Reference]]
"Feature Matrix" = "reference/feature-matrix.md"

[[project.nav.Reference]]
"Chat Stream Events" = "reference/glossary.md"

[[project.nav]]
Development = "about/contributing.md"
"""

let render() = file
