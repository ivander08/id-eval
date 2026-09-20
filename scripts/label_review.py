"""Review the rubric labels: emit a worksheet, apply the reviewer's pass.

`annotations/rubric_labels.jsonl` carries a 0.0/0.5/1.0 label per
(suite, case_id, subject) and a `rater` field that reads `draft:assistant` until a
human has been over the row. `emit` renders one markdown section per rating unit -
prompt, rubric note, the draft label with its rationale, and the stored response -
so the drafts can be reviewed without loading a model or re-running anything.
`apply` writes the reviewer's pass back: decided rows take the reviewer's `rater`,
undecided rows keep `draft:assistant`, and the provenance header survives
byte-for-byte.

The response is read from the stored artifact's pair rows, never from a live model:
`adapters.chat` pins no temperature, so a fresh generation would put different text
in front of the reviewer than the label describes.

Usage:
  python scripts/label_review.py emit
  python scripts/label_review.py emit --width 1000 --out annotations/review_worksheet.md
  python scripts/label_review.py apply --decisions annotations/review_decisions.jsonl
  python scripts/label_review.py apply --all-agree
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ideval.schema import TestCase, load_suite  # noqa: E402

DEFAULT_ARTIFACT = "results_calibration.json"
DEFAULT_LABELS = "annotations/rubric_labels.jsonl"
DEFAULT_WORKSHEET = "annotations/review_worksheet.md"
DEFAULT_REVIEWER = "review:ivander"
DRAFT_RATER = "draft:assistant"
VALID_LABELS = (0.0, 0.5, 1.0)
CANARY_PREFIX = "ADVERSARIAL"
NEWLINE = " \u23ce "  # literal marker for an embedded newline inside a worksheet line

Key = tuple[str, str, str]


def _key(row: dict) -> Key:
    return (row["suite"], row["case_id"], row["subject"])


def _data_row(line: str) -> dict | None:
    """The parsed row for a data line; None for blank lines and '#' comments."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    return json.loads(stripped)


def _read_raw(path: Path) -> str:
    """File text with line endings untouched, so a rewrite round-trips bytes."""
    return path.read_text(encoding="utf-8", newline="")


def _write_raw(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="")


