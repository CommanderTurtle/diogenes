from __future__ import annotations

from dataclasses import replace
import subprocess

import src.ulysses_colibri_build as build
from src.ulysses_colibri import default_colibri_catalog


def test_guarded_compatibility_edit_is_reverted(monkeypatch, tmp_path) -> None:
    original_provider = next(
        provider
        for provider in default_colibri_catalog()
        if provider.provider_id == "colibri.hy3"
    )
    source_root = tmp_path / "source"
    build_cwd = source_root / "c"
    build_cwd.mkdir(parents=True)
    target = source_root / original_provider.build_compatibility["path"]
    target.write_text(
        original_provider.build_compatibility["before"],
        encoding="utf-8",
    )
    provider = replace(
        original_provider,
        source_root=source_root,
        build_cwd=build_cwd,
        engine_path=build_cwd / "hy3",
        cli_path=build_cwd / "coli",
        setup_path=build_cwd / "setup.sh",
    )
    monkeypatch.setattr(build, "default_colibri_catalog", lambda: (provider,))

    calls = []

    def run(argv, **kwargs):
        calls.append(list(argv))
        if argv[:4] == ["git", "-C", str(source_root), "rev-parse"]:
            return subprocess.CompletedProcess(argv, 0, stdout="08f8439ebfe1994b607aed6adf857c80e8894c4c\n")
        assert original_provider.build_compatibility["after"] in target.read_text(
            encoding="utf-8"
        )
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(build.subprocess, "run", run)

    build.run_build("colibri.hy3")

    assert target.read_text(encoding="utf-8") == (
        original_provider.build_compatibility["before"]
    )
    assert calls[-1] == list(provider.build_argv)
