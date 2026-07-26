from routes.cookbook_helpers import ServeRequest, _parse_serve_phase
from routes.cookbook_routes import _serve_supports_tools


def test_colibri_native_ready_line_marks_serve_ready() -> None:
    phase = _parse_serve_phase(
        "OpenAI-compatible API listening on http://127.0.0.1:8642/v1"
    )

    assert phase == {"phase": "ready", "status": "ready"}


def test_serve_request_carries_structured_colibri_identity() -> None:
    request = ServeRequest(
        repo_id="mastouri--GLM-5.2-colibri-int4-g64-with-int8-mtp",
        cmd="/home/example/Odysseus/colibri/c/coli serve",
        runtime_id="colibri.glm",
        runtime_settings={"profile": "rtx5090-high-ram"},
        served_model_id="glm-5.2-colibri",
    )

    assert request.runtime_id == "colibri.glm"
    assert request.runtime_settings == {"profile": "rtx5090-high-ram"}


def test_registered_colibri_capability_and_cli_fallback_are_preserved() -> None:
    assert _serve_supports_tools("colibri.glm", "") is True
    assert _serve_supports_tools("colibri.hy3", "") is True
    assert (
        _serve_supports_tools(
            "vllm",
            "vllm serve model --enable-auto-tool-choice --tool-call-parser qwen3",
        )
        is True
    )
    assert _serve_supports_tools("vllm", "vllm serve model") is None
