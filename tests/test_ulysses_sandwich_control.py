from __future__ import annotations

from pathlib import Path

from src.ulysses_sandwich_control import SandwichControl
from src.ulysses_sandwich_install import stage_bundled_sandwich


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_staging_materializes_exact_component_under_services_root(tmp_path: Path) -> None:
    services = tmp_path / "Hermes"

    result = stage_bundled_sandwich(
        repository_root=REPOSITORY_ROOT,
        home=tmp_path,
        microservices_root=services,
    )

    target = services / "sandwich"
    assert result["created"] is True
    assert result["source_root"] == str(target)
    assert (target / "manifest.json").read_bytes() == (
        REPOSITORY_ROOT / "components" / "sandwich" / "manifest.json"
    ).read_bytes()

    repeated = stage_bundled_sandwich(
        repository_root=REPOSITORY_ROOT,
        home=tmp_path,
        microservices_root=services,
    )
    assert repeated["created"] is False


def test_install_plan_targets_configured_microservices_root(
    monkeypatch,
    tmp_path: Path,
) -> None:
    services = tmp_path / "services"
    monkeypatch.setenv("ULYSSES_MICROSERVICES_ROOT", str(services))
    control = SandwichControl(tmp_path / "state")

    plan, _token = control.create_plan(
        {"ready": False, "bundled_version": "0.2.0"},
        action="install",
    )

    target = services / "sandwich"
    assert plan["confirmation_phrase"] == "INSTALL SANDWICH"
    assert plan["steps"][0]["argv"][1:] == [
        "-m",
        "src.ulysses_sandwich_install",
        "--stage",
    ]
    assert plan["steps"][1]["argv"] == [
        str(target / "scripts" / "install-user.sh"),
        "--apply",
    ]
