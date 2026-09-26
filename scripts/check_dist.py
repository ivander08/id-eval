"""Offline dist-freshness gate: fails when `dist/` predates the source tree.

`dist/` is gitignored, so CI cannot notice a stale wheel or sdist and nothing else
can either. The observed failure was a wheel built before five shipped-module
commits: it imported fine, but a module the repo's own tests import was missing
from it.

Both distributions in `dist/` are checked, in both directions:

- The wheel's shipped payload — `ideval/**/*.py` and the six `suites/*.jsonl`,
  which `[tool.hatch.build.targets.wheel.force-include]` maps to `ideval/suites/`
  — is compared byte for byte against the tree. A file edited after the build and
  a file added after the build both fail.
- The wheel's generated metadata is checked against the tree it was built from:
  `METADATA`'s body (everything after the first blank line) must equal `README.md`
  with `\\r\\n` folded to `\\n`, and `licenses/LICENSE` must equal `LICENSE`. Without
  this a README edit that skips a rebuild ships stale docs, since the long
  description is baked into the metadata.
- The sdist's members are compared byte for byte against the tree, and every file
  under the `[tool.hatch.build.targets.sdist] include` paths must be present, so a
  doc or script edited after the build fails. `PKG-INFO` is generated rather than
  copied, so it is compared against the wheel's `METADATA` instead — the two are
  the same document, and a stale sdist built beside a fresh wheel shows up here.

Exits non-zero on any failure.
"""

from __future__ import annotations

import hashlib
import re
import tarfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
MEMBER_RE = re.compile(r"^ideval/.*\.(?:py|jsonl)$")
VERSION_RE = re.compile(r'__version__\s*=\s*"([^"]+)"')
DIST_INFO = ".dist-info/"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _wheel_expected() -> dict[str, Path]:
    """{wheel member name: source path} for everything the wheel ships."""
    expected = {f"ideval/{p.relative_to(SRC / 'ideval').as_posix()}": p
                for p in (SRC / "ideval").rglob("*.py")}
    expected.update({f"ideval/suites/{p.name}": p for p in (ROOT / "suites").glob("*.jsonl")})
    return expected


def _sdist_expected() -> dict[str, Path]:
    """{sdist member name: source path} for the tree the sdist is built from."""
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    includes = config["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
    expected: dict[str, Path] = {}
    for entry in includes:
        path = ROOT / entry
        files = sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else [path]
        for f in files:
            if "__pycache__" in f.parts:
                continue
            expected[f.relative_to(ROOT).as_posix()] = f
    return expected


def _source_version() -> str | None:
    init = SRC / "ideval" / "__init__.py"
    match = VERSION_RE.search(init.read_text(encoding="utf-8"))
    return match.group(1) if match else None


def _newest(pattern: str) -> Path | None:
    dist = ROOT / "dist"
    if not dist.is_dir():
        return None
    found = sorted(dist.glob(pattern), key=lambda p: p.stat().st_mtime)
    return found[-1] if found else None


def _check_wheel(wheel: Path, version: str, failures: list[str]) -> str | None:
    """Compare the wheel against the tree. Returns its `METADATA` text, if any."""
    if version not in wheel.name:
        failures.append(f"{wheel.name}: does not carry the source version {version}")

    expected = _wheel_expected()
    metadata: str | None = None

    with zipfile.ZipFile(wheel) as zf:
        names = zf.namelist()
        members = sorted(n for n in names if MEMBER_RE.match(n))
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

        for name in sorted(n for n in names if DIST_INFO in n):
            if name.endswith("/METADATA"):
                metadata = zf.read(name).decode("utf-8")
            elif name.endswith("/licenses/LICENSE"):
                if zf.read(name) != (ROOT / "LICENSE").read_bytes():
                    failures.append(f"{name}: differs from LICENSE (stale build)")

    if metadata is None:
        failures.append(f"{wheel.name}: no {DIST_INFO}METADATA member")
    else:
        _, _, body = metadata.partition("\n\n")
        readme = (ROOT / "README.md").read_text(encoding="utf-8").replace("\r\n", "\n")
        same = body == readme
        print(f"METADATA long description {_sha256(body.encode())[:8]} "
              f"{_sha256(readme.encode())[:8]} {'same' if same else 'STALE'}")
        if not same:
            failures.append(f"{wheel.name}: METADATA's long description differs from "
                            f"README.md (a README edit shipped without a rebuild)")
    return metadata


def _check_sdist(sdist: Path, version: str, wheel_metadata: str | None,
                 failures: list[str]) -> None:
    """Compare the sdist against the tree, and its PKG-INFO against the wheel's."""
    if version not in sdist.name:
        failures.append(f"{sdist.name}: does not carry the source version {version}")

    expected = _sdist_expected()
    with tarfile.open(sdist) as tf:
        files = [m for m in tf.getmembers() if m.isfile()]
        if not files:
            failures.append(f"{sdist.name}: contains no files")
            return
        roots = {Path(m.name).parts[0] for m in files}
        if len(roots) != 1:
            failures.append(f"{sdist.name}: expected one top-level directory, found "
                            f"{sorted(roots)}")
            return
        members = {Path(*Path(m.name).parts[1:]).as_posix(): m for m in files}

        for name, member in sorted(members.items()):
            if name == "PKG-INFO":
                continue
            # `include` drives the "in the tree but not in the sdist" direction
            # below; hatch also always ships a few root files (.gitignore), so any
            # member that resolves to a real tree file is byte-compared rather than
            # rejected as foreign.
            source = expected.get(name)
            if source is None and (ROOT / name).is_file():
                source = ROOT / name
            if source is None:
                failures.append(f"{name}: in the sdist but not in the source tree "
                                f"(built from a different tree?)")
                continue
            src_bytes = source.read_bytes()
            sdist_bytes = tf.extractfile(member).read()
            same = src_bytes == sdist_bytes
            print(f"{name} {_sha256(sdist_bytes)[:8]} {_sha256(src_bytes)[:8]} "
                  f"{'same' if same else 'STALE'}")
            if not same:
                failures.append(f"{name}: sdist bytes differ from {source.relative_to(ROOT)} "
                                f"(stale build)")

        for name in sorted(set(expected) - set(members)):
            failures.append(f"{name}: in the sdist include list but not in the sdist "
                            f"(added after the build)")

        if "PKG-INFO" in members:
            pkg_info = tf.extractfile(members["PKG-INFO"]).read().decode("utf-8")
            if wheel_metadata is not None and pkg_info != wheel_metadata:
                failures.append(f"{sdist.name}: PKG-INFO differs from the wheel's METADATA "
                                f"(one of the two is stale)")
        else:
            failures.append(f"{sdist.name}: no PKG-INFO member")


def main() -> int:
    failures: list[str] = []

    version = _source_version()
    if version is None:
        print(f"{SRC / 'ideval' / '__init__.py'}: no __version__ found")
        return 1

    wheel = _newest("*.whl")
    sdist = _newest("*.tar.gz")
    if wheel is None:
        print("dist/: no wheel found (run python -m build)")
        return 1
    if sdist is None:
        print("dist/: no sdist found (run python -m build)")
        return 1

    metadata = _check_wheel(wheel, version, failures)
    _check_sdist(sdist, version, metadata, failures)

    if failures:
        print(f"\nFAIL ({len(failures)}):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"\nOK: {wheel.name} and {sdist.name} match the tree at version {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
