import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from starlette.requests import Request

import routes.cookbook_routes as cookbook_routes
from routes.cookbook_helpers import ModelDownloadRequest, _cached_model_scan_script
from routes.cookbook_routes import _hf_hub_capability_check, _hf_xet_env_lines


ROOT = Path(__file__).resolve().parents[1]


def _download_endpoint():
    router = cookbook_routes.setup_cookbook_routes()
    return next(
        route.endpoint
        for route in router.routes
        if route.path == "/api/model/download" and "POST" in route.methods
    )


def _admin_request() -> Request:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/model/download",
            "headers": [],
            "state": {},
        }
    )
    request.state.current_user = "admin"
    return request


class _Stderr:
    async def read(self):
        return b""


class _Process:
    returncode = 0
    stderr = _Stderr()

    async def wait(self):
        return None


async def _launch(*_args, **_kwargs):
    return _Process()


async def _binary_available(*_args, **_kwargs):
    return True


def test_fast_and_reliable_xet_environment_contracts():
    assert _hf_xet_env_lines(reliable=False) == [
        "export HF_HUB_DISABLE_XET=0",
        "export HF_XET_HIGH_PERFORMANCE=1",
    ]
    assert _hf_xet_env_lines(reliable=True) == [
        "export HF_HUB_DISABLE_XET=1",
        "export HF_XET_HIGH_PERFORMANCE=0",
    ]
    assert _hf_xet_env_lines(reliable=False, powershell=True) == [
        '$env:HF_HUB_DISABLE_XET = "0"',
        '$env:HF_XET_HIGH_PERFORMANCE = "1"',
    ]
    assert "import hf_xet" in _hf_hub_capability_check(require_xet=True)
    assert "import hf_xet" not in _hf_hub_capability_check(require_xet=False)
    assert "Version('0.32.0')" in _hf_hub_capability_check(require_xet=True)


def test_legacy_disable_hf_transfer_input_remains_a_reliable_lane_alias():
    current = ModelDownloadRequest(
        repo_id="org/model",
        reliable_download=True,
    )
    legacy = ModelDownloadRequest(
        repo_id="org/model",
        disable_hf_transfer=True,
    )
    fast = ModelDownloadRequest(repo_id="org/model")

    assert current.use_reliable_download is True
    assert legacy.use_reliable_download is True
    assert fast.use_reliable_download is False


def test_generic_downloader_uses_xet_without_legacy_transfer_runtime():
    route_source = (ROOT / "routes" / "cookbook_routes.py").read_text(
        encoding="utf-8"
    )
    generic_route_source = (
        route_source[: route_source.index("async def _start_ninfer_artifact_download")]
        + route_source[route_source.index("def setup_cookbook_routes"):]
    )
    helper_source = (ROOT / "routes" / "cookbook_helpers.py").read_text(
        encoding="utf-8"
    )
    dependency_source = (ROOT / "routes" / "shell_routes.py").read_text(
        encoding="utf-8"
    )
    frontend_source = "\n".join(
        (ROOT / "static" / "js" / filename).read_text(encoding="utf-8")
        for filename in (
            "cookbook.js",
            "cookbook-deps-recipes.js",
            "cookbookDownload.js",
            "cookbookRunning.js",
            "cookbookServe.js",
        )
    )

    assert "huggingface_hub[hf_xet]" in generic_route_source
    assert "import hf_xet" in generic_route_source
    assert "HF_HUB_DISABLE_XET" in generic_route_source
    assert "HF_XET_HIGH_PERFORMANCE" in generic_route_source
    assert "HF_HUB_ENABLE_HF_TRANSFER" not in generic_route_source
    assert "import hf_transfer" not in generic_route_source
    assert "ps_lines.append('try {{')" not in route_source
    assert "ps_lines.append('try {')" in route_source
    assert '"name": "hf_xet"' in dependency_source
    assert '"pip": "huggingface_hub[hf_xet]"' in dependency_source
    assert "reliable_download: true" in frontend_source
    assert "os.environ['HF_HUB_DISABLE_XET']='0'" in frontend_source
    assert "os.environ['HF_XET_HIGH_PERFORMANCE']='1'" in frontend_source
    assert "cache_dir=os.path.join(os.path.expanduser(" in frontend_source
    assert "local_dir=os.path.expanduser(" not in frontend_source
    assert "disable_hf_transfer" not in frontend_source

    # The old key remains only as a compatibility field and alias.
    assert helper_source.count("disable_hf_transfer") == 2


def test_backend_error_is_not_presented_as_a_user_stop():
    source = (ROOT / "static" / "js" / "cookbookRunning.js").read_text(
        encoding="utf-8"
    )
    assert "if (status === 'error') return 'failed';" in source
    assert "if (status === 'error') return 'stopped';" not in source


