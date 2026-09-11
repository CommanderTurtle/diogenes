from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.diogenes_skill_auditor as auditor
from src.ulysses_jobs import RuntimeJobError


def test_catalog_is_compacted_from_retrieval_graph(monkeypatch) -> None:
    monkeypatch.setattr(
        auditor,
        "_catalog_browse",
        lambda **_kwargs: {
            "generated_at": "2026-09-11T00:00:00Z",
            "summary": {"skills": 1, "sources": 1, "categories": 1, "tags": 1},
            "roots": [
                {
                    "id": "source:test",
                    "kind": "source",
                    "label": "test",
                    "children": ["test:demo"],
                }
            ],
            "nodes": [{"id": "source:test", "kind": "source", "count": 1}],
            "facets": {
                "sources": {"test": ["test:demo"]},
                "categories": {"development": ["test:demo"]},
                "states": {"cold": ["test:demo"]},
                "tags": {"python": ["test:demo"]},
            },
            "skills": [
                {
                    "item_id": "test:demo",
                    "title": "demo",
                    "description": "A compact entry",
                    "descriptor": "large text that must not reach the index response",
                    "source": "test",
                    "state": "cold",
                    "categories": ["development"],
                    "tags": ["python"],
                    "canonical_path": "/repo/demo/SKILL.md",
                    "relative_path": "demo/SKILL.md",
                    "package_hash": "abc",
                    "graph_key": "skills/test/demo",
                    "duplicate_paths": ["/repo/demo/SKILL.md"],
                    "duplicate_sources": ["test"],
                }
            ],
        },
    )
    monkeypatch.setattr(
        auditor,
        "_retrieval_skills",
        lambda: [
            {
                "skill_id": "test:demo",
                "state": "cold",
                "modified_at": "2026-09-10T00:00:00Z",
                "bytes": 42,
                "symlinked": False,
            }
        ],
    )

    report = auditor.collect_retrieval_catalog()

    assert report["schema_version"] == "diogenes.retrieval-workspace.v1"
    assert report["roots"] == [
        {"id": "source:test", "label": "test", "kind": "source", "count": 1}
    ]
    assert report["facets"]["categories"] == [
        {"name": "development", "count": 1}
    ]
    assert report["skills"][0]["skill_id"] == "test:demo"
    assert report["skills"][0]["editable"] is False
    assert "descriptor" not in report["skills"][0]


def test_skill_inspection_uses_exact_cli_output(monkeypatch) -> None:
    content = {
        "skill_id": "test:demo",
        "name": "demo",
        "state": "cold",
        "canonical_path": "/repo/demo/SKILL.md",
    }
    monkeypatch.setattr(auditor, "_cli", lambda: Path("/retrieval"))
    monkeypatch.setattr(auditor, "native_host_environment", lambda: {})
    monkeypatch.setattr(
        auditor.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(content) + "\n\n--- SKILL.md ---\n\n# Demo\n",
            stderr="",
        ),
    )
    monkeypatch.setattr(
        auditor,
        "_CATALOG_CACHE",
        {
            "skills": [
                {
                    "item_id": "test:demo",
                    "categories": ["development"],
                    "tags": ["python"],
                    "package_hash": "abc",
                    "duplicate_paths": ["/repo/demo/SKILL.md"],
                }
            ]
        },
    )

    report = auditor.inspect_retrieval_skill("test:demo")

    assert report["metadata"]["package_hash"] == "abc"
    assert report["metadata"]["categories"] == ["development"]
    assert report["markdown"].strip() == "# Demo"


def test_runtime_report_uses_retrieval_status_and_doctor(monkeypatch) -> None:
    def fake_json(arguments: list[str], **_kwargs):
        if arguments == ["status"]:
            return {
                "catalog": {"entries": 1},
                "watcher": {"healthy": True, "backend": "inotify"},
                "projections": {
                    "hermes": {"skills": []},
                    "omp": {"skills": []},
                },
                "sources": [
                    {
                        "name": "test",
                        "kind": "skills",
                        "state": "cold",
                        "enabled": True,
                        "available": True,
                        "stale": False,
                        "checkpoint": {
                            "document_count": 1,
                            "last_synced_at": "now",
                        },
                        "index_health": {"current": True, "reasons": []},
                    }
                ],
            }
        assert arguments == ["doctor", "--json"]
        return {
            "summary": {"checks": 2, "passed": 2, "failed": 0},
            "checks": [
                {
                    "scope": "hermes:default",
                    "name": "MCP",
                    "passed": True,
                    "detail": "/config.yaml",
                },
                {
                    "scope": "hermes:default",
                    "name": "routing skill",
                    "passed": True,
                    "detail": "/SKILL.md",
                },
            ],
        }

    monkeypatch.setattr(auditor, "_retrieval_json", fake_json)

    report = auditor.collect_retrieval_runtime()

    assert report["doctor"]["failed"] == 0
    assert report["profiles"][0]["scope"] == "hermes:default"
    assert report["profiles"][0]["managed"] is True
    assert report["sources"][0]["document_count"] == 1


def test_plans_delegate_mutations_to_retrieval_cli(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(auditor, "_cli", lambda: Path("/retrieval"))
    control = auditor.SkillAuditorControl(tmp_path)

    sync, _token = control.create_plan(action="catalog-sync")
    assert sync["steps"][0]["argv"] == ["/retrieval", "catalog", "sync"]

    close, _token = control.create_plan(
        action="session-close",
        harness="hermes",
    )
    assert close["steps"][0]["argv"] == [
        "/retrieval",
        "session-close",
        "--harness",
        "hermes",
        "--all-profiles",
    ]

    retrieve, _token = control.create_plan(
        action="retrieve",
        harness="omp",
        query="python packaging",
    )
    assert retrieve["steps"][0]["argv"] == [
        "/retrieval",
        "retrieve",
        "python packaging",
        "--harness",
        "omp",
    ]


def test_plan_rejects_invalid_harness(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(auditor, "_cli", lambda: Path("/retrieval"))
    control = auditor.SkillAuditorControl(tmp_path)

    with pytest.raises(RuntimeJobError, match="requires hermes or omp"):
        control.create_plan(
            action="retrieve",
            harness="other",
            query="demo",
        )
