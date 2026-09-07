from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from src.diogenes_host_services import (
    HostServiceError,
    HostServicesManager,
    MM_TOOL_SERVICES,
    TMUX_SOCKET,
    clean_host_path,
)


class _Recorder:
    def __init__(self, output: str = "") -> None:
        self.calls: list[list[str]] = []
        self.output = output

    def __call__(self, argv, **_kwargs):
        self.calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, self.output, "")


def _project(root: Path, project: str, launcher: str, *, venv: bool = True) -> Path:
    directory = root / project
    directory.mkdir(parents=True, exist_ok=True)
    (directory / launcher).write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    if venv:
        activate = directory / ".venv" / "bin" / "activate"
        activate.parent.mkdir(parents=True)
        activate.write_text("# activate\n", encoding="utf-8")
    return directory


def test_mm_tools_catalog_has_the_explicit_launch_contract() -> None:
    values = {
        item.id: (item.project, item.launchers, item.port, item.requires_venv)
        for item in MM_TOOL_SERVICES
    }

    assert list(values) == [
        "mm.ideogram",
        "mm.img2svg",
        "mm.longcat",
        "mm.minimax",
        "mm.muscriptor",
        "mm.musvit",
        "mm.redesign",
        "mm.stableaudio",
        "mm.symphony",
        "mm.translate",
        "mm.videocompact",
        "mm.video-to-gif-avif",
        "mm.vocalrender",
        "mm.whisper",
        "http.whisper",
        "http.longcat",
        "http.translate",
    ]
    assert values["mm.ideogram"] == ("ideogram", ("startwithuv",), 8174, True)
    assert values["mm.img2svg"] == ("img2svg", ("startwithrust",), 417, False)
    assert values["mm.musvit"][1] == ("startwithuv.sh", "startwithuv")
    assert values["mm.videocompact"][0] == "video-compact"
    assert values["http.whisper"][2] == 8172
    assert values["http.longcat"][2] == 8230
    assert values["http.translate"][2] == 8176


def test_clean_host_path_removes_only_the_active_venv(tmp_path: Path) -> None:
    home = tmp_path / "home"
    active = tmp_path / "diogenes" / ".venv"
    other = tmp_path / "multimedia" / "translate" / ".venv" / "bin"
    value = os.pathsep.join((str(active / "bin"), str(other), "/usr/bin"))

    result = clean_host_path(value, virtual_env=str(active), home=home).split(os.pathsep)

    assert str(active / "bin") not in result
    assert str(other) in result
    assert str(home / ".local" / "bin") in result
    assert str(home / ".bun" / "bin") in result
    assert str(home / ".cargo" / "bin") in result


def test_every_tmux_command_uses_the_private_socket(tmp_path: Path) -> None:
    recorder = _Recorder()
    manager = HostServicesManager(
        root=tmp_path / "multimedia",
        state_root=tmp_path / "state",
        tmux="/usr/bin/tmux",
        runner=recorder,
    )

    manager._tmux("list-sessions")

    assert recorder.calls == [["/usr/bin/tmux", "-L", TMUX_SOCKET, "list-sessions"]]


def test_service_wrapper_enters_only_the_selected_project_venv(tmp_path: Path) -> None:
    root = tmp_path / "multimedia"
    project = _project(root, "translate", "startwithuv.sh")
    manager = HostServicesManager(
        root=root,
        state_root=tmp_path / "state",
        tmux="/usr/bin/tmux",
        runner=_Recorder(),
    )

    wrapper, log = manager._service_wrapper(manager._spec("mm.translate"))
    source = wrapper.read_text(encoding="utf-8")

    assert f"source {project / '.venv' / 'bin' / 'activate'}" in source
    assert f"bash {project / 'startwithuv.sh'}" in source
    assert "unset VIRTUAL_ENV PYTHONHOME CONDA_PREFIX CONDA_DEFAULT_ENV UV_ACTIVE" in source
    assert str(log).endswith("logs/mm-translate.log")
    assert "Odysseus/Diogenes/.venv" not in source


def test_img2svg_wrapper_uses_rust_launcher_without_a_venv(tmp_path: Path) -> None:
    root = tmp_path / "multimedia"
    project = _project(root, "img2svg", "startwithrust", venv=False)
    manager = HostServicesManager(
        root=root,
        state_root=tmp_path / "state",
        tmux="/usr/bin/tmux",
        runner=_Recorder(),
    )

    wrapper, _log = manager._service_wrapper(manager._spec("mm.img2svg"))
    source = wrapper.read_text(encoding="utf-8")

    assert "source " not in source
    assert f"bash {project / 'startwithrust'}" in source


def test_observation_reads_env_ports_and_reports_real_collisions(tmp_path: Path) -> None:
    root = tmp_path / "multimedia"
    ideogram = _project(root, "ideogram", "startwithuv")
    (ideogram / ".env").write_text("export OBJECT_REMOVER_PORT=9017\n", encoding="utf-8")
    _project(root, "redesign", "startwithuv.sh")
    _project(root, "whisper", "startwithuv.sh")
    recorder = _Recorder("host-svc-mm-ideogram\n")
    manager = HostServicesManager(
        root=root,
        state_root=tmp_path / "state",
        tmux="/usr/bin/tmux",
        runner=recorder,
        port_probe=lambda port: port in {9017, 8173},
    )

    report = manager.observe()
    by_id = {item["id"]: item for item in report["services"]}

    assert by_id["mm.ideogram"]["port"] == 9017
    assert by_id["mm.ideogram"]["managed"] is True
    assert by_id["mm.ideogram"]["state"] == "running"
    assert by_id["mm.redesign"]["port_conflicts"] == ["mm.whisper"]
    assert by_id["mm.whisper"]["port_conflicts"] == ["mm.redesign"]


def test_shell_creation_is_bounded_to_a_generated_private_tmux_session(tmp_path: Path) -> None:
    recorder = _Recorder()
    manager = HostServicesManager(
        root=tmp_path / "multimedia",
        state_root=tmp_path / "state",
        tmux="/usr/bin/tmux",
        runner=recorder,
    )

    manager.create_shell(title="Scratch", cwd=str(tmp_path), cols=123, rows=45)

    new_session = next(call for call in recorder.calls if "new-session" in call)
    shell_id = new_session[new_session.index("-s") + 1]
    assert shell_id.startswith("host-shell-")
    assert new_session[:3] == ["/usr/bin/tmux", "-L", TMUX_SOCKET]
    assert new_session[new_session.index("-x") + 1] == "123"
    assert new_session[new_session.index("-y") + 1] == "45"
    wrapper = tmp_path / "state" / "wrappers" / f"{shell_id}.sh"
    text = wrapper.read_text(encoding="utf-8")
    assert "unset VIRTUAL_ENV PYTHONHOME CONDA_PREFIX CONDA_DEFAULT_ENV UV_ACTIVE" in text
    assert f"cd -- {tmp_path}" in text
    assert "exec " in text and " -l" in text
    assert any(call[3:6] == ["set-option", "-w", "-t"] for call in recorder.calls)


def test_unknown_services_and_untrusted_shell_ids_fail_explicitly(tmp_path: Path) -> None:
    manager = HostServicesManager(
        root=tmp_path / "multimedia",
        state_root=tmp_path / "state",
        tmux="/usr/bin/tmux",
        runner=_Recorder(),
    )

    with pytest.raises(HostServiceError, match="unknown host service"):
        manager.act("mm.not-real", "start")
    with pytest.raises(HostServiceError, match="invalid operator shell id"):
        manager.delete_shell("../../default")
