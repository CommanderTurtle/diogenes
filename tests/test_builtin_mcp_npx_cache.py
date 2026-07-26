import asyncio
import importlib.util
from pathlib import Path
import subprocess
import sys
import types


ROOT = Path(__file__).resolve().parent.parent


def _load_builtin_mcp(monkeypatch):
    core = types.ModuleType("core")
    core.__path__ = []
    platform_compat = types.ModuleType("core.platform_compat")
    platform_compat.IS_WINDOWS = False
    platform_compat.which_tool = lambda name: None
    monkeypatch.setitem(sys.modules, "core", core)
    monkeypatch.setitem(sys.modules, "core.platform_compat", platform_compat)

    spec = importlib.util.spec_from_file_location(
        "builtin_mcp_under_test",
        ROOT / "src" / "builtin_mcp.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_npx_package_from_args_prefers_package_after_y_flag(monkeypatch):
    builtin_mcp = _load_builtin_mcp(monkeypatch)

    assert builtin_mcp._npx_package_from_args(
        ["-y", "@playwright/mcp@latest", "--headless"]
    ) == "@playwright/mcp@latest"


def test_browser_mcp_cache_requirement_is_opt_in(monkeypatch):
    monkeypatch.delenv("ODYSSEUS_BROWSER_MCP_REQUIRE_CACHE", raising=False)
    builtin_mcp = _load_builtin_mcp(monkeypatch)

    assert builtin_mcp.BROWSER_MCP_REQUIRE_CACHE is False


def test_browser_mcp_cache_requirement_can_be_enabled(monkeypatch):
    monkeypatch.setenv("ODYSSEUS_BROWSER_MCP_REQUIRE_CACHE", "1")
    builtin_mcp = _load_builtin_mcp(monkeypatch)

    assert builtin_mcp.BROWSER_MCP_REQUIRE_CACHE is True


def test_browser_provider_defaults_to_camofox(monkeypatch):
    monkeypatch.delenv("ODYSSEUS_BROWSER_MCP_PROVIDER", raising=False)
    monkeypatch.delenv("CAMOFOX_URL", raising=False)
    builtin_mcp = _load_builtin_mcp(monkeypatch)

    assert builtin_mcp.browser_mcp_provider() == "camofox"
    assert builtin_mcp._browser_server_config()["provider"] == "camofox"


def test_browser_provider_can_select_camofox_without_playwright_args(monkeypatch):
    monkeypatch.setenv("ODYSSEUS_BROWSER_MCP_PROVIDER", "camofox")
    monkeypatch.setenv("CAMOFOX_URL", "http://127.0.0.1:9377")
    builtin_mcp = _load_builtin_mcp(monkeypatch)

    config = builtin_mcp._browser_server_config()
    assert config["provider"] == "camofox"
    assert config["args"] == ["-y", "camofox-mcp@latest"]
    assert "@playwright/mcp" not in " ".join(config["args"])
    assert builtin_mcp._camofox_mcp_env() == {
        "CAMOFOX_URL": "http://127.0.0.1:9377"
    }


def test_browser_provider_can_be_disabled_without_uninstalling(monkeypatch):
    monkeypatch.setenv("ODYSSEUS_BROWSER_MCP_PROVIDER", "disabled")
    builtin_mcp = _load_builtin_mcp(monkeypatch)

    assert builtin_mcp._browser_server_config() is None


def test_browser_provider_auto_never_falls_back_to_playwright(monkeypatch):
    monkeypatch.setenv("ODYSSEUS_BROWSER_MCP_PROVIDER", "auto")
    monkeypatch.delenv("CAMOFOX_URL", raising=False)
    builtin_mcp = _load_builtin_mcp(monkeypatch)
    assert builtin_mcp.browser_mcp_provider() == "camofox"

    monkeypatch.setenv("CAMOFOX_URL", "http://localhost:9377")
    assert builtin_mcp.browser_mcp_provider() == "camofox"


def test_invalid_browser_provider_fails_closed(monkeypatch):
    monkeypatch.setenv("ODYSSEUS_BROWSER_MCP_PROVIDER", "mystery")
    builtin_mcp = _load_builtin_mcp(monkeypatch)

    assert builtin_mcp.browser_mcp_provider() == "disabled"
    assert builtin_mcp._browser_server_config() is None


def test_register_builtin_browser_uses_camofox_command_and_env(monkeypatch):
    monkeypatch.setenv("ODYSSEUS_BROWSER_MCP_PROVIDER", "camofox")
    monkeypatch.setenv("CAMOFOX_URL", "http://127.0.0.1:9377")
    monkeypatch.delenv("ODYSSEUS_BROWSER_MCP_REQUIRE_CACHE", raising=False)
    builtin_mcp = _load_builtin_mcp(monkeypatch)
    scheduled = []
    calls = []

    class Manager:
        async def connect_server(self, **kwargs):
            calls.append(kwargs)
            return True

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(builtin_mcp, "_BUILTIN_SERVERS", {})
    monkeypatch.setattr(builtin_mcp, "_find_npx", lambda: "/sandwich/bin/npx")
    monkeypatch.setattr(builtin_mcp, "_spawn_bg", scheduled.append)
    monkeypatch.setattr(builtin_mcp.asyncio, "sleep", no_sleep)

    async def run():
        await builtin_mcp.register_builtin_servers(Manager())
        assert len(scheduled) == 1
        await scheduled[0]

    asyncio.run(run())

    assert calls == [{
        "server_id": "builtin_browser",
        "name": "Built-in: Browser (Camofox)",
        "transport": "stdio",
        "command": "/sandwich/bin/npx",
        "args": ["-y", "camofox-mcp@latest"],
        "env": {"CAMOFOX_URL": "http://127.0.0.1:9377"},
    }]
    assert "@playwright/mcp" not in repr(calls)


def test_register_builtin_browser_disabled_schedules_no_npx(monkeypatch):
    monkeypatch.setenv("ODYSSEUS_BROWSER_MCP_PROVIDER", "disabled")
    builtin_mcp = _load_builtin_mcp(monkeypatch)
    scheduled = []

    monkeypatch.setattr(builtin_mcp, "_BUILTIN_SERVERS", {})
    monkeypatch.setattr(builtin_mcp, "_spawn_bg", scheduled.append)

    asyncio.run(builtin_mcp.register_builtin_servers(object()))

    assert scheduled == []


def test_browser_mcp_args_use_configured_browser_executable(monkeypatch):
    monkeypatch.setenv("ODYSSEUS_BROWSER_EXECUTABLE", "/usr/bin/chromium")
    builtin_mcp = _load_builtin_mcp(monkeypatch)

    args = builtin_mcp._browser_mcp_args(["-y", "@playwright/mcp@latest", "--headless"])

    assert "--executable-path" in args
    assert "/usr/bin/chromium" in args
    assert "--isolated" in args
    assert "--no-sandbox" in args


def test_browser_mcp_args_can_use_persistent_profile_when_requested(monkeypatch):
    monkeypatch.setenv("ODYSSEUS_BROWSER_EXECUTABLE", "/usr/bin/chromium")
    monkeypatch.setenv("ODYSSEUS_BROWSER_ISOLATED", "0")
    builtin_mcp = _load_builtin_mcp(monkeypatch)

    args = builtin_mcp._browser_mcp_args(["-y", "@playwright/mcp@latest", "--headless"])

    assert "--executable-path" in args
    assert "--isolated" not in args


def test_browser_mcp_args_respect_explicit_user_data_dir(monkeypatch):
    monkeypatch.setenv("ODYSSEUS_BROWSER_EXECUTABLE", "/usr/bin/chromium")
    builtin_mcp = _load_builtin_mcp(monkeypatch)

    args = builtin_mcp._browser_mcp_args([
        "-y", "@playwright/mcp@latest", "--headless", "--user-data-dir", "/tmp/profile",
    ])

    assert "--user-data-dir" in args
    assert "--isolated" not in args


def test_browser_mcp_args_can_keep_sandbox(monkeypatch):
    monkeypatch.setenv("ODYSSEUS_BROWSER_EXECUTABLE", "/usr/bin/chromium")
    monkeypatch.setenv("ODYSSEUS_BROWSER_NO_SANDBOX", "0")
    builtin_mcp = _load_builtin_mcp(monkeypatch)

    args = builtin_mcp._browser_mcp_args(["-y", "@playwright/mcp@latest", "--headless"])

    assert "--executable-path" in args
    assert "--no-sandbox" not in args


def test_npx_cache_check_detects_scoped_package_in_npx_cache(monkeypatch, tmp_path):
    builtin_mcp = _load_builtin_mcp(monkeypatch)
    package_json = (
        tmp_path
        / ".npm"
        / "_npx"
        / "9833c18b2d85bc59"
        / "node_modules"
        / "@playwright"
        / "mcp"
        / "package.json"
    )
    package_json.parent.mkdir(parents=True)
    package_json.write_text('{"name":"@playwright/mcp","version":"0.0.76"}', encoding="utf-8")

    async def unexpected_exec(*args, **kwargs):
        raise AssertionError("cache hit should not shell out to npx")

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("npm_config_cache", raising=False)
    monkeypatch.setattr(builtin_mcp.asyncio, "create_subprocess_exec", unexpected_exec)

    assert asyncio.run(
        builtin_mcp._is_npx_package_cached(
            "npx",
            "@playwright/mcp@latest",
            timeout_s=2,
        )
    ) is True


def test_npx_cache_check_falls_back_when_async_subprocess_is_unsupported(monkeypatch, tmp_path):
    builtin_mcp = _load_builtin_mcp(monkeypatch)

    async def unsupported_exec(*args, **kwargs):
        raise NotImplementedError("subprocess transport unavailable")

    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args, 0, stdout=b"1.2.3\n", stderr=b"")

    monkeypatch.setattr(builtin_mcp.asyncio, "create_subprocess_exec", unsupported_exec)
    monkeypatch.setattr(builtin_mcp.subprocess, "run", fake_run)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("npm_config_cache", raising=False)

    assert asyncio.run(
        builtin_mcp._is_npx_package_cached(
            "npx.cmd",
            "@playwright/mcp@latest",
            timeout_s=2,
        )
    ) is True
    assert captured["args"] == [
        "npx.cmd",
        "--no-install",
        "@playwright/mcp@latest",
        "--version",
    ]
    assert captured["kwargs"]["capture_output"] is True
    assert captured["kwargs"]["timeout"] == 2


def test_npx_cache_check_fallback_treats_timeout_as_cache_miss(monkeypatch, tmp_path):
    builtin_mcp = _load_builtin_mcp(monkeypatch)

    async def unsupported_exec(*args, **kwargs):
        raise NotImplementedError("subprocess transport unavailable")

    def fake_run(args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    monkeypatch.setattr(builtin_mcp.asyncio, "create_subprocess_exec", unsupported_exec)
    monkeypatch.setattr(builtin_mcp.subprocess, "run", fake_run)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("npm_config_cache", raising=False)

    assert asyncio.run(
        builtin_mcp._is_npx_package_cached(
            "npx.cmd",
            "@playwright/mcp@latest",
            timeout_s=2,
        )
    ) is False
