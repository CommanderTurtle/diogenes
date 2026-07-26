from __future__ import annotations

import re
import sys
from importlib.machinery import ModuleSpec
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

import download_models
from scripts import hf_download


def _isolate_hf_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    defaults = {
        "HF_HUB_DOWNLOAD_MAX_WORKERS": "16",
        "HF_HUB_DOWNLOAD_TIMEOUT": "60",
        "HF_HUB_ETAG_TIMEOUT": "30",
        "HF_XET_NUM_CONCURRENT_RANGE_GETS": "16",
    }
    for key in (
        "DO_NOT_TRACK",
        "HF_HUB_DISABLE_PROGRESS_BARS",
        "HF_HUB_DISABLE_TELEMETRY",
        "HF_HUB_DISABLE_UPDATE_CHECK",
        "HF_HUB_DISABLE_XET",
        "HF_HUB_DOWNLOAD_MAX_WORKERS",
        "HF_HUB_DOWNLOAD_TIMEOUT",
        "HF_HUB_ETAG_TIMEOUT",
        "HF_XET_HIGH_PERFORMANCE",
        "HF_XET_NUM_CONCURRENT_RANGE_GETS",
    ):
        monkeypatch.setenv(key, defaults.get(key, ""))


def test_curated_download_jobs_use_exact_revisions_and_direct_folders(
    tmp_path: Path,
) -> None:
    colibri = download_models._colibri_jobs(
        {"colibri-glm", "colibri-hy3"},
        root_override=tmp_path / "colibri",
    )
    prism = download_models._prism_jobs(
        {"prism-ternary", "prism-onebit"},
        root_override=tmp_path / "prism",
        with_drafter=False,
        with_vision=False,
    )

    assert {job["label"] for job in colibri} == {
        "colibri-glm",
        "colibri-hy3",
    }
    assert all(
        re.fullmatch(r"[0-9a-f]{40}", job["revision"])
        for job in [*colibri, *prism]
    )
    assert all(job["destination"].is_absolute() for job in [*colibri, *prism])
    assert all(not job["include"] for job in colibri)
    assert [job["include"] for job in prism] == [
        ["Ternary-Bonsai-27B-Q2_0.gguf"],
        ["Bonsai-27B-Q1_0.gguf"],
    ]


def test_checkout_env_sets_destinations_without_overriding_shell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_glm = tmp_path / "env-models" / "glm"
    env_hy3 = tmp_path / "env-models" / "hy3"
    shell_hy3 = tmp_path / "shell-models" / "hy3"
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                f"ULYSSES_COLIBRI_GLM_MODEL={env_glm}",
                f"ULYSSES_COLIBRI_HY3_MODEL={env_hy3}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("ULYSSES_COLIBRI_GLM_MODEL", raising=False)
    monkeypatch.setenv("ULYSSES_COLIBRI_HY3_MODEL", str(shell_hy3))

    download_models._load_checkout_environment(tmp_path)
    jobs = {
        job["label"]: job
        for job in download_models._colibri_jobs(
            {"colibri-glm", "colibri-hy3"},
            root_override=None,
        )
    }

    assert jobs["colibri-glm"]["destination"] == env_glm.resolve()
    assert jobs["colibri-hy3"]["destination"] == shell_hy3.resolve()


def test_prism_optional_files_are_explicit_opt_ins(tmp_path: Path) -> None:
    jobs = download_models._prism_jobs(
        {"prism-ternary"},
        root_override=tmp_path,
        with_drafter=True,
        with_vision=True,
    )

    assert len(jobs) == 1
    assert jobs[0]["include"] == [
        "Ternary-Bonsai-27B-Q2_0.gguf",
        "Ternary-Bonsai-27B-dspark-Q4_1.gguf",
        "Ternary-Bonsai-27B-mmproj-Q8_0.gguf",
    ]
    assert "PQ2_0" not in " ".join(jobs[0]["include"])
    assert "Q2_g64" not in " ".join(jobs[0]["include"])


@pytest.mark.parametrize(
    "revision",
    [
        "",
        "main",
        "latest",
        "0" * 39,
        "0" * 41,
        "z" * 40,
    ],
)
def test_revision_must_be_an_exact_commit(revision: str) -> None:
    with pytest.raises(SystemExit, match="exact 40-character commit"):
        download_models._exact_revision(revision, "model revision")


def test_model_destination_cannot_be_inside_either_venv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(download_models, "ROOT", tmp_path)

    for environment in (".venv", ".venv-model-download"):
        with pytest.raises(SystemExit, match="cannot be inside"):
            download_models._safe_destination(
                tmp_path / environment / "models" / "example",
                "MODEL_PATH",
            )

    outside = tmp_path.parent / "models" / "example"
    assert download_models._safe_destination(outside, "MODEL_PATH") == outside.resolve()


def test_public_entrypoint_reexecutes_isolated_downloader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(download_models, "ROOT", tmp_path)
    environment = tmp_path / ".venv-model-download"
    interpreter = (
        environment / "Scripts" / "python.exe"
        if download_models.os.name == "nt"
        else environment / "bin" / "python"
    )
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text("", encoding="utf-8")
    (environment / "pyvenv.cfg").write_text("uv = 0.11.31\n", encoding="utf-8")
    monkeypatch.setattr(sys, "prefix", str(tmp_path / ".venv"))
    monkeypatch.setattr(
        sys,
        "argv",
        ["download_models.py", "colibri-glm", "--reliable"],
    )
    monkeypatch.delenv(download_models._DOWNLOADER_REEXEC_ENV, raising=False)
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = [str(part) for part in command]
        captured.update(kwargs)
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(download_models.subprocess, "run", fake_run)

    assert download_models._entrypoint() == 7
    assert captured["command"] == [
        str(interpreter),
        str(Path(download_models.__file__).resolve()),
        "colibri-glm",
        "--reliable",
    ]
    assert captured["cwd"] == tmp_path
    assert captured["env"][download_models._DOWNLOADER_REEXEC_ENV] == "1"
    assert captured["check"] is False


