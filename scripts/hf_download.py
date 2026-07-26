#!/usr/bin/env python3
"""Download HuggingFace models with clean pipe-friendly progress output.

Usage:
    python3 scripts/hf_download.py <repo_id> --revision COMMIT
        --local-dir /models/owner--repo [--include "pattern"]
        [--workers 16] [--xet-workers 16] [--fast|--reliable]

Prints lines like:
    FILE model.safetensors [########------------] 42% 1.23/2.91GB 156.3MB/s
    DONE /path/to/cached/model
"""
import argparse
import importlib.util
import sys
import time
import os
import re
import threading
from pathlib import Path


_last_print = {}
_EXACT_REVISION_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)


def _environment_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


class PipeTqdm:
    """Minimal tqdm replacement that prints simple progress lines to stdout."""

    _lock = threading.RLock()

    def __init__(self, *args, **kwargs):
        self.iterable = args[0] if args else kwargs.get("iterable")
        self.total = kwargs.get("total", None)
        self.desc = kwargs.get("desc", "")
        self.unit = kwargs.get("unit", "it")
        self.n = kwargs.get("initial", 0) or 0
        self.start_t = time.time()
        self.disable = bool(kwargs.get("disable", False))
        self._closed = False

        if self.iterable is not None and self.total is None:
            try:
                self.total = len(self.iterable)
            except (TypeError, AttributeError):
                pass

    def __iter__(self):
        if self.iterable is None:
            return
        for item in self.iterable:
            yield item
            self.update(1)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __len__(self):
        return self.total or 0

    def update(self, n=1):
        self.n += n
        total = self.total or 0
        if self.disable or total == 0:
            return
        now = time.time()
        key = id(self)
        # Throttle to every 0.5s, always print on completion
        if now - _last_print.get(key, 0) < 0.5 and self.n < total:
            return
        _last_print[key] = now

        pct = min(100, int(100 * self.n / total))
        elapsed = now - self.start_t
        speed = self.n / elapsed if elapsed > 0 else 0
        desc = (self.desc or "").strip()

        # Format sizes
        if total >= 1024 ** 3:
            done_s = f"{self.n / (1024**3):.2f}"
            total_s = f"{total / (1024**3):.2f}GB"
            speed_s = f"{speed / (1024**2):.1f}MB/s"
        elif total >= 1024 ** 2:
            done_s = f"{self.n / (1024**2):.1f}"
            total_s = f"{total / (1024**2):.1f}MB"
            speed_s = f"{speed / (1024**2):.1f}MB/s"
        else:
            done_s = str(self.n)
            total_s = str(total)
            speed_s = f"{speed:.0f}/s"

        # ASCII progress bar
        bar_len = 20
        filled = min(bar_len, int(bar_len * self.n / total))
        bar = "#" * filled + "-" * (bar_len - filled)

        with self.get_lock():
            print(
                f"FILE {desc} [{bar}] {pct}% {done_s}/{total_s} {speed_s}",
                flush=True,
            )

    def set_description(self, desc=None, refresh=True):
        self.desc = desc or ""

    def set_description_str(self, desc=None, refresh=True):
        self.set_description(desc, refresh=refresh)

    def set_postfix(self, *args, **kwargs):
        pass

    def set_postfix_str(self, s="", refresh=True):
        pass

    def reset(self, total=None):
        self.n = 0
        if total is not None:
            self.total = total
        self.start_t = time.time()

    def refresh(self):
        pass

    def close(self):
        self._closed = True
        _last_print.pop(id(self), None)

    def clear(self):
        pass

    def display(self, msg=None, pos=None):
        pass

    @classmethod
    def get_lock(cls):
        # Match tqdm's lazy lock contract. tqdm.contrib.concurrent temporarily
        # swaps this class attribute while a thread/process map is active.
        if not hasattr(cls, "_lock"):
            cls._lock = threading.RLock()
        return cls._lock

    @classmethod
    def set_lock(cls, lock):
        cls._lock = lock

    @classmethod
    def write(cls, message, file=None, end="\n", nolock=False):
        stream = file or sys.stdout
        if nolock:
            print(message, file=stream, end=end, flush=True)
            return
        with cls.get_lock():
            print(message, file=stream, end=end, flush=True)

    @property
    def format_dict(self):
        return {"n": self.n, "total": self.total, "elapsed": time.time() - self.start_t}


