"""Install the official signal-cli native release into the current user's PATH."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


RELEASE_API = "https://api.github.com/repos/AsamK/signal-cli/releases/latest"
MAX_ARCHIVE_BYTES = 250 * 1024 * 1024


class SignalUpdateError(RuntimeError):
    """Raised when an official signal-cli release cannot be safely installed."""


def _request_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Diogenes-signal-cli-updater",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read(MAX_ARCHIVE_BYTES).decode("utf-8"))
    if not isinstance(payload, dict):
        raise SignalUpdateError("release metadata is not an object")
    return payload


def _choose_asset(release: dict[str, Any]) -> tuple[str, str, int, str]:
    tag = str(release.get("tag_name") or "").lstrip("v")
    if not tag or any(character not in "0123456789." for character in tag):
        raise SignalUpdateError("latest release has an invalid version tag")
    expected = f"signal-cli-{tag}-Linux-native.tar.gz"
    for asset in release.get("assets") or []:
        if not isinstance(asset, dict) or asset.get("name") != expected:
            continue
        url = str(asset.get("browser_download_url") or "")
        parsed = urllib.parse.urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "github.com"
            or not parsed.path.startswith("/AsamK/signal-cli/releases/download/")
        ):
            raise SignalUpdateError("release asset URL is not an official GitHub download")
        try:
            size = int(asset.get("size"))
        except (TypeError, ValueError) as exc:
            raise SignalUpdateError("release asset size is invalid") from exc
        digest = str(asset.get("digest") or "")
        if not 0 < size <= MAX_ARCHIVE_BYTES:
            raise SignalUpdateError("release asset size is outside the allowed range")
        if (
            asset.get("state") != "uploaded"
            or not digest.startswith("sha256:")
            or len(digest) != len("sha256:") + 64
            or any(character not in "0123456789abcdef" for character in digest[7:])
        ):
            raise SignalUpdateError(
                "release asset is not uploaded with a valid SHA-256 digest"
            )
        return tag, url, size, digest
    raise SignalUpdateError(f"official native release asset {expected} was not found")


def _download(
    url: str,
    destination: Path,
    *,
    expected_size: int,
    expected_digest: str,
) -> None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Diogenes-signal-cli-updater"},
    )
    total = 0
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as stream:
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_ARCHIVE_BYTES:
                raise SignalUpdateError("release archive exceeds the size limit")
            digest.update(chunk)
            stream.write(chunk)
    if total != expected_size:
        raise SignalUpdateError(
            f"release archive size mismatch: expected {expected_size}, received {total}"
        )
    observed_digest = f"sha256:{digest.hexdigest()}"
    if observed_digest != expected_digest:
        raise SignalUpdateError("release archive SHA-256 digest mismatch")


def _extract_binary(archive: Path, destination: Path) -> None:
    with tarfile.open(archive, mode="r:gz") as bundle:
        candidates = [
            member
            for member in bundle.getmembers()
            if member.isfile() and Path(member.name).name == "signal-cli"
        ]
        if len(candidates) != 1:
            raise SignalUpdateError("release archive does not contain one signal-cli binary")
        member = candidates[0]
        source = bundle.extractfile(member)
        if source is None:
            raise SignalUpdateError("signal-cli binary could not be read from the archive")
        with destination.open("wb") as stream:
            shutil.copyfileobj(source, stream)
    destination.chmod(0o755)


def _version(binary: Path) -> str:
    try:
        result = subprocess.run(
            [str(binary), "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SignalUpdateError("downloaded signal-cli binary could not be executed") from exc
    value = ((result.stdout or "") + (result.stderr or "")).strip()
    if result.returncode or not value:
        raise SignalUpdateError("downloaded signal-cli binary failed its version check")
    return value


def _version_matches(expected: str, observed: str) -> bool:
    return bool(
        re.search(
            rf"(?<![0-9.]){re.escape(expected)}(?![0-9.])",
            observed,
        )
    )


def install_user(destination: Path | None = None) -> dict[str, str]:
    release = _request_json(RELEASE_API)
    version, url, size, digest = _choose_asset(release)
    requested = destination or Path.home() / ".local" / "bin" / "signal-cli"
    if requested.is_symlink():
        raise SignalUpdateError(
            "signal-cli destination is a symlink; reconcile it before updating"
        )
    target = requested.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ulysses-signal-cli-") as temporary:
        temporary_root = Path(temporary)
        archive = temporary_root / "signal-cli.tar.gz"
        candidate = temporary_root / "signal-cli"
        _download(
            url,
            archive,
            expected_size=size,
            expected_digest=digest,
        )
        _extract_binary(archive, candidate)
        observed = _version(candidate)
        if not _version_matches(version, observed):
            raise SignalUpdateError("downloaded signal-cli version does not match the release tag")
        staged = target.parent / f".{target.name}.ulysses-new"
        previous = target.parent / f".{target.name}.ulysses-previous"
        try:
            shutil.copyfile(candidate, staged)
            staged.chmod(0o755)
            if target.is_file():
                shutil.copy2(target, previous)
            os.replace(staged, target)
        finally:
            staged.unlink(missing_ok=True)
    return {
        "version": version,
        "observed": observed,
        "path": str(target),
        "source": url,
        "sha256": digest,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install the official signal-cli Linux native release for this user."
    )
    parser.add_argument(
        "--install-user",
        action="store_true",
        help="Install atomically to ~/.local/bin/signal-cli.",
    )
    arguments = parser.parse_args()
    if not arguments.install_user:
        parser.error("--install-user is required")
    try:
        print(json.dumps(install_user(), indent=2))
    except SignalUpdateError as exc:
        parser.exit(1, f"signal-cli update failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
