from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from src.ulysses_jobs import (
    RuntimeJobConfirmationError,
    RuntimeJobConflict,
    RuntimeJobStore,
    run_persisted_job,
)


def _plan(store: RuntimeJobStore, *, runtime_id: str = "hermes.gateway"):
    return store.create_plan(
        runtime_id=runtime_id,
        action="restart",
        summary="Restart Hermes gateway",
        confirmation_phrase="RESTART HERMES",
        steps=[
            {
                "label": "Restart",
                "argv": ["systemctl", "--user", "restart", "hermes-gateway.service"],
                "timeout": 60,
            }
        ],
    )


def test_plan_persists_only_a_confirmation_hash(tmp_path: Path) -> None:
    store = RuntimeJobStore(tmp_path)
    plan, token = _plan(store)
    persisted = json.loads(
        (tmp_path / "jobs" / f"{plan['id']}.json").read_text(encoding="utf-8")
    )

    assert token not in str(persisted)
    assert "confirmation_hash" in persisted
    assert "confirmation_hash" not in plan
    assert plan["status"] == "planned"
    assert (tmp_path / "jobs").stat().st_mode & 0o777 == 0o700
    assert (
        tmp_path / "jobs" / f"{plan['id']}.json"
    ).stat().st_mode & 0o777 == 0o600


def test_execute_requires_both_token_and_phrase(tmp_path: Path) -> None:
    store = RuntimeJobStore(tmp_path)
    plan, token = _plan(store)

    with pytest.raises(RuntimeJobConfirmationError):
        store.execute(
            plan["id"],
            confirmation_token="wrong",
            confirmation_phrase="RESTART HERMES",
        )
    with pytest.raises(RuntimeJobConfirmationError):
        store.execute(
            plan["id"],
            confirmation_token=token,
            confirmation_phrase="wrong",
        )


def test_runtime_lock_blocks_a_second_job(tmp_path: Path) -> None:
    store = RuntimeJobStore(tmp_path)
    first, first_token = _plan(store)
    second, second_token = _plan(store)
    store.execute(
        first["id"],
        confirmation_token=first_token,
        confirmation_phrase="RESTART HERMES",
        launcher=lambda _argv, _cwd: os.getpid(),
    )

    with pytest.raises(RuntimeJobConflict):
        store.execute(
            second["id"],
            confirmation_token=second_token,
            confirmation_phrase="RESTART HERMES",
            launcher=lambda _argv, _cwd: 12346,
        )


def test_worker_checkpoints_steps_and_releases_lock(tmp_path: Path) -> None:
    store = RuntimeJobStore(tmp_path)
    plan, token = _plan(store)
    store.execute(
        plan["id"],
        confirmation_token=token,
        confirmation_phrase="RESTART HERMES",
        launcher=lambda _argv, _cwd: 12345,
    )

    def fake_run(argv, **_kwargs):
        return subprocess.CompletedProcess(argv, 0, "gateway active\n", "")

    assert run_persisted_job(tmp_path, plan["id"], run=fake_run) == 0
    completed = store.get(plan["id"], reconcile=False)

    assert completed["status"] == "succeeded"
    assert completed["exit_code"] == 0
    assert completed["step_results"][0]["label"] == "Restart"
    assert not (tmp_path / "locks" / "hermes.gateway.lock").exists()
    assert "gateway active" in Path(completed["log_path"]).read_text(
        encoding="utf-8"
    )
    assert Path(completed["log_path"]).stat().st_mode & 0o777 == 0o600


def test_shell_steps_are_rejected(tmp_path: Path) -> None:
    store = RuntimeJobStore(tmp_path)
    with pytest.raises(Exception, match="shell runtime steps"):
        store.create_plan(
            runtime_id="hermes.gateway",
            action="restart",
            summary="unsafe",
            confirmation_phrase="UNSAFE",
            steps=[{"argv": ["echo", "no"], "shell": True}],
        )


def test_expected_output_is_a_hard_validation_gate(tmp_path: Path) -> None:
    store = RuntimeJobStore(tmp_path)
    plan, token = store.create_plan(
        runtime_id="colibri.hy3",
        action="build",
        summary="Validate Hy3 oracle",
        confirmation_phrase="BUILD",
        steps=[
            {
                "label": "Oracle",
                "argv": ["./hy3"],
                "expected_output_contains": "32/32 positions",
            }
        ],
    )
    store.execute(
        plan["id"],
        confirmation_token=token,
        confirmation_phrase="BUILD",
        launcher=lambda _argv, _cwd: os.getpid(),
    )

    def fake_run(argv, **_kwargs):
        return subprocess.CompletedProcess(argv, 0, "31/32 positions\n", "")

    assert run_persisted_job(tmp_path, plan["id"], run=fake_run) == 65
    completed = store.get(plan["id"], reconcile=False)
    assert completed["status"] == "failed"
    assert completed["step_results"][0]["output_matched"] is False


def test_expected_output_match_succeeds(tmp_path: Path) -> None:
    store = RuntimeJobStore(tmp_path)
    plan, token = store.create_plan(
        runtime_id="colibri.hy3",
        action="build",
        summary="Validate Hy3 oracle",
        confirmation_phrase="BUILD",
        steps=[
            {
                "label": "Oracle",
                "argv": ["./hy3"],
                "expected_output_contains": "32/32 positions",
            }
        ],
    )
    store.execute(
        plan["id"],
        confirmation_token=token,
        confirmation_phrase="BUILD",
        launcher=lambda _argv, _cwd: os.getpid(),
    )

    def fake_run(argv, **_kwargs):
        return subprocess.CompletedProcess(argv, 0, "32/32 positions\n", "")

    assert run_persisted_job(tmp_path, plan["id"], run=fake_run) == 0
    completed = store.get(plan["id"], reconcile=False)
    assert completed["status"] == "succeeded"
    assert completed["step_results"][0]["output_matched"] is True


def test_job_logs_are_tailed_inside_the_state_root(tmp_path: Path) -> None:
    store = RuntimeJobStore(tmp_path)
    plan, _token = _plan(store)
    log_path = Path(plan["log_path"])
    log_path.write_text("a" * 2000 + "tail", encoding="utf-8")

    payload = store.read_log(plan["id"], max_chars=1000)

    assert payload["truncated"] is True
    assert payload["text"].endswith("tail")
    assert len(payload["text"]) == 1000


@pytest.mark.parametrize(
    ("observed_code", "expected_codes", "status"),
    [(3, [3], "succeeded"), (0, [3], "failed")],
)
def test_worker_honors_explicit_expected_exit_codes(
    tmp_path: Path,
    observed_code: int,
    expected_codes: list[int],
    status: str,
) -> None:
    store = RuntimeJobStore(tmp_path)
    plan, token = store.create_plan(
        runtime_id="test.runtime",
        action="probe",
        summary="Probe expected status",
        confirmation_phrase="PROBE",
        steps=[
            {
                "label": "Probe",
                "argv": ["probe"],
                "expected_exit_codes": expected_codes,
            }
        ],
    )
    store.execute(
        plan["id"],
        confirmation_token=token,
        confirmation_phrase="PROBE",
        launcher=lambda _argv, _cwd: os.getpid(),
    )

    def fake_run(argv, **_kwargs):
        return subprocess.CompletedProcess(argv, observed_code, "", "")

    run_persisted_job(tmp_path, plan["id"], run=fake_run)
    assert store.get(plan["id"], reconcile=False)["status"] == status
