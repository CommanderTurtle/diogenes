from __future__ import annotations

from pathlib import Path

from src import diogenes_docker_projects as docker_projects


def _compose_project(tmp_path: Path, *actions: str) -> dict:
    root = tmp_path / "firecrawl"
    root.mkdir()
    compose = root / "docker-compose.yaml"
    compose.write_text("services: {}\n", encoding="utf-8")
    return {
        "id": "compose-firecrawl",
        "name": "firecrawl",
        "root": str(root),
        "compose_file": str(compose),
        "services": ["api", "rabbitmq"],
        "actions": {action: True for action in actions},
        "has_build": True,
    }


def _control(
    monkeypatch,
    tmp_path: Path,
    *actions: str,
) -> docker_projects.DockerProjectControl:
    project = _compose_project(tmp_path, *actions)
    monkeypatch.setattr(docker_projects, "_project", lambda _project_id: project)
    monkeypatch.setattr(
        docker_projects,
        "_compose_base",
        lambda _root, compose: ["docker", "compose", "-f", str(compose)],
    )
    return docker_projects.DockerProjectControl(tmp_path / "state")


def test_compose_update_does_not_force_recreate_healthy_dependencies(
    monkeypatch,
    tmp_path: Path,
) -> None:
    control = _control(monkeypatch, tmp_path, "redeploy")

    plan, _token = control.create_plan(
        project_id="compose-firecrawl",
        action="redeploy",
    )

    redeploy = plan["steps"][-1]
    assert redeploy["label"] == "Apply Compose update and wait for readiness"
    assert "--force-recreate" not in redeploy["argv"]
    assert redeploy["argv"][-4:] == [
        "--remove-orphans",
        "--wait",
        "--wait-timeout",
        "300",
    ]


def test_compose_restart_stops_then_uses_dependency_ordered_start(
    monkeypatch,
    tmp_path: Path,
) -> None:
    control = _control(monkeypatch, tmp_path, "restart")

    plan, _token = control.create_plan(
        project_id="compose-firecrawl",
        action="restart",
    )

    assert [step["label"] for step in plan["steps"]] == [
        "Stop Compose services before ordered restart",
        "Start Compose services and wait for readiness",
    ]
    assert "restart" not in plan["steps"][1]["argv"]
    assert "--wait" in plan["steps"][1]["argv"]
