from __future__ import annotations

from pathlib import Path

import src.ulysses_runtime_bootstrap as bootstrap


def test_bootstrap_creates_defaults_once_without_replacing_user_config(
    monkeypatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "bifrost"
    startup = root / "startup.sh"
    env = root / ".env"
    item = {
        "id": "bifrost.gateway",
        "root": root,
        "documents": (),
        "bootstrap_files": (
            {
                "path": startup,
                "content": "#!/usr/bin/env bash\nexec npx bifrost\n",
                "mode": "0755",
            },
            {
                "path": env,
                "content": "BIFROST_PORT=7999\n",
                "mode": "0600",
            },
        ),
    }
    monkeypatch.setattr(bootstrap, "load_runtime_management", lambda: (item,))

    written = bootstrap.bootstrap_runtime("bifrost.gateway")
    startup.write_text("# user-managed\n", encoding="utf-8")
    second = bootstrap.bootstrap_runtime("bifrost.gateway")

    assert written == [startup, env]
    assert second == []
    assert startup.read_text(encoding="utf-8") == "# user-managed\n"
    assert env.read_text(encoding="utf-8") == "BIFROST_PORT=7999\n"
    assert startup.stat().st_mode & 0o777 == 0o755
    assert env.stat().st_mode & 0o777 == 0o600