def test_public_entrypoint_requires_prepared_downloader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(download_models, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "prefix", str(tmp_path / ".venv"))
    monkeypatch.delenv(download_models._DOWNLOADER_REEXEC_ENV, raising=False)

    assert download_models._entrypoint() == 2


def test_fast_failure_retries_same_snapshot_with_reliable_lane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "models" / "example"
    job = {
        "label": "colibri-glm",
        "repo": "owner/model",
        "revision": "a" * 40,
        "destination": destination,
        "include": [],
    }
    monkeypatch.setattr(
        download_models,
        "_colibri_jobs",
        lambda *args, **kwargs: [job],
    )
    monkeypatch.setattr(
        download_models,
        "_prism_jobs",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["download_models.py", "colibri-glm"],
    )
    calls: list[list[str]] = []
    returncodes = iter((2, 0))

    def fake_run(command, **kwargs):
        calls.append([str(part) for part in command])
        return SimpleNamespace(returncode=next(returncodes))

    monkeypatch.setattr(download_models.subprocess, "run", fake_run)

    assert download_models.main() == 0
    assert len(calls) == 2
    assert calls[0][-1] == "--fast"
    assert calls[1][-1] == "--reliable"
    assert calls[0][:-1] == calls[1][:-1]
    assert calls[0][0] == sys.executable
    assert calls[0][calls[0].index("--revision") + 1] == "a" * 40
    assert calls[0][calls[0].index("--local-dir") + 1] == str(destination)


def test_reliable_option_skips_fast_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = {
        "label": "colibri-hy3",
        "repo": "owner/model",
        "revision": "b" * 40,
        "destination": tmp_path / "models" / "example",
        "include": [],
    }
    monkeypatch.setattr(
        download_models,
        "_colibri_jobs",
        lambda *args, **kwargs: [job],
    )
    monkeypatch.setattr(
        download_models,
        "_prism_jobs",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["download_models.py", "colibri-hy3", "--reliable"],
    )
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append([str(part) for part in command])
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(download_models.subprocess, "run", fake_run)

    assert download_models.main() == 0
    assert len(calls) == 1
    assert calls[0][-1] == "--reliable"


def test_helper_reliable_lane_uses_exact_direct_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate_hf_environment(monkeypatch)
    destination = tmp_path / "models" / "exact"
    captured: dict[str, object] = {}
    fake_hub = ModuleType("huggingface_hub")

    def snapshot_download(**kwargs):
        captured.update(kwargs)
        return str(destination)

    fake_hub.snapshot_download = snapshot_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)
    monkeypatch.setattr(hf_download, "_patch_tqdm", lambda: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "hf_download.py",
            "owner/model",
            "--revision",
            "c" * 40,
            "--local-dir",
            str(destination),
            "--workers",
            "12",
            "--reliable",
        ],
    )

    assert hf_download.main() == 0
    assert captured["repo_id"] == "owner/model"
    assert captured["revision"] == "c" * 40
    assert Path(str(captured["local_dir"])) == destination
    assert captured["max_workers"] == 12
    assert captured["tqdm_class"] is hf_download.PipeTqdm
    assert "local_dir_use_symlinks" not in captured
    assert hf_download.os.environ["HF_HUB_DISABLE_XET"] == "1"
    assert hf_download.os.environ["HF_HUB_DISABLE_TELEMETRY"] == "1"


def test_helper_fast_lane_fails_cleanly_without_hf_xet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate_hf_environment(monkeypatch)
    monkeypatch.setattr(hf_download.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "hf_download.py",
            "owner/model",
            "--revision",
            "d" * 40,
            "--local-dir",
            str(tmp_path / "model"),
            "--fast",
        ],
    )

    assert hf_download.main() == 2


def test_helper_fast_lane_enables_current_xet_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate_hf_environment(monkeypatch)
    destination = tmp_path / "model"
    captured: dict[str, object] = {}
    fake_hub = ModuleType("huggingface_hub")

    def snapshot_download(**kwargs):
        captured.update(kwargs)
        return str(destination)

    fake_hub.snapshot_download = snapshot_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)
    monkeypatch.setattr(hf_download, "_patch_tqdm", lambda: None)
    monkeypatch.setattr(
        hf_download.importlib.util,
        "find_spec",
        lambda name: ModuleSpec(name, loader=None),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "hf_download.py",
            "owner/model",
            "--revision",
            "e" * 40,
            "--local-dir",
            str(destination),
            "--fast",
            "--xet-workers",
            "24",
        ],
    )

    assert hf_download.main() == 0
    assert captured["revision"] == "e" * 40
    assert hf_download.os.environ["HF_HUB_DISABLE_XET"] == "0"
    assert hf_download.os.environ["HF_XET_HIGH_PERFORMANCE"] == "1"
    assert hf_download.os.environ["HF_XET_NUM_CONCURRENT_RANGE_GETS"] == "24"


def test_pipe_tqdm_obeys_tqdm_concurrent_lock_contract() -> None:
    from tqdm.contrib.concurrent import thread_map

    assert thread_map(
        lambda value: value * 2,
        [1, 2, 3],
        tqdm_class=hf_download.PipeTqdm,
        disable=True,
    ) == [2, 4, 6]
    assert hf_download.PipeTqdm.get_lock() is not None
