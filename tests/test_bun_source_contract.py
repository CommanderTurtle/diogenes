from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_javascript_syntax_ci_uses_pinned_bun() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    assert "JS syntax (Bun parser)" in workflow
    assert "bun-version: \"1.3.14\"" in workflow
    assert "bun run js:check" in workflow
    assert "setup-node" not in workflow
    assert "node --check" not in workflow

    checker = (ROOT / "scripts" / "check-js-syntax.mjs").read_text(
        encoding="utf-8"
    )
    assert 'new Bun.Transpiler({ loader: "js" })' in checker
    assert 'new Bun.Glob("static/js/**/*.js")' in checker


def test_theme_cli_uses_bun_with_parser_fallback() -> None:
    script = (ROOT / "scripts" / "odysseus-theme").read_text(encoding="utf-8")

    assert 'shutil.which("bun")' in script
    assert '[bun, "--eval", script]' in script
    assert 'shutil.which("node")' not in script
    assert '["node",' not in script
