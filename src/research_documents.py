"""Specialized, self-contained visual documents for Deep Research modes.

The research engine still writes portable Markdown.  This module changes only
the visual-report envelope for scholarly papers and long-form manuscripts.
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional


def _safe_json(value) -> str:
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def _source_list(sources: List[Dict]) -> str:
    items = []
    seen = set()
    for index, source in enumerate(sources or [], 1):
        url = str(source.get("url") or "").strip()
        if not url or url in seen or not url.startswith(("http://", "https://")):
            continue
        seen.add(url)
        title = str(source.get("title") or url).strip()
        items.append(
            '<li><span class="ref-number">[{0}]</span> '
            '<a href="{1}" target="_blank" rel="noopener noreferrer">{2}</a></li>'.format(
                len(items) + 1,
                html.escape(url, quote=True),
                html.escape(title),
            )
        )
    if not items:
        return ""
    return (
        '<section class="source-record" id="source-record">'
        '<h2>Source record</h2><p class="source-record-note">Links consulted during the research run.</p>'
        '<ol>' + "".join(items) + '</ol></section>'
    )


def _toc_html(headings: List[Dict[str, str]]) -> str:
    if not headings:
        return '<p class="toc-empty">Sections appear here as the manuscript develops.</p>'
    result = []
    for heading in headings:
        level = int(heading.get("level") or 2)
        cls = "toc-sub" if level >= 3 else "toc-main"
        result.append(
            '<a class="{0}" href="#{1}">{2}</a>'.format(
                cls,
                html.escape(str(heading.get("slug") or heading.get("id") or ""), quote=True),
                html.escape(str(heading.get("text") or "")),
            )
        )
    return "".join(result)


def _normalize_mermaid_blocks(rendered: str) -> str:
    """Turn fenced Mermaid code into nodes understood by vendored Mermaid."""
    pattern = re.compile(
        r'<(?:div class="code">)?\s*<pre><(?:span></span>)?<code class="(?:language-)?mermaid">(.*?)</code></pre>\s*(?:</div>)?',
        re.IGNORECASE | re.DOTALL,
    )
    return pattern.sub(lambda match: '<pre class="mermaid">' + match.group(1) + '</pre>', rendered)


def _protect_mermaid_blocks(markdown_text: str):
    blocks = []

    def replace(match):
        index = len(blocks)
        blocks.append(match.group(1).strip())
        return f"\n\nODYSSEUSMERMAIDBLOCK{index}TOKEN\n\n"

    protected = re.sub(
        r"```mermaid\s*\n([\s\S]*?)\n```",
        replace,
        markdown_text,
        flags=re.IGNORECASE,
    )
    return protected, blocks


def _restore_mermaid_blocks(rendered: str, blocks: List[str]) -> str:
    for index, source in enumerate(blocks):
        token = f"ODYSSEUSMERMAIDBLOCK{index}TOKEN"
        node = '<pre class="mermaid">' + html.escape(source) + '</pre>'
        rendered = rendered.replace(f"<p>{token}</p>", node).replace(token, node)
    return rendered


def generate_arxiv_report(
    *,
    question: str,
    report_markdown: str,
    sources: Optional[List[Dict]],
    stats: Optional[Dict],
    session_id: Optional[str],
    md_to_html: Callable[[str], str],
    extract_title: Callable,
    extract_headings: Callable,
    apply_heading_ids: Callable,
) -> str:
    """Render research Markdown as an arXiv-HTML-inspired paper."""
    sources = sources or []
    stats = stats or {}
    title, body_markdown = extract_title(report_markdown, question)
    title = str(title or question or "Untitled paper").strip()
    headings = extract_headings(body_markdown)
    protected_markdown, mermaid_blocks = _protect_mermaid_blocks(body_markdown)
    article_html = apply_heading_ids(md_to_html(protected_markdown), headings)
    article_html = _restore_mermaid_blocks(article_html, mermaid_blocks)
    article_html = _normalize_mermaid_blocks(article_html)
    source_record = _source_list(sources)
    toc = _toc_html(headings)
    generated = datetime.now(timezone.utc).strftime("%d %B %Y")
    session_label = html.escape(str(session_id or "draft"))
    stats_bits = []
    for key in ("Rounds", "URLs", "Findings", "Model"):
        if stats.get(key) not in (None, ""):
            stats_bits.append(f"<span><b>{html.escape(key)}</b> {html.escape(str(stats[key]))}</span>")
    stats_html = "".join(stats_bits)

    return f'''<!doctype html>
<html lang="en" data-theme="light">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{html.escape(title)}</title>
  <link rel="stylesheet" href="/static/lib/katex/katex.min.css">
  <style>
    :root {{ color-scheme:light; --paper:#fff; --ink:#1d1d1f; --muted:#62666d; --rule:#d7d9dc; --soft:#f4f5f6; --link:#0057a8; --bar:#171717; --accent:#b31b1b; }}
    html[data-theme="dark"] {{ color-scheme:dark; --paper:#17191c; --ink:#edf0f2; --muted:#aeb3bb; --rule:#3a3e44; --soft:#22252a; --link:#79b9f2; --bar:#090a0b; --accent:#ef6b6b; }}
    * {{ box-sizing:border-box; }}
    html {{ scroll-behavior:smooth; }}
    body {{ margin:0; background:var(--paper); color:var(--ink); font-family:Georgia,'Times New Roman',serif; line-height:1.58; }}
    .arxiv-bar {{ position:sticky; top:0; z-index:20; min-height:48px; display:flex; align-items:center; gap:18px; padding:7px 18px; color:#fff; background:var(--bar); font:13px/1.2 Arial,sans-serif; box-shadow:0 1px 0 rgba(255,255,255,.12); }}
    .arxiv-mark {{ font:700 25px/1 Georgia,serif; letter-spacing:-1px; white-space:nowrap; }}
    .arxiv-mark i {{ color:#e14b4b; font-style:normal; }}
    .bar-id {{ color:#b9bdc3; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
    .bar-actions {{ margin-left:auto; display:flex; align-items:center; gap:6px; }}
    button {{ font:inherit; }}
    .bar-actions button {{ border:1px solid #555; border-radius:3px; color:#fff; background:#25272a; padding:6px 9px; cursor:pointer; }}
    .bar-actions button:hover {{ background:#393c40; }}
    .layout {{ display:grid; grid-template-columns:minmax(190px,250px) minmax(0,900px) minmax(20px,1fr); gap:34px; align-items:start; max-width:1500px; margin:0 auto; padding:30px 26px 80px; }}
    .toc {{ position:sticky; top:74px; max-height:calc(100vh - 94px); overflow:auto; border-right:1px solid var(--rule); padding:0 20px 22px 0; font:12px/1.4 Arial,sans-serif; }}
    .toc-title {{ color:var(--muted); text-transform:uppercase; letter-spacing:.09em; font-weight:700; margin-bottom:10px; }}
    .toc a {{ display:block; padding:5px 7px; color:var(--muted); text-decoration:none; border-left:2px solid transparent; }}
    .toc a:hover,.toc a.active {{ color:var(--ink); border-left-color:var(--accent); background:var(--soft); }}
    .toc .toc-sub {{ padding-left:19px; font-size:11px; }}
    .toc-empty {{ color:var(--muted); font-style:italic; }}
    main {{ min-width:0; }}
    .paper-meta {{ font:12px/1.45 Arial,sans-serif; color:var(--muted); border-bottom:1px solid var(--rule); padding-bottom:14px; margin-bottom:30px; }}
    .paper-meta .primary {{ display:flex; flex-wrap:wrap; gap:8px 18px; margin-bottom:7px; }}
    .paper-meta .mode {{ color:var(--accent); font-weight:700; }}
    .paper-stats {{ display:flex; flex-wrap:wrap; gap:12px; }}
    .paper-title {{ font-size:clamp(29px,4.4vw,45px); line-height:1.12; text-align:center; letter-spacing:-.025em; margin:34px auto 18px; max-width:820px; }}
    .paper-byline {{ text-align:center; margin:0 auto 38px; color:var(--muted); font:14px/1.5 Arial,sans-serif; }}
    article {{ font-size:16px; }}
    article h1, article h2, article h3, article h4 {{ color:var(--ink); font-family:Arial,sans-serif; line-height:1.25; scroll-margin-top:72px; }}
    article h1 {{ font-size:27px; margin:42px 0 16px; }}
    article h2 {{ font-size:23px; margin:40px 0 13px; padding-bottom:6px; border-bottom:1px solid var(--rule); }}
    article h3 {{ font-size:18px; margin:27px 0 8px; }}
    article p {{ margin:0 0 1.05em; text-align:justify; hyphens:auto; }}
    article > p:first-of-type {{ font-size:17px; }}
    article a,.source-record a {{ color:var(--link); text-decoration:none; }}
    article a:hover,.source-record a:hover {{ text-decoration:underline; }}
    article blockquote {{ margin:20px 0; padding:4px 18px; border-left:3px solid var(--accent); color:var(--muted); }}
    article img {{ display:block; max-width:100%; max-height:72vh; margin:22px auto 8px; object-fit:contain; }}
    article table {{ width:100%; border-collapse:collapse; display:block; overflow:auto; margin:22px 0; font:13px/1.45 Arial,sans-serif; }}
    article th, article td {{ border:1px solid var(--rule); padding:7px 9px; vertical-align:top; }}
    article th {{ background:var(--soft); font-weight:700; }}
    article pre:not(.mermaid) {{ overflow:auto; padding:14px; border:1px solid var(--rule); border-radius:3px; background:var(--soft); font:12px/1.55 ui-monospace,SFMono-Regular,Consolas,monospace; }}
    article code {{ font-family:ui-monospace,SFMono-Regular,Consolas,monospace; font-size:.87em; }}
    article :not(pre)>code {{ padding:.12em .32em; border:1px solid var(--rule); border-radius:3px; background:var(--soft); }}
    .mermaid {{ margin:24px auto; text-align:center; overflow:auto; background:transparent; }}
    .katex-display {{ overflow-x:auto; overflow-y:hidden; padding:6px 0; }}
    .source-record {{ margin-top:48px; padding-top:12px; border-top:2px solid var(--ink); font:13px/1.55 Arial,sans-serif; }}
    .source-record h2 {{ font:700 22px/1.3 Arial,sans-serif; }}
    .source-record-note {{ color:var(--muted); }}
    .source-record ol {{ list-style:none; padding:0; }}
    .source-record li {{ margin:7px 0; padding-left:35px; position:relative; overflow-wrap:anywhere; }}
    .ref-number {{ position:absolute; left:0; color:var(--muted); }}
    .footer {{ margin-top:54px; padding-top:16px; border-top:1px solid var(--rule); color:var(--muted); font:11px/1.5 Arial,sans-serif; }}
    @media (max-width:900px) {{ .layout {{ grid-template-columns:1fr; padding:18px 18px 60px; }} .toc {{ position:relative; top:0; max-height:220px; border:1px solid var(--rule); border-radius:4px; padding:12px; }} .layout-spacer {{ display:none; }} }}
    @media (max-width:600px) {{ .arxiv-bar {{ gap:9px; padding:7px 10px; }} .bar-id {{ display:none; }} .bar-actions button span {{ display:none; }} .paper-title {{ margin-top:18px; }} article {{ font-size:15px; }} }}
    @media print {{ .arxiv-bar,.toc,.layout-spacer {{ display:none!important; }} .layout {{ display:block; max-width:none; padding:0; }} main {{ max-width:none; }} body {{ background:#fff; color:#000; }} a {{ color:#000!important; }} article h2 {{ break-after:avoid; }} pre,table,img,.mermaid {{ break-inside:avoid; }} }}
  </style>
</head>
<body>
  <header class="arxiv-bar">
    <div class="arxiv-mark"><i>ar</i>Xiv</div>
    <span class="bar-id">HTML manuscript · {session_label}</span>
    <div class="bar-actions">
      <button type="button" onclick="document.getElementById('abstract')?.scrollIntoView()" title="Back to abstract">↑ <span>Abstract</span></button>
      <button type="button" id="theme-button" onclick="toggleTheme()" title="Toggle color theme">◐ <span>Theme</span></button>
      <button type="button" onclick="copyMarkdown(this)" title="Copy source Markdown">⧉ <span>Markdown</span></button>
      <button type="button" onclick="window.print()" title="Print or save as PDF">↓ <span>PDF</span></button>
    </div>
  </header>
  <div class="layout">
    <nav class="toc" aria-label="Paper sections"><div class="toc-title">Contents</div>{toc}</nav>
    <main>
      <div class="paper-meta">
        <div class="primary"><span class="mode">arXiv-style research paper</span><span>{generated}</span></div>
        <div class="paper-stats">{stats_html}</div>
      </div>
      <h1 class="paper-title">{html.escape(title)}</h1>
      <p class="paper-byline">Generated from the supplied question, references, and cited research sources. No author or affiliation has been inferred.</p>
      <article id="paper">{article_html}{source_record}</article>
      <footer class="footer">Research draft · source links remain available for verification · {session_label}</footer>
    </main>
    <div class="layout-spacer" aria-hidden="true"></div>
  </div>
  <script src="/static/lib/katex/katex.min.js"></script>
  <script src="/static/lib/mermaid.min.js"></script>
  <script>
    const SOURCE_MARKDOWN = {_safe_json(report_markdown)};
    function toggleTheme() {{
      const root = document.documentElement;
      root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
      try {{ localStorage.setItem('odysseus-paper-theme', root.dataset.theme); }} catch (_) {{}}
    }}
    async function copyMarkdown(button) {{
      try {{ await navigator.clipboard.writeText(SOURCE_MARKDOWN); const old=button.innerHTML; button.textContent='Copied'; setTimeout(()=>button.innerHTML=old,1200); }}
      catch (_) {{ const area=document.createElement('textarea'); area.value=SOURCE_MARKDOWN; document.body.appendChild(area); area.select(); document.execCommand('copy'); area.remove(); }}
    }}
    function renderMath(root) {{
      if (!window.katex) return;
      const skip = new Set(['CODE','PRE','SCRIPT','STYLE','TEXTAREA']);
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      const nodes=[]; while(walker.nextNode()) if(!skip.has(walker.currentNode.parentElement?.tagName)) nodes.push(walker.currentNode);
      const pattern = /(\\$\\$[\\s\\S]+?\\$\\$|(?<!\\\\)\\$(?!\\s)(?:\\\\.|[^$\\n])+?(?<!\\s)\\$)/g;
      for (const node of nodes) {{
        const text=node.nodeValue||''; if(!pattern.test(text)) {{ pattern.lastIndex=0; continue; }} pattern.lastIndex=0;
        const frag=document.createDocumentFragment(); let at=0;
        for (const match of text.matchAll(pattern)) {{
          frag.append(document.createTextNode(text.slice(at,match.index)));
          const display=match[0].startsWith('$$'); const expression=match[0].slice(display?2:1,display?-2:-1);
          const span=document.createElement(display?'div':'span');
          try {{ window.katex.render(expression,span,{{displayMode:display,throwOnError:false,strict:'ignore',trust:false}}); }} catch (_) {{ span.textContent=match[0]; }}
          frag.append(span); at=match.index+match[0].length;
        }}
        frag.append(document.createTextNode(text.slice(at))); node.replaceWith(frag);
      }}
    }}
    async function renderDiagrams() {{
      if (!window.mermaid) return;
      const theme=document.documentElement.dataset.theme==='dark'?'dark':'neutral';
      try {{ window.mermaid.initialize({{startOnLoad:false,securityLevel:'strict',theme}}); await window.mermaid.run({{nodes:document.querySelectorAll('.mermaid')}}); }}
      catch (error) {{ document.querySelectorAll('.mermaid').forEach(node => node.dataset.renderError=String(error)); console.warn('Mermaid render failed',error); }}
    }}
    function trackToc() {{
      const links=[...document.querySelectorAll('.toc a')]; const targets=links.map(a=>document.getElementById(a.hash.slice(1))).filter(Boolean);
      const update=()=>{{ let active=null; for(const target of targets) if(target.getBoundingClientRect().top<130) active=target.id; links.forEach(a=>a.classList.toggle('active',a.hash==='#'+active)); }};
      addEventListener('scroll',update,{{passive:true}}); update();
    }}
    try {{ const saved=localStorage.getItem('odysseus-paper-theme'); document.documentElement.dataset.theme=saved||'light'; }} catch (_) {{}}
    renderMath(document.getElementById('paper')); renderDiagrams(); trackToc();
  </script>
</body>
</html>'''


def generate_novel_report(
    *,
    question: str,
    report_markdown: str,
    sources: Optional[List[Dict]],
    stats: Optional[Dict],
    story_kind: str,
    session_id: Optional[str],
    md_to_html: Callable[[str], str],
    extract_title: Callable,
    extract_headings: Callable,
    apply_heading_ids: Callable,
) -> str:
    """Render a long-form fiction or narrative-nonfiction manuscript."""
    sources = sources or []
    stats = stats or {}
    kind = "nonfiction" if story_kind == "nonfiction" else "fiction"
    kind_label = "Narrative nonfiction" if kind == "nonfiction" else "Fiction"
    title, body_markdown = extract_title(report_markdown, question)
    title = str(title or question or "Untitled manuscript").strip()
    headings = extract_headings(body_markdown)
    manuscript_html = apply_heading_ids(md_to_html(body_markdown), headings)
    toc = _toc_html(headings)
    source_record = _source_list(sources) if kind == "nonfiction" else ""
    word_count = len(re.findall(r"\b[\w’'-]+\b", body_markdown))
    read_minutes = max(1, round(word_count / 230))
    read_label = f"{read_minutes} minute" + ("" if read_minutes == 1 else "s")
    session_label = html.escape(str(session_id or "draft"))

    return f'''<!doctype html>
<html lang="en" data-theme="night">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{ color-scheme:dark; --page:#151316; --sheet:#1c191d; --ink:#eee8df; --muted:#a9a0a6; --rule:#373139; --accent:#d6a6c8; --soft:#242026; --measure:720px; --reader-size:18px; }}
    html[data-theme="paper"] {{ color-scheme:light; --page:#e9e4db; --sheet:#faf7f0; --ink:#282421; --muted:#716963; --rule:#d5cec2; --accent:#7e395f; --soft:#f0ebe2; }}
    html[data-theme="ink"] {{ color-scheme:light; --page:#edf0f2; --sheet:#fff; --ink:#17191c; --muted:#666d74; --rule:#dce0e4; --accent:#365f76; --soft:#f3f5f6; }}
    * {{ box-sizing:border-box; }}
    html {{ scroll-behavior:smooth; }}
    body {{ margin:0; background:var(--page); color:var(--ink); font-family:Georgia,'Times New Roman',serif; }}
    .progress {{ position:fixed; inset:0 auto auto 0; z-index:50; width:0; height:3px; background:var(--accent); transition:width .12s linear; }}
    .reader-bar {{ position:sticky; top:0; z-index:30; display:flex; align-items:center; gap:12px; min-height:49px; padding:7px 14px; border-bottom:1px solid var(--rule); background:color-mix(in srgb,var(--sheet) 94%,transparent); backdrop-filter:blur(14px); font:12px/1.2 Arial,sans-serif; }}
    .reader-title {{ min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-weight:700; }}
    .reader-kind {{ flex:none; color:var(--accent); text-transform:uppercase; letter-spacing:.1em; font-size:9px; }}
    .reader-actions {{ margin-left:auto; display:flex; gap:5px; }}
    button {{ font:inherit; }}
    .reader-actions button,.chapters-toggle {{ color:var(--ink); background:var(--soft); border:1px solid var(--rule); border-radius:5px; padding:6px 8px; cursor:pointer; }}
    .reader-actions button:hover,.chapters-toggle:hover {{ border-color:var(--accent); }}
    .book-layout {{ display:grid; grid-template-columns:minmax(190px,240px) minmax(0,1fr); gap:34px; max-width:1240px; min-height:calc(100vh - 49px); margin:auto; }}
    .chapters {{ position:sticky; top:76px; align-self:start; max-height:calc(100vh - 98px); overflow:auto; margin:28px 0 28px 24px; padding:8px 19px 18px 0; border-right:1px solid var(--rule); font:12px/1.45 Arial,sans-serif; }}
    .chapters-label {{ margin:4px 7px 11px; color:var(--muted); text-transform:uppercase; letter-spacing:.11em; font-weight:700; font-size:10px; }}
    .chapters a {{ display:block; padding:6px 8px; color:var(--muted); text-decoration:none; border-left:2px solid transparent; }}
    .chapters a.toc-sub {{ padding-left:19px; font-size:11px; }}
    .chapters a:hover,.chapters a.active {{ color:var(--ink); border-left-color:var(--accent); background:var(--soft); }}
    .book {{ min-width:0; background:var(--sheet); box-shadow:0 8px 44px rgba(0,0,0,.16); padding:clamp(28px,6vw,78px) clamp(22px,7vw,92px) 80px; }}
    .cover {{ min-height:min(62vh,620px); display:flex; flex-direction:column; justify-content:center; text-align:center; border-bottom:1px solid var(--rule); margin-bottom:56px; }}
    .eyebrow {{ color:var(--accent); font:700 10px/1.3 Arial,sans-serif; letter-spacing:.18em; text-transform:uppercase; }}
    .cover h1 {{ max-width:820px; margin:25px auto 20px; font-size:clamp(38px,6vw,72px); line-height:1.05; letter-spacing:-.035em; font-weight:500; }}
    .cover-meta {{ color:var(--muted); font:12px/1.7 Arial,sans-serif; }}
    .ornament {{ margin:34px auto 0; color:var(--accent); font-size:18px; letter-spacing:.45em; }}
    article {{ max-width:var(--measure); margin:0 auto; font-size:var(--reader-size); line-height:1.82; }}
    article h1,article h2,article h3,article h4 {{ scroll-margin-top:70px; font-family:Georgia,'Times New Roman',serif; line-height:1.18; text-align:center; }}
    article h1,article h2 {{ margin:72px auto 31px; font-size:clamp(29px,4vw,40px); font-weight:500; }}
    article h2::after {{ content:'◆'; display:block; margin:16px auto 0; color:var(--accent); font-size:8px; }}
    article h3 {{ margin:48px auto 22px; font-size:23px; font-style:italic; font-weight:500; }}
    article p {{ margin:0 0 .4em; }}
    article p + p {{ text-indent:1.65em; }}
    article h1 + p,article h2 + p,article h3 + p,article blockquote + p,article ul + p,article ol + p {{ text-indent:0; }}
    article h2 + p::first-letter {{ float:left; margin:.08em .09em 0 0; color:var(--accent); font-size:3.6em; line-height:.75; }}
    article blockquote {{ margin:30px 4%; padding:8px 24px; color:var(--muted); border-left:2px solid var(--accent); font-style:italic; }}
    article hr {{ width:72px; margin:42px auto; border:0; text-align:center; }}
    article hr::after {{ content:'⁂'; color:var(--accent); letter-spacing:.35em; }}
    article a,.source-record a {{ color:var(--accent); text-decoration:none; }}
    article a:hover,.source-record a:hover {{ text-decoration:underline; }}
    article img {{ display:block; max-width:min(100%,900px); max-height:78vh; margin:38px auto 10px; object-fit:contain; border-radius:4px; }}
    article pre {{ overflow:auto; padding:14px; border:1px solid var(--rule); border-radius:5px; background:var(--soft); font:12px/1.55 ui-monospace,SFMono-Regular,Consolas,monospace; }}
    article code {{ font-family:ui-monospace,SFMono-Regular,Consolas,monospace; font-size:.84em; }}
    article table {{ width:100%; border-collapse:collapse; display:block; overflow:auto; margin:25px 0; font:13px/1.45 Arial,sans-serif; }}
    article th,article td {{ border:1px solid var(--rule); padding:7px 9px; }}
    .source-record {{ max-width:var(--measure); margin:70px auto 0; padding-top:24px; border-top:1px solid var(--rule); font:13px/1.55 Arial,sans-serif; }}
    .source-record h2 {{ text-align:left; margin:0 0 8px; font:700 22px/1.3 Arial,sans-serif; }}
    .source-record-note,.source-record .ref-number {{ color:var(--muted); }}
    .source-record ol {{ list-style:none; padding:0; }} .source-record li {{ position:relative; margin:7px 0; padding-left:35px; overflow-wrap:anywhere; }} .source-record .ref-number {{ position:absolute; left:0; }}
    .colophon {{ max-width:var(--measure); margin:65px auto 0; padding-top:18px; border-top:1px solid var(--rule); color:var(--muted); text-align:center; font:10px/1.6 Arial,sans-serif; letter-spacing:.05em; }}
    .chapters-toggle {{ display:none; }}
    @media(max-width:800px) {{ .book-layout {{ display:block; }} .chapters-toggle {{ display:inline-block; }} .chapters {{ display:none; position:fixed; z-index:40; inset:50px 10px auto; max-height:60vh; margin:0; padding:13px; background:var(--sheet); border:1px solid var(--rule); box-shadow:0 12px 35px rgba(0,0,0,.28); }} .chapters.open {{ display:block; }} .book {{ box-shadow:none; }} .reader-kind {{ display:none; }} }}
    @media(max-width:520px) {{ .reader-actions button span {{ display:none; }} .book {{ padding-left:20px; padding-right:20px; }} article {{ line-height:1.72; }} .cover {{ min-height:52vh; }} }}
    @media print {{ .reader-bar,.chapters,.progress {{ display:none!important; }} .book-layout {{ display:block; }} .book {{ padding:0; box-shadow:none; }} .cover {{ min-height:90vh; break-after:page; }} body,.book {{ background:#fff; color:#000; }} article h2 {{ break-before:page; }} }}
  </style>
</head>
<body>
  <div class="progress" id="reading-progress"></div>
  <header class="reader-bar">
    <button class="chapters-toggle" type="button" onclick="document.querySelector('.chapters').classList.toggle('open')">☰</button>
    <span class="reader-title">{html.escape(title)}</span>
    <span class="reader-kind">{kind_label}</span>
    <div class="reader-actions">
      <button type="button" onclick="changeSize(-1)" title="Smaller text">A−</button>
      <button type="button" onclick="changeSize(1)" title="Larger text">A+</button>
      <button type="button" onclick="cycleTheme()" title="Change reading theme">◐ <span>Theme</span></button>
      <button type="button" onclick="copyMarkdown(this)" title="Copy source Markdown">⧉ <span>Markdown</span></button>
      <button type="button" onclick="window.print()" title="Print or save as PDF">↓ <span>PDF</span></button>
    </div>
  </header>
  <div class="book-layout">
    <nav class="chapters" aria-label="Manuscript chapters"><div class="chapters-label">Chapters</div>{toc}</nav>
    <main class="book">
      <section class="cover">
        <div class="eyebrow">{kind_label} manuscript</div>
        <h1>{html.escape(title)}</h1>
        <div class="cover-meta">{word_count:,} words · about {read_label}</div>
        <div class="ornament">◆ ◆ ◆</div>
      </section>
      <article id="manuscript">{manuscript_html}</article>
      {source_record}
      <footer class="colophon">{kind_label} draft · {session_label}</footer>
    </main>
  </div>
  <script>
    const SOURCE_MARKDOWN={_safe_json(report_markdown)};
    const THEMES=['night','paper','ink'];
    function cycleTheme() {{ const root=document.documentElement; const at=THEMES.indexOf(root.dataset.theme); root.dataset.theme=THEMES[(at+1)%THEMES.length]; try{{localStorage.setItem('odysseus-reader-theme',root.dataset.theme)}}catch(_){{}} }}
    function changeSize(step) {{ const root=document.documentElement; const now=parseFloat(getComputedStyle(root).getPropertyValue('--reader-size'))||18; root.style.setProperty('--reader-size',Math.max(14,Math.min(26,now+step))+'px'); }}
    async function copyMarkdown(button) {{ try{{await navigator.clipboard.writeText(SOURCE_MARKDOWN);const old=button.innerHTML;button.textContent='Copied';setTimeout(()=>button.innerHTML=old,1200)}}catch(_){{const area=document.createElement('textarea');area.value=SOURCE_MARKDOWN;document.body.appendChild(area);area.select();document.execCommand('copy');area.remove()}} }}
    function updateReadingState() {{ const max=document.documentElement.scrollHeight-innerHeight; document.getElementById('reading-progress').style.width=(max>0?scrollY/max*100:0)+'%'; const links=[...document.querySelectorAll('.chapters a')]; let active=''; for(const link of links){{const node=document.getElementById(link.hash.slice(1));if(node&&node.getBoundingClientRect().top<130)active=node.id}} links.forEach(link=>link.classList.toggle('active',link.hash==='#'+active)); }}
    addEventListener('scroll',updateReadingState,{{passive:true}}); document.querySelectorAll('.chapters a').forEach(link=>link.addEventListener('click',()=>document.querySelector('.chapters').classList.remove('open')));
    try{{document.documentElement.dataset.theme=localStorage.getItem('odysseus-reader-theme')||'night'}}catch(_){{}} updateReadingState();
  </script>
</body>
</html>'''
