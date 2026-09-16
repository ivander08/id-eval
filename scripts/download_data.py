"""Download raw eval data files into data/ (gitignored)."""

from __future__ import annotations

import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data"

FILES = {
    "IndoMMLU.csv": "https://huggingface.co/datasets/indolem/IndoMMLU/resolve/main/IndoMMLU.csv",
    "tydiqa-id-dev.jsonl": "https://huggingface.co/datasets/khalidalt/tydiqa-goldp/resolve/main/dev/indonesian-dev.jsonl",
}


def main() -> None:
    DATA.mkdir(exist_ok=True)
    for name, url in FILES.items():
        dest = DATA / name
        if dest.exists():
            print(f"skip {name} (exists)")
            continue
        print(f"downloading {name}...")
        urllib.request.urlretrieve(url, dest)  # noqa: S310 - pinned URLs
        print(f"  -> {dest.stat().st_size} bytes")


if __name__ == "__main__":
    main()
