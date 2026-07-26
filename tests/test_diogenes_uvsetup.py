from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _commands(name: str) -> list[str]:
    return [
        line.strip()
        for line in (ROOT / name).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#") and not line.startswith("set ")
    ]


def test_uvsetup_is_the_canonical_inner_environment_flow():
    assert _commands("uvsetup.sh") == [
        "uv venv --python 3.13.12 --seed",
        "source .venv/bin/activate",
        "uv pip install -r requirements.txt",
        "uv run setup.py",
    ]


def test_startwithuv_is_the_canonical_web_launch():
    assert _commands("startwithuv.sh") == [
        "uv run python -m uvicorn app:app --host 0.0.0.0 --port 7000",
    ]
