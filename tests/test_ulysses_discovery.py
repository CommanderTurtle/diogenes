import subprocess

from src.ulysses_discovery import (
    DOCKER_COMPOSE_COMMAND,
    SOCKET_COMMAND,
    SYSTEMD_USER_COMMAND,
    TMUX_COMMAND,
    collect_host_discovery,
    parse_compose_containers,
    parse_listening_sockets,
    parse_systemd_user_units,
    parse_tmux_sessions,
)


def test_compose_parser_preserves_project_roots_without_guessing():
    parsed = parse_compose_containers(
        "abc\tfirecrawl-api\tUp 2 hours\tfirecrawl\t"
        "/home/example/Hermes/firecrawl/firecrawl\t0.0.0.0:3002->3002/tcp\n"
        "def\torphan\tUp\t\trelative/path\t\n"
    )

    assert parsed[0].project == ""
    assert parsed[0].working_dir is None
    assert parsed[1].project == "firecrawl"
    assert str(parsed[1].working_dir) == "/home/example/Hermes/firecrawl/firecrawl"


def test_tmux_and_systemd_parsers_skip_malformed_rows():
    sessions = parse_tmux_sessions("vllm\t0\t1\t1720000000\nbad\trow\n")
    units = parse_systemd_user_units(
        "hermes-gateway.service loaded active running Hermes gateway\n"
    )

    assert sessions[0].name == "vllm"
    assert sessions[0].attached is False
    assert units[0].unit == "hermes-gateway.service"
    assert units[0].active == "active"


def test_socket_parser_handles_ipv4_ipv6_and_process_metadata():
    sockets = parse_listening_sockets(
        'tcp LISTEN 0 2048 0.0.0.0:7000 0.0.0.0:* users:(("python",pid=10,fd=7))\n'
        'tcp LISTEN 0 128 [::1]:9377 [::]:* users:(("bun",pid=22,fd=9))\n'
        "udp UNCONN 0 0 *:5353 *:*\n"
    )

    assert [(item.port, item.process_name) for item in sockets] == [
        (5353, ""),
        (7000, "python"),
        (9377, "bun"),
    ]
    assert sockets[1].process_ids == (10,)
    assert sockets[2].host == "::1"


def test_collector_uses_only_fixed_read_only_commands():
    outputs = {
        DOCKER_COMPOSE_COMMAND: "",
        TMUX_COMMAND: "vllm\t0\t1\t1720000000\n",
        SYSTEMD_USER_COMMAND: "",
        SOCKET_COMMAND: "tcp LISTEN 0 128 0.0.0.0:8000 0.0.0.0:*\n",
    }
    seen = []

    def runner(argv, timeout):
        seen.append((tuple(argv), timeout))
        return subprocess.CompletedProcess(argv, 0, outputs[tuple(argv)], "")

    snapshot = collect_host_discovery(timeout_seconds=9, runner=runner)

    assert [item[0] for item in seen] == [
        DOCKER_COMPOSE_COMMAND,
        TMUX_COMMAND,
        SYSTEMD_USER_COMMAND,
        SOCKET_COMMAND,
    ]
    assert all(timeout == 9 for _, timeout in seen)
    assert snapshot.tmux_sessions[0].name == "vllm"
    assert snapshot.listening_sockets[0].port == 8000
    assert snapshot.issues == ()


def test_collector_reports_failures_without_raising_or_retrying_commands():
    def runner(argv, _timeout):
        return subprocess.CompletedProcess(argv, 1, "", "not available")

    snapshot = collect_host_discovery(runner=runner)

    assert len(snapshot.issues) == 4
    assert snapshot.compose_containers == ()
    assert snapshot.listening_sockets == ()