def test_configured_download_root_scans_its_resumable_hub_cache(tmp_path):
    model_root = tmp_path / "models"
    hub = model_root / "hub"
    cached = hub / "models--xet-contract--sample-model"
    (cached / "blobs").mkdir(parents=True)
    (cached / "blobs" / "weights.safetensors").write_bytes(b"weights")
    (cached / "snapshots" / "revision").mkdir(parents=True)
    (cached / "snapshots" / "revision" / "config.json").write_text(
        "{}",
        encoding="utf-8",
    )

    scan_source = _cached_model_scan_script([str(model_root)])
    assert "scan_hf(os.path.join(p, 'hub'))" in scan_source
    assert f"scan_model_root({str(model_root)!r})" in scan_source
    assert scan_source.index("scan_model_root(" + repr(str(model_root))) < (
        scan_source.index("for _hf_cache in hf_cache_paths()")
    )

    scan_path = tmp_path / "scan.py"
    scan_path.write_text(scan_source, encoding="utf-8")
    empty_home = tmp_path / "home"
    empty_home.mkdir()
    env = dict(os.environ)
    env["HOME"] = str(empty_home)
    env.pop("HF_HOME", None)
    env.pop("HF_HUB_CACHE", None)
    env.pop("HUGGINGFACE_HUB_CACHE", None)
    result = subprocess.run(
        [sys.executable, str(scan_path)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    models = {item["repo_id"]: item for item in json.loads(result.stdout)}
    record = models["xet-contract/sample-model"]
    assert record["path"] == str(hub)
    assert record["size_bytes"] == len(b"weights")
    assert record["nb_files"] == 1


@pytest.mark.asyncio
async def test_local_bash_runner_uses_fast_xet_lane(monkeypatch, tmp_path):
    monkeypatch.setattr(cookbook_routes, "require_admin", lambda _request: None)
    monkeypatch.setattr(cookbook_routes, "IS_WINDOWS", False)
    monkeypatch.setattr(cookbook_routes, "TMUX_LOG_DIR", tmp_path)
    monkeypatch.setattr(cookbook_routes, "_binary_available", _binary_available)
    monkeypatch.setattr(
        cookbook_routes.asyncio,
        "create_subprocess_shell",
        _launch,
    )

    response = await _download_endpoint()(
        _admin_request(),
        ModelDownloadRequest(
            repo_id="org/model",
            hf_token="hf_test",
        ),
    )

    assert response["ok"] is True
    runner = next(tmp_path.glob("cookbook-*.sh")).read_text(encoding="utf-8")
    assert "export HF_HUB_DISABLE_XET=0" in runner
    assert "export HF_XET_HIGH_PERFORMANCE=1" in runner
    assert "huggingface_hub[hf_xet]" in runner
    assert "import hf_xet" in runner
    assert "HF_HUB_ENABLE_HF_TRANSFER" not in runner


@pytest.mark.asyncio
async def test_ninfer_download_uses_the_isolated_transfer_environment(
    monkeypatch,
    tmp_path,
):
    ninfer_root = tmp_path / "Odysseus" / "ninfer" / "ninfer"
    ninfer_root.mkdir(parents=True)
    download_root = tmp_path / "temp-hf-download-venv"
    activate = download_root / ".venv" / "bin" / "activate"
    activate.parent.mkdir(parents=True)
    activate.write_text("# activate\n", encoding="utf-8")
    log_root = tmp_path / "logs"

    monkeypatch.setattr(cookbook_routes, "require_admin", lambda _request: None)
    monkeypatch.setattr(cookbook_routes, "IS_WINDOWS", False)
    monkeypatch.setattr(cookbook_routes, "TMUX_LOG_DIR", log_root)
    monkeypatch.setattr(cookbook_routes, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(
        cookbook_routes.shutil,
        "which",
        lambda name: f"/usr/bin/{name}",
    )
    monkeypatch.setattr(
        cookbook_routes.asyncio,
        "create_subprocess_shell",
        _launch,
    )
    monkeypatch.setenv("DIOGENES_NINFER_ROOT", str(ninfer_root))
    monkeypatch.setenv("DIOGENES_HF_TRANSFER_ROOT", str(download_root))

    response = await _download_endpoint()(
        _admin_request(),
        ModelDownloadRequest(
            repo_id="DreamFast/example-Ninfer",
            hf_token="hf_test",
            backend="ninfer",
        ),
    )

    assert response["ok"] is True
    assert response["ninfer_model_dir"] == str(ninfer_root / "models1")
    runner = next(log_root.glob("cookbook-*.sh"))
    downloader = next(log_root.glob("cookbook-*-download-ninfer.py"))
    source = runner.read_text(encoding="utf-8")
    download_source = downloader.read_text(encoding="utf-8")
    assert f"source {activate}" in source
    assert f"cd -- {download_root}" in source
    assert f"uv run {downloader}" in source
    assert "cp -- \"$NINFER_SOURCE\"" in source
    assert "models1" in source
    assert "--lm-head-draft --vision --cors" in source
    assert 'os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"' in download_source
    assert 'os.environ["TOKIO_WORKER_THREADS"] = "16"' in download_source
    assert "local_dir_use_symlinks=False" in download_source
    subprocess.run(["bash", "-n", str(runner)], check=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "request_kwargs",
    (
        {"reliable_download": True},
        {"disable_hf_transfer": True},
    ),
)
async def test_remote_windows_runner_uses_reliable_xet_contract(
    monkeypatch,
    tmp_path,
    request_kwargs,
):
    monkeypatch.setattr(cookbook_routes, "require_admin", lambda _request: None)
    monkeypatch.setattr(cookbook_routes, "TMUX_LOG_DIR", tmp_path)
    monkeypatch.setattr(
        cookbook_routes.asyncio,
        "create_subprocess_shell",
        _launch,
    )

    response = await _download_endpoint()(
        _admin_request(),
        ModelDownloadRequest(
            repo_id="org/model",
            hf_token="hf_test",
            remote_host="winbox",
            platform="windows",
            **request_kwargs,
        ),
    )

    assert response["ok"] is True
    runners = sorted(
        tmp_path.glob("cookbook-*_run.ps1"),
        key=lambda path: path.stat().st_mtime_ns,
    )
    runner = runners[-1].read_text(encoding="utf-8")
    assert '$env:HF_HUB_DISABLE_XET = "1"' in runner
    assert '$env:HF_XET_HIGH_PERFORMANCE = "0"' in runner
    assert "import hf_xet" not in runner
    assert "try {{" not in runner
    assert "if ($hfPath) {{" not in runner
    assert "HF_HUB_ENABLE_HF_TRANSFER" not in runner