def _patch_tqdm():
    """Replace tqdm everywhere with our pipe-friendly version."""
    import tqdm as tqdm_mod
    import tqdm.auto as tqdm_auto

    # Replace the main class
    tqdm_mod.tqdm = PipeTqdm
    tqdm_auto.tqdm = PipeTqdm

    # huggingface_hub uses tqdm.auto or its own utils.tqdm
    try:
        import huggingface_hub.utils
        huggingface_hub.utils.tqdm = PipeTqdm
        # Also patch the _tqdm module if it exists
        if hasattr(huggingface_hub.utils, "_tqdm"):
            huggingface_hub.utils._tqdm.tqdm = PipeTqdm
    except (ImportError, AttributeError):
        pass


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Download an exact Hugging Face snapshot into either the normal "
            "cache or a directly serveable model directory."
        )
    )
    parser.add_argument("repo_id", help="HuggingFace repo (e.g. meta-llama/Llama-3-8B)")
    parser.add_argument(
        "--revision",
        required=True,
        help="Exact 40-character commit revision.",
    )
    parser.add_argument(
        "--local-dir",
        required=True,
        help="Exact destination directory. Files are materialized directly here.",
    )
    parser.add_argument(
        "--include",
        action="append",
        help="File pattern to include; repeat for multiple patterns.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=_environment_int("HF_HUB_DOWNLOAD_MAX_WORKERS", 16),
        help="Concurrent Hugging Face file workers (default: 16).",
    )
    parser.add_argument(
        "--xet-workers",
        "--tokio-workers",
        dest="xet_workers",
        type=int,
        default=_environment_int("HF_XET_NUM_CONCURRENT_RANGE_GETS", 16),
        help=(
            "Concurrent Xet range requests per file (default: 16). "
            "--tokio-workers remains as a compatibility alias."
        ),
    )
    transfer = parser.add_mutually_exclusive_group()
    transfer.add_argument(
        "--fast",
        action="store_true",
        help="Require the high-performance Rust hf_xet backend.",
    )
    transfer.add_argument(
        "--reliable",
        action="store_true",
        help="Disable Xet and use the standard resumable HTTP downloader.",
    )
    args = parser.parse_args()
    if not 1 <= args.workers <= 64:
        parser.error("--workers must be between 1 and 64")
    if not 1 <= args.xet_workers <= 64:
        parser.error("--xet-workers must be between 1 and 64")
    args.revision = args.revision.strip().lower()
    if not _EXACT_REVISION_RE.fullmatch(args.revision):
        parser.error("--revision must be an exact 40-character commit")
    args.local_dir = os.path.abspath(os.path.expanduser(args.local_dir))
    if os.path.isfile(args.local_dir):
        parser.error("--local-dir points to a file")

    # Disable HF progress bars (we provide our own)
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "0"
    os.environ["HF_HUB_DOWNLOAD_MAX_WORKERS"] = str(args.workers)
    os.environ["HF_XET_NUM_CONCURRENT_RANGE_GETS"] = str(args.xet_workers)
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["HF_HUB_DISABLE_UPDATE_CHECK"] = "1"
    os.environ["DO_NOT_TRACK"] = "1"
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")
    os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "30")

    # The backend flag must be set before importing huggingface_hub.
    if args.reliable:
        os.environ["HF_HUB_DISABLE_XET"] = "1"
        os.environ["HF_XET_HIGH_PERFORMANCE"] = "0"
        transfer_name = "standard"
    else:
        xet_available = importlib.util.find_spec("hf_xet") is not None
        if not xet_available:
            if args.fast:
                print(
                    "ERROR --fast requires hf_xet; install "
                    "requirements/model-download.txt in the downloader venv",
                    file=sys.stderr,
                    flush=True,
                )
                return 2
            print("HINT install hf_xet for the fast transfer lane", flush=True)
            os.environ["HF_HUB_DISABLE_XET"] = "1"
            os.environ["HF_XET_HIGH_PERFORMANCE"] = "0"
            transfer_name = "standard"
        else:
            os.environ["HF_HUB_DISABLE_XET"] = "0"
            os.environ["HF_XET_HIGH_PERFORMANCE"] = "1"
            transfer_name = "xet-high-performance"

    _patch_tqdm()

    from huggingface_hub import snapshot_download

    kwargs = {
        "repo_id": args.repo_id,
        "revision": args.revision,
        "local_dir": args.local_dir,
        "max_workers": args.workers,
        "tqdm_class": PipeTqdm,
    }
    if args.include:
        kwargs["allow_patterns"] = args.include

    print(
        f"START repo={args.repo_id} revision={args.revision} "
        f"destination={args.local_dir} "
        f"workers={args.workers} transfer={transfer_name}",
        flush=True,
    )
    try:
        path = snapshot_download(**kwargs)
        expected = Path(args.local_dir).resolve()
        materialized = Path(path).resolve()
        if materialized != expected:
            print(
                f"ERROR downloader returned {materialized}, expected {expected}",
                file=sys.stderr,
                flush=True,
            )
            return 1
        print(f"DONE {materialized}", flush=True)
    except Exception as e:
        print(f"ERROR {e}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
