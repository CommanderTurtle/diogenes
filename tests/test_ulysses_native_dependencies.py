from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_liburing_development_headers_are_a_first_class_dependency():
    routes = (ROOT / "routes" / "shell_routes.py").read_text(encoding="utf-8")
    cookbook = (ROOT / "static" / "js" / "cookbook.js").read_text(encoding="utf-8")

    assert '"name": "liburing-dev"' in routes
    assert '"probe_path": "/usr/include/liburing.h"' in routes
    assert '"liburing-dev":    {"debian": ["liburing-dev"]' in routes
    assert '"liburing" if n == "liburing-dev"' in routes
    assert '"liburing-devel"' in routes
    assert '"liburing-dev"' in routes.partition("ALLOWED = {")[2].partition("}")[0]
    assert "new Set(['tmux', 'liburing-dev'])" in cookbook
    assert "System: ['tmux', 'docker', 'liburing-dev']" in cookbook
