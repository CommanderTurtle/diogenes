from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from src.ulysses_signal_update import (
    SignalUpdateError,
    _choose_asset,
    _extract_binary,
    _version_matches,
)


def test_choose_asset_accepts_only_official_native_release() -> None:
    version, url, size, digest = _choose_asset(
        {
            "tag_name": "v0.14.6",
            "assets": [
                {
                    "name": "signal-cli-0.14.6-Linux-native.tar.gz",
                    "browser_download_url": (
                        "https://github.com/AsamK/signal-cli/releases/download/"
                        "v0.14.6/signal-cli-0.14.6-Linux-native.tar.gz"
                    ),
                    "size": 105960000,
                    "digest": (
                        "sha256:"
                        "c78639c2d3c14cd004872a99ecf129bd7d7c26ee7d9844d50c2b0afdafefea68"
                    ),
                    "state": "uploaded",
                }
            ],
        }
    )
    assert version == "0.14.6"
    assert url.startswith("https://github.com/AsamK/signal-cli/")
    assert size == 105960000
    assert digest.startswith("sha256:")


def test_choose_asset_rejects_unofficial_download_host() -> None:
    with pytest.raises(SignalUpdateError, match="official GitHub"):
        _choose_asset(
            {
                "tag_name": "v0.14.6",
                "assets": [
                    {
                        "name": "signal-cli-0.14.6-Linux-native.tar.gz",
                        "browser_download_url": "https://example.com/signal-cli.tar.gz",
                        "size": 105960000,
                        "digest": "sha256:" + "a" * 64,
                        "state": "uploaded",
                    }
                ],
            }
        )


def test_choose_asset_requires_github_digest() -> None:
    with pytest.raises(SignalUpdateError, match="valid SHA-256"):
        _choose_asset(
            {
                "tag_name": "v0.14.6",
                "assets": [
                    {
                        "name": "signal-cli-0.14.6-Linux-native.tar.gz",
                        "browser_download_url": (
                            "https://github.com/AsamK/signal-cli/releases/download/"
                            "v0.14.6/signal-cli-0.14.6-Linux-native.tar.gz"
                        ),
                        "size": 105960000,
                        "digest": None,
                        "state": "uploaded",
                    }
                ],
            }
        )


def test_extract_binary_accepts_one_regular_signal_cli_file(tmp_path: Path) -> None:
    archive = tmp_path / "signal.tar.gz"
    payload = b"#!/bin/sh\nprintf 'signal-cli 0.14.6\\n'\n"
    with tarfile.open(archive, "w:gz") as bundle:
        member = tarfile.TarInfo("signal-cli")
        member.size = len(payload)
        member.mode = 0o755
        bundle.addfile(member, io.BytesIO(payload))
    destination = tmp_path / "signal-cli"

    _extract_binary(archive, destination)

    assert destination.read_bytes() == payload
    assert destination.stat().st_mode & 0o111


def test_extract_binary_rejects_symlinks(tmp_path: Path) -> None:
    archive = tmp_path / "signal.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        member = tarfile.TarInfo("signal-cli")
        member.type = tarfile.SYMTYPE
        member.linkname = "/bin/sh"
        bundle.addfile(member)

    with pytest.raises(SignalUpdateError, match="one signal-cli binary"):
        _extract_binary(archive, tmp_path / "signal-cli")


def test_version_match_is_an_exact_numeric_token() -> None:
    assert _version_matches("0.14.6", "signal-cli 0.14.6")
    assert not _version_matches("0.14.6", "signal-cli 10.14.60")
