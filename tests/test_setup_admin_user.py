import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys


def _load_setup_module():
    spec = importlib.util.spec_from_file_location("odysseus_setup_under_test", Path("setup.py"))
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_fresh_setup_creates_and_loads_env_before_constants_import(
    tmp_path,
):
    source = Path("setup.py").resolve()
    (tmp_path / "setup.py").write_text(
        source.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / ".env.example").write_text(
        "SETUP_BOOTSTRAP_SENTINEL=loaded-before-constants\n",
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
    constants = """
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
assert (ROOT / ".env").is_file()
assert os.environ.get("SETUP_BOOTSTRAP_SENTINEL") == "loaded-before-constants"
DATA_DIR = str(ROOT / "data")
AUTH_FILE = str(ROOT / "data" / "auth.json")
UPLOAD_DIR = str(ROOT / "data" / "uploads")
PERSONAL_DIR = str(ROOT / "data" / "personal")
PERSONAL_UPLOADS_DIR = str(ROOT / "data" / "personal-uploads")
TTS_CACHE_DIR = str(ROOT / "data" / "tts")
GENERATED_IMAGES_DIR = str(ROOT / "data" / "images")
DEEP_RESEARCH_DIR = str(ROOT / "data" / "research")
CHROMA_DIR = str(ROOT / "data" / "chroma")
RAG_DIR = str(ROOT / "data" / "rag")
MEMORY_VECTORS_DIR = str(ROOT / "data" / "memory")
PASSWORD_MIN_LENGTH = 12
"""
    (tmp_path / "src" / "constants.py").write_text(
        constants.lstrip(),
        encoding="utf-8",
    )
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "core" / "auth.py").write_text(
        "RESERVED_USERNAMES = set()\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment.pop("SETUP_BOOTSTRAP_SENTINEL", None)
    runner = (
        "import importlib.util, pathlib; "
        "path = pathlib.Path('setup.py').resolve(); "
        "spec = importlib.util.spec_from_file_location('fresh_setup', path); "
        "module = importlib.util.module_from_spec(spec); "
        "spec.loader.exec_module(module)"
    )

    result = subprocess.run(
        [sys.executable, "-c", runner],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / ".env").read_text(encoding="utf-8") == (
        "SETUP_BOOTSTRAP_SENTINEL=loaded-before-constants\n"
    )


def test_create_default_admin_normalizes_env_username(tmp_path, monkeypatch):
    setup_module = _load_setup_module()
    monkeypatch.setattr(setup_module, "AUTH_FILE", str(tmp_path / "auth.json"))
    monkeypatch.setenv("ODYSSEUS_ADMIN_USER", " AdminUser ")
    monkeypatch.setenv("ODYSSEUS_ADMIN_PASSWORD", "temporary-password")

    assert setup_module.create_default_admin() == "created"

    auth_path = tmp_path / "auth.json"
    data = json.loads(auth_path.read_text(encoding="utf-8"))
    assert "adminuser" in data["users"]
    assert "AdminUser" not in data["users"]


def test_main_loads_admin_password_from_env_file(tmp_path, monkeypatch):
    """Regression: setup.py must honor an admin password pre-seeded in .env on
    native installs, even when the var is not exported into the shell
    (website/setup.md documents this). Previously setup.py never called
    load_dotenv(), so os.getenv() saw nothing and a random password was
    generated instead."""
    import bcrypt

    setup_module = _load_setup_module()

    # Credentials live ONLY in a .env beside setup.py (written with a UTF-8 BOM,
    # the Notepad-on-Windows case that utf-8-sig must tolerate) — not exported.
    monkeypatch.delenv("ODYSSEUS_ADMIN_USER", raising=False)
    monkeypatch.delenv("ODYSSEUS_ADMIN_PASSWORD", raising=False)
    (tmp_path / ".env").write_text(
        "ODYSSEUS_ADMIN_USER=presetuser\nODYSSEUS_ADMIN_PASSWORD=fromenvfile12345\n",
        encoding="utf-8-sig",
    )

    # Point setup at the temp dir and neutralize main()'s heavy steps.
    monkeypatch.setattr(setup_module, "BASE_DIR", str(tmp_path))
    auth_path = tmp_path / "auth.json"
    monkeypatch.setattr(setup_module, "AUTH_FILE", str(auth_path))
    monkeypatch.setattr(setup_module, "check_arch", lambda: None)
    monkeypatch.setattr(setup_module, "create_dirs", lambda: None)
    monkeypatch.setattr(setup_module, "create_env", lambda: None)
    monkeypatch.setattr(setup_module, "check_deps", lambda: None)
    monkeypatch.setattr(setup_module, "init_database", lambda: None)
    # Force the non-interactive branch so the test never blocks on a prompt.
    monkeypatch.setenv("ODYSSEUS_SKIP_ADMIN_PROMPT", "1")

    try:
        assert setup_module.main() == 0
    finally:
        # load_dotenv writes real os.environ entries; undo so sibling tests
        # don't inherit them.
        os.environ.pop("ODYSSEUS_ADMIN_USER", None)
        os.environ.pop("ODYSSEUS_ADMIN_PASSWORD", None)

    data = json.loads(auth_path.read_text(encoding="utf-8"))
    assert "presetuser" in data["users"], data
    assert bcrypt.checkpw(
        b"fromenvfile12345", data["users"]["presetuser"]["password_hash"].encode()
    ), "admin password from .env was ignored; a random one was generated"


def test_main_does_not_report_success_when_database_init_fails(monkeypatch):
    setup_module = _load_setup_module()
    monkeypatch.setattr(setup_module, "check_arch", lambda: None)
    monkeypatch.setattr(setup_module, "create_dirs", lambda: None)
    monkeypatch.setattr(setup_module, "create_env", lambda: None)
    monkeypatch.setattr(setup_module, "check_deps", lambda: None)
    monkeypatch.setattr(
        setup_module,
        "init_database",
        lambda: (_ for _ in ()).throw(RuntimeError("database unavailable")),
    )

    try:
        setup_module.main()
    except RuntimeError as exc:
        assert str(exc) == "database unavailable"
    else:
        raise AssertionError("setup.py masked a database initialization failure")
