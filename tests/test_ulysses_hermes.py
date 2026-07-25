from __future__ import annotations

from pathlib import Path

import src.ulysses_hermes as hermes


def test_mcp_arguments_include_authenticated_management_values(monkeypatch, tmp_path: Path) -> None:
    config = tmp_path / ".hermes" / "config.yaml"
    config.parent.mkdir()
    config.write_text(
        """
model:
  default: local/model
  provider: custom
mcp_servers:
  camofox:
    command: npx
    args: [-y, camofox-mcp, --env, CAMOFOX_URL=http://localhost:9377]
    enabled: true
  private:
    command: tool
    args: [--api-key, top-secret]
    env:
      PRIVATE_TOKEN: do-not-return
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(hermes.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(
        hermes,
        "_run",
        lambda argv, **_kwargs: (
            "LoadState=loaded\nActiveState=active\nSubState=running\nMainPID=42"
            if argv and argv[0] == "systemctl"
            else ""
        ),
    )

    report = hermes.collect_hermes_adoption(home=tmp_path)
    servers = {server["name"]: server for server in report["mcp_servers"]}

    assert servers["camofox"]["args"][-1] == "CAMOFOX_URL=<redacted>"
    assert servers["camofox"]["configured_args"][-1] == "CAMOFOX_URL=http://localhost:9377"
    assert servers["camofox"]["environment"] == {
        "CAMOFOX_URL": "http://localhost:9377"
    }
    assert servers["camofox"]["environment_keys"] == ["CAMOFOX_URL"]
    assert servers["private"]["args"][-1] == "<redacted>"
    assert servers["private"]["configured_args"][-1] == "top-secret"
    assert servers["private"]["environment"] == {
        "PRIVATE_TOKEN": "do-not-return"
    }
    assert servers["private"]["environment_keys"] == ["PRIVATE_TOKEN"]
    assert "top-secret" in str(report)
    assert "do-not-return" in str(report)


def test_adoption_preview_preserves_native_hermes(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / ".hermes" / "hermes-agent"
    source.mkdir(parents=True)
    (tmp_path / ".hermes" / "config.yaml").write_text(
        "mcp_servers: {}\n", encoding="utf-8"
    )

    def fake_run(argv, **_kwargs):
        if argv[0] == "systemctl":
            return (
                "LoadState=loaded\nActiveState=active\nSubState=running\n"
                "MainPID=99\nFragmentPath=/unit"
            )
        if argv[0] == "/bin/hermes":
            return "Hermes Agent v0.19.0 (2026.7.20) · upstream 35b1e578"
        if "rev-parse" in argv:
            return "35b1e578621af70c5dbffd2a6fd6c534a0a1a4b7"
        if "branch" in argv:
            return "main"
        return ""

    monkeypatch.setattr(hermes, "_run", fake_run)
    report = hermes.collect_hermes_adoption(
        home=tmp_path, executable="/bin/hermes"
    )

    assert report["schema_version"] == "ulysses.hermes-adoption.v1"
    assert report["status"] == "ready"
    assert report["ownership"]["agent_registry"] == "separate"
    assert report["adoption_preview"]["preserves_native_install"] is True
    assert report["adoption_preview"]["preserves_agent_registry"] is True
    assert report["adoption_preview"]["apply_available"] is False
    assert all(not action["enabled"] for action in report["lifecycle_actions"])
