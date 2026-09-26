"""Offline dist-freshness gate: fails when `dist/` predates the source tree.

`dist/` is gitignored, so CI cannot notice a stale wheel and nothing else can
either. The observed failure was a wheel built before five shipped-module commits:
it imported fine, but a module the repo's own tests import was missing from it.

Every shipped file in the newest wheel is compared byte for byte against the tree
it was built from, in both directions, so a stale file and a file added after the
build both fail. That covers `src/ideval/**/*.py` and the six `suites/*.jsonl`,
which `[tool.hatch.build.targets.wheel.force-include]` maps to `ideval/suites/` —
a suite edited after the build ships stale eval data and is caught here too.
Exits non-zero on any failure.
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
MEMBER_RE = re.compile(r"^ideval/.*\.(?:py|jsonl)$")
VERSION_RE = re.compile(r'__version__\s*=\s*"([^"]+)"')


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _expected() -> dict[str, Path]:
    """{wheel member name: source path} for everything the wheel ships."""
    expected = {f"ideval/{p.relative_to(SRC / 'ideval').as_posix()}": p
                for p in (SRC / "ideval").rglob("*.py")}
    expected.update({f"ideval/suites/{p.name}": p for p in (ROOT / "suites").glob("*.jsonl")})
    return expected


def main() -> int:
    failures: list[str] = []

    wheels = sorted((ROOT / "dist").glob("*.whl"), key=lambda p: p.stat().st_mtime) \
        if (ROOT / "dist").is_dir() else []
    if not wheels:
        print("dist/: no wheel found (run python -m build)")
        return 1
    wheel = wheels[-1]

    init = SRC / "ideval" / "__init__.py"
    match = VERSION_RE.search(init.read_text(encoding="utf-8"))
    if match is None:
        print(f"{init}: no __version__ found")
        return 1
    version = match.group(1)
    if version not in wheel.name:
        failures.append(f"{wheel.name}: does not carry the source version {version}")

    expected = _expected()

    with zipfile.ZipFile(wheel) as zf:
        members = sorted(n for n in zf.namelist() if MEMBER_RE.match(n))
        if not members:
            failures.append(f"{wheel.name}: contains no shipped ideval/ modules or suites")
        for member in members:
            source = expected.get(member)
            if source is None:
                failures.append(f"{member}: in the wheel but not in the source tree "
                                f"(built from a different tree?)")
                continue
            src_bytes = source.read_bytes()
            wheel_bytes = zf.read(member)
            same = src_bytes == wheel_bytes
            print(f"{member} {_sha256(wheel_bytes)[:8]} {_sha256(src_bytes)[:8]} "
                  f"{'same' if same else 'STALE'}")
            if not same:
                failures.append(f"{member}: wheel bytes differ from {source.relative_to(ROOT)} "
                                f"(stale build)")

    for member in sorted(set(expected) - set(members)):
        failures.append(f"{member}: in the source tree but not in the wheel "
                        f"(added after the build)")

    if failures:
        print(f"\nFAIL ({len(failures)}):")
        for f in failures:
            print(f"  - {f}")
        return 1
    modules = sum(1 for m in members if m.endswith(".py"))
    suites = len(members) - modules
    print(f"\nOK: {wheel.name} matches {modules} modules and {suites} suites "
          f"at version {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
