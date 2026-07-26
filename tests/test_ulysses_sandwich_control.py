from __future__ import annotations

from pathlib import Path

from src.ulysses_sandwich_control import SandwichControl


def test_install_plan_targets_configured_microservices_root(
    monkeypatch,
    tmp_path: Path,
) -> None:
    services = tmp_path / "services"
    monkeypatch.setenv("ULYSSES_MICROSERVICES_ROOT", str(services))
    control = SandwichControl(tmp_path / "state")

    plan, _token = control.create_plan(
        {
            "ready": False,
            "installed_version": None,
            "repository": "https://github.com/CommanderTurtle/sandwich.git",
        },
        action="install",
    )

    target = services / "sandwich"
    assert plan["confirmation_phrase"] == "INSTALL SANDWICH"
    assert plan["steps"][0]["argv"][1:] == [
        "-m",
        "src.ulysses_sandwich_install",
        "--stage",
    ]
    assert plan["steps"][1]["argv"] == [str(target / "install.sh")]
    assert plan["steps"][1]["label"] == (
        "Install Bun and the Sandwich compatibility layer"
    )
