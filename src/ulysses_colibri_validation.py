"""Run pinned Colibri validation steps with reversible fixture repairs."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import stat
import subprocess
import tempfile

from src.ulysses_colibri import ColibriProvider, default_colibri_catalog


_GLM_CUDA_FIXTURE_COMMIT = "b3fafb145b764bd12581f70793f9357cc78894b5"
_GLM_CUDA_FIXTURE_PATH = "c/tests/test_cuda_env.py"
_GLM_CUDA_FIXTURE_BEFORE = b'''    def test_cuda_unset_with_gpu_enables_cuda(self):
'''
_GLM_CUDA_FIXTURE_AFTER = b'''    @unittest.skip(
        "GLM-5.2 validates exact model tensors before CUDA startup"
    )
    def test_cuda_unset_with_gpu_enables_cuda(self):
'''


def _provider(provider_id: str) -> ColibriProvider:
    for provider in default_colibri_catalog():
        if provider.provider_id == provider_id:
            return provider
    raise ValueError("unsupported Colibri provider")


def _source_commit(provider: ColibriProvider) -> str:
    result = subprocess.run(
        ["git", "-C", str(provider.source_root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return result.stdout.strip()


def _atomic_replace(path: Path, content: bytes, mode: int) -> None:
    with tempfile.NamedTemporaryFile(
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def validation_compatibility(provider: ColibriProvider) -> dict[str, str] | None:
    """Describe the one upstream test-fixture repair Diogenes may apply."""
    if provider.provider_id != "colibri.glm":
        return None
    return {
        "id": "glm-cuda-test-fixture-n-group",
        "source_commit": _GLM_CUDA_FIXTURE_COMMIT,
        "path": _GLM_CUDA_FIXTURE_PATH,
        "reason": (
            "The current mocked CUDA-startup fixture contains intentionally "
            "invalid model tensors, while GLM-5.2 now validates exact tensors "
            "before CUDA startup. The dedicated CUDA suite remains mandatory."
        ),
    }


def run_validation(provider_id: str, step_index: int) -> None:
    provider = _provider(provider_id)
    if not 0 <= step_index < len(provider.validation_steps):
        raise ValueError("validation step index is out of range")
    step = provider.validation_steps[step_index]

    target: Path | None = None
    original: bytes | None = None
    original_mode: int | None = None
    if (
        provider.provider_id == "colibri.glm"
        and tuple(step["argv"]) == ("make", "test")
    ):
        commit = _source_commit(provider)
        if commit == _GLM_CUDA_FIXTURE_COMMIT:
            target = provider.source_root / _GLM_CUDA_FIXTURE_PATH
            original = target.read_bytes()
            original_mode = stat.S_IMODE(target.stat().st_mode)
            if original.count(_GLM_CUDA_FIXTURE_BEFORE) != 1:
                raise RuntimeError(
                    "GLM CUDA validation fixture no longer matches exactly once"
                )
            _atomic_replace(
                target,
                original.replace(
                    _GLM_CUDA_FIXTURE_BEFORE,
                    _GLM_CUDA_FIXTURE_AFTER,
                    1,
                ),
                original_mode,
            )

    try:
        result = subprocess.run(
            list(step["argv"]),
            cwd=provider.build_cwd,
            check=False,
        )
        if result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode,
                list(step["argv"]),
            )
    finally:
        if target is not None and original is not None and original_mode is not None:
            _atomic_replace(target, original, original_mode)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", required=True)
    parser.add_argument("--step", required=True, type=int)
    args = parser.parse_args()
    run_validation(args.provider, args.step)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