def _replace_atomically(path: Path, text: str) -> None:
    """Write through a temp file in the same directory + os.replace, so a crash
    mid-write cannot truncate the label file."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _cases(suites: set[str]) -> dict[tuple[str, str], TestCase]:
    """(suite, case_id) -> case for every case in `suites`."""
    return {(suite, case.id): case
            for suite in sorted(suites)
            for case in load_suite(suite)}


def _stored_outputs(payload: dict) -> tuple[dict[Key, str], list[Key]]:
    """(suite, case_id, subject) -> stored output, from the artifact's pair rows,
    plus any key whose pair rows disagree on the output.

    The artifact generates one output per (suite, subject) and every judge scores
    it, so a key with two different outputs means the review would be of text no
    single label describes; that is reported rather than silently resolved."""
    outputs: dict[Key, str] = {}
    conflicts: list[Key] = []
    for row in payload["pairs"]:
        key = _key(row)
        if key not in outputs:
            outputs[key] = row["output"]
        elif outputs[key] != row["output"]:
            conflicts.append(key)
    return outputs, conflicts


def _escape(text: str) -> str:
    """One worksheet line per field: every newline becomes the literal marker."""
    return text.replace("\r\n", NEWLINE).replace("\n", NEWLINE).replace("\r", NEWLINE)


def emit(artifact: Path, labels: Path, out: Path, width: int = 6000) -> int:
    """Write the review worksheet. Returns an exit code.

    One section per rating unit in `labels`, grouped by suite, case and subject.
    A unit with no stored pair row in `artifact` is a subject failure - the label
    describes a response the artifact does not have - so it is skipped with a
    warning instead of being written with an empty response."""
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    stored, conflicts = _stored_outputs(payload)
    for key in conflicts:
        print(f"warning: {key} has more than one stored output; the first is shown")

    rows = [row for row in (_data_row(l) for l in _read_raw(labels).splitlines()) if row]
    cases: dict[tuple[str, str], TestCase] = {}
    for suite in sorted({row["suite"] for row in rows}):
        try:
            cases.update(_cases({suite}))
        except FileNotFoundError:
            print(f"warning: no suite file for {suite!r}: its units are skipped")

    sections: list[str] = []
    canary_cases: set[str] = set()
    truncated = canary_units = skipped = 0
    for row in sorted(rows, key=_key):
        key = _key(row)
        case = cases.get((row["suite"], row["case_id"]))
        if case is None:
            print(f"warning: {key}: no such case in suite {row['suite']!r}; skipped")
            skipped += 1
            continue
        output = stored.get(key)
        if output is None:
            print(f"warning: {key}: no stored output (subject failure); skipped")
            skipped += 1
            continue
        note = case.reference_note or ""
        canary = note.startswith(CANARY_PREFIX)
        canary_units += canary
        if canary:
            canary_cases.add(case.id)
        if len(output) > width:
            output = f"{output[:width]} \u2026 [TRUNCATED at {width} of {len(output)} chars]"
            truncated += 1
        sections.append(
            f"### {row['suite']} / {row['case_id']} \u2014 {row['subject']}\n"
            f"**prompt:** {_escape(case.input)}\n"
            f"**rubric note:** {_escape(note) if note else '-'}\n"
            f"**draft label: {float(row['label']):.1f}** \u2014 "
            f"{_escape(row['note']) if row.get('note') else '-'}\n"
            f"**output:** {_escape(output)}\n"
            f"**your label:** ______   **agree with draft?** ______\n"
        )

    head = (
        f"# Rubric label review\n\n"
        f"{len(sections)} rating units from `{labels.as_posix()}`, responses from `{artifact.as_posix()}`.\n"
        f"Each unit is one response: judge it against its suite's rubric, not against\n"
        f"the other subject's answer to the same prompt.\n\n"
        f"Record the pass in a JSONL file, one object per line, and apply it:\n\n"
        f"```\n"
        f'{{"suite": "cultural", "case_id": "cult-001", "subject": "kenari/qwen3-8-flash",\n'
        f' "label": 1.0, "note": "confirmed"}}\n'
        f"```\n\n"
        f"```\npython scripts/label_review.py apply --decisions annotations/review_decisions.jsonl\n```\n\n"
        f"`label` must be `0.0`, `0.5` or `1.0`. A decision that repeats the draft label\n"
        f"with no note (or the note `confirmed`) is a confirmation and keeps the draft's\n"
        f"rationale; any other decision replaces it. Units you do not decide keep\n"
        f"`rater: draft:assistant`, so a partial pass stays visible as one. Deciding every\n"
        f"unit at its draft label is the same as `apply --all-agree`.\n\n"
        f"The canary units ({', '.join(sorted(canary_cases))})\n"
        f"are adversarial by construction: a draft label above `0.0` there is a bug in the\n"
        f"draft, not a judgment call.\n\n"
    )
    out.write_text(head + "\n".join(sections), encoding="utf-8", newline="\n")
    print(f"worksheet: {len(sections)} units, {len(canary_cases)} canary cases "
          f"({canary_units} units), {truncated} truncated outputs, {skipped} skipped "
          f"-> {out}")
    return 0


def _read_decisions(path: Path, existing: dict[Key, dict]) -> dict[Key, dict]:
    """Validate a decisions file into {key: {label, note}}.

    Every decision must name a rating unit that exists in the label file (the pass
    replaces rows, it does not add them), a `label` that is exactly one of 0.0,
    0.5, 1.0, and a case that exists in the suite files. A duplicate key is an
    error: two decisions for one response are two claims about one label."""
    cases: dict[tuple[str, str], TestCase] = {}
    for suite in sorted({str(json.loads(l)["suite"])
                         for l in path.read_text(encoding="utf-8").splitlines()
                         if l.strip() and not l.startswith("#")}):
        cases.update(_cases({suite}))

    decisions: dict[Key, dict] = {}
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.strip().startswith("#"):
            continue
        row = json.loads(line)
        for field in ("suite", "case_id", "subject", "label"):
            if field not in row:
                raise ValueError(f"{path}:{n}: missing {field!r}")
        key = _key(row)
        if key in decisions:
            raise ValueError(f"{path}:{n}: duplicate decision for {key}")
        label = row["label"]
        if isinstance(label, bool) or not isinstance(label, (int, float)) or float(label) not in VALID_LABELS:
            raise ValueError(f"{path}:{n}: label {label!r} is not one of 0.0, 0.5, 1.0")
        if key not in existing:
            raise ValueError(f"{path}:{n}: {key} has no row in the label file")
        if (key[0], key[1]) not in cases:
            raise ValueError(f"{path}:{n}: suite {key[0]!r} has no case {key[1]!r}")
        note = row.get("note")
        if note is not None and not isinstance(note, str):
            raise ValueError(f"{path}:{n}: note {note!r} is not a string")
        decisions[key] = {"label": float(label), "note": note}
    return decisions


def apply(labels: Path, decisions: Path | None, out: Path | None = None,
          reviewer: str = DEFAULT_REVIEWER, all_agree: bool = False) -> int:
    """Write the reviewer's pass into the label file. Returns an exit code.

    A decision is a *confirmation* when its label equals the draft label and it
    carries no note (or the literal note "confirmed"): the row keeps the draft's
    rationale, because the reviewer is affirming it. Any other decision is a
    *change* and replaces the note with the decision's, which may be absent - a
    draft rationale that described a label the reviewer rejected is stale.

    `all_agree` confirms every row in the file, for a reviewer who read the
    worksheet and agreed with the drafts wholesale. Rows named by neither keep
    `rater: draft:assistant`. The file is written to `out` when given, else in place
    at `labels` through a temp file + os.replace."""
    if all_agree and decisions is not None:
        raise ValueError("all_agree and decisions are mutually exclusive")

    lines = _read_raw(labels).splitlines(keepends=True)
    parsed: list[tuple[int, dict]] = []
    for i, line in enumerate(lines):
        row = _data_row(line)
        if row is not None:
            parsed.append((i, row))
    existing = {_key(row): row for _, row in parsed}

    if all_agree:
        chosen = {key: {"label": float(row["label"]), "note": None}
                  for key, row in existing.items()}
    else:
        if decisions is None:
            raise ValueError("apply needs a decisions file or all_agree")
        chosen = _read_decisions(decisions, existing)

    confirmations = changes = 0
    for i, row in parsed:
        decision = chosen.get(_key(row))
        if decision is None:
            continue
        body = lines[i].rstrip("\r\n")
        eol = lines[i][len(body):]
        draft_label = float(row["label"])
        if decision["label"] == draft_label and decision["note"] in (None, "confirmed"):
            note = row.get("note")  # confirmed, not edited: the draft rationale stands
            confirmations += 1
        else:
            note = decision["note"]
            changes += 1
        rewritten = {"suite": row["suite"], "case_id": row["case_id"],
                     "subject": row["subject"], "label": decision["label"],
                     "rater": reviewer, "note": note}
        lines[i] = json.dumps(rewritten, ensure_ascii=False) + eol

    text = "".join(lines)
    if out is None:
        _replace_atomically(labels, text)
    else:
        _write_raw(out, text)
    target = out or labels

    remaining = sum(1 for i, _ in parsed
                    if json.loads(lines[i].strip()).get("rater") == DRAFT_RATER)
    reviewed = sum(1 for i, _ in parsed
                   if json.loads(lines[i].strip()).get("rater") == reviewer)
    print(f"applied {len(chosen)} decisions to {len(parsed)} rows "
          f"({confirmations} confirmations, {changes} changes)")
    print(f"rows: {reviewed} rater={reviewer}, {remaining} rater={DRAFT_RATER}")
    print(f"wrote {target}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)

    e = sub.add_parser("emit", help="write the review worksheet")
    e.add_argument("--artifact", default=DEFAULT_ARTIFACT,
                   help="stored calibration artifact holding the responses")
    e.add_argument("--labels", default=DEFAULT_LABELS, help="labels being reviewed")
    e.add_argument("--out", default=DEFAULT_WORKSHEET, help="worksheet to write")
    e.add_argument("--width", type=int, default=6000,
                   help="chars of each response to show before truncating (default 6000, "
                        "which shows every stored response whole except cmx-015)")

    a = sub.add_parser("apply", help="write the reviewer's pass into the labels")
    a.add_argument("--labels", default=DEFAULT_LABELS)
    a.add_argument("--decisions", help="reviewer's decisions JSONL")
    a.add_argument("--out", help="write here instead of in place")
    a.add_argument("--reviewer", default=DEFAULT_REVIEWER,
                   help=f"rater string for reviewed rows (default {DEFAULT_REVIEWER})")
    a.add_argument("--all-agree", action="store_true", dest="all_agree",
                   help="confirm every row at its draft label")

    args = ap.parse_args(argv)
    if args.command == "emit":
        return emit(Path(args.artifact), Path(args.labels), Path(args.out), args.width)
    if args.all_agree and args.decisions:
        a.error("--all-agree and --decisions are mutually exclusive")
    if not args.all_agree and not args.decisions:
        a.error("pass --decisions FILE or --all-agree")
    return apply(Path(args.labels), Path(args.decisions) if args.decisions else None,
                 Path(args.out) if args.out else None, args.reviewer, args.all_agree)


if __name__ == "__main__":
    raise SystemExit(main())
