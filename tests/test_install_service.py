import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_installer_uses_the_named_per_user_diogenes_unit() -> None:
    script = (ROOT / "install-service.sh").read_text(encoding="utf-8")

    assert 'USER_SYSTEMD_DIR="$HOME/.config/systemd/user"' in script
    assert 'INSTALLED_SERVICE="$USER_SYSTEMD_DIR/diogenes.service"' in script
    assert 'LINK_ROOT="$HOME/.local/share/diogenes"' in script
    assert 'CURRENT_LINK="$LINK_ROOT/current"' in script
    assert '[[ -e "$CURRENT_LINK" && ! -L "$CURRENT_LINK" ]]' in script
    assert '[[ ! -f "$SCRIPT_DIR/.env" ]]' in script
    assert '[[ ! -x "$SCRIPT_DIR/.venv/bin/python" ]]' in script
    assert 'ln -s -- "$SCRIPT_DIR" "$TEMP_LINK"' in script
    assert 'mv -Tf -- "$TEMP_LINK" "$CURRENT_LINK"' in script
    assert 'install -m 0644 "$SERVICE_FILE" "$INSTALLED_SERVICE"' in script
    assert "systemctl --user daemon-reload" in script
    assert "systemctl --user enable diogenes.service" in script
    assert "systemctl --user restart diogenes.service" in script
    assert "systemctl --user --no-pager status diogenes.service" in script
    assert "sudo " not in script
    assert "/etc/systemd/system" not in script


def test_user_unit_targets_the_checkout_selected_by_the_installer() -> None:
    unit = (ROOT / "odysseus-ui.service").read_text(encoding="utf-8")
    current = "%h/.local/share/diogenes/current"

    assert f"WorkingDirectory={current}" in unit
    assert f"EnvironmentFile={current}/.env" in unit
    assert f"ExecStart={current}/.venv/bin/python " in unit
    assert "%h/Odysseus/Diogenes-prod" not in unit


@pytest.mark.skipif(os.name == "nt", reason="per-user systemd installer targets Linux")
def test_installer_selects_the_invoking_checkout_and_restarts(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout with spaces"
    checkout.mkdir()
    shutil.copy2(ROOT / "install-service.sh", checkout / "install-service.sh")
    shutil.copy2(ROOT / "odysseus-ui.service", checkout / "odysseus-ui.service")
    (checkout / ".env").write_text("AUTH_ENABLED=true\n", encoding="utf-8")
    python = checkout / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
    python.chmod(0o755)

    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    systemctl_log = tmp_path / "systemctl.log"
    systemctl = fake_bin / "systemctl"
    systemctl.write_text(
        "#!/usr/bin/env sh\nprintf '%s\\n' \"$*\" >> \"$SYSTEMCTL_LOG\"\n",
        encoding="utf-8",
    )
    systemctl.chmod(0o755)
    environment = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "SYSTEMCTL_LOG": str(systemctl_log),
    }

    subprocess.run(
        ["bash", str(checkout / "install-service.sh")],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    current = home / ".local" / "share" / "diogenes" / "current"
    assert current.is_symlink()
    assert current.resolve() == checkout.resolve()
    assert (
        home / ".config" / "systemd" / "user" / "diogenes.service"
    ).read_text(encoding="utf-8") == (
        checkout / "odysseus-ui.service"
    ).read_text(encoding="utf-8")
    calls = systemctl_log.read_text(encoding="utf-8").splitlines()
    assert "--user daemon-reload" in calls
    assert "--user enable diogenes.service" in calls
    assert "--user restart diogenes.service" in calls
    assert "--user --no-pager status diogenes.service" in calls


@pytest.mark.skipif(os.name == "nt", reason="per-user systemd installer targets Linux")
def test_installer_refuses_non_symlink_current_without_mutating_it(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    shutil.copy2(ROOT / "install-service.sh", checkout / "install-service.sh")
    shutil.copy2(ROOT / "odysseus-ui.service", checkout / "odysseus-ui.service")
    (checkout / ".env").write_text("AUTH_ENABLED=true\n", encoding="utf-8")
    python = checkout / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
    python.chmod(0o755)

    home = tmp_path / "home"
    current = home / ".local" / "share" / "diogenes" / "current"
    current.mkdir(parents=True)
    marker = current / "keep"
    marker.write_text("preserve\n", encoding="utf-8")

    result = subprocess.run(
        ["bash", str(checkout / "install-service.sh")],
        env={**os.environ, "HOME": str(home)},
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "is not a symbolic link" in result.stderr
    assert marker.read_text(encoding="utf-8") == "preserve\n"
