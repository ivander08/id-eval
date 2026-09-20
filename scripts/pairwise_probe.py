"""Pairwise position-bias probe: does the judge's winner follow the order?

The `frame` column in the 36-row table measures the pointwise analogue — moving
the rubric around a single response. Position bias proper needs *two* responses
and a swapped presentation order, which is a different protocol and cannot be a
column of that table. This script runs that protocol on pairs built from the
stored artifact.

Pair construction: for a `factual` case, the API judge (`config['judges'][0]`)
passed one subject's output and failed another's, so the pair has a known better
response. That is a sanity anchor, not the measurement — the measurement is
whether swapping A/B changes the verdict.

Each pair is judged `--repeats` times per order, so framing alternates and each
order gets more than one draw. A verdict of "A" on the backward draw is resolved
to the response that appeared as B on the forward draw, so the two orders are
compared on content identity, not on the letter.

Usage:
  python scripts/pairwise_probe.py --artifact results_calibration.json --repeats 2
  python scripts/pairwise_probe.py --suite factual --limit 8
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ideval.adapters import make_client  # noqa: E402
from ideval.calibrate import pairwise_flip_rate  # noqa: E402
from ideval.runner import _judge_pair  # noqa: E402
from ideval.schema import load_suite  # noqa: E402

BETTER = "better"   # the response the API judge passed
WORSE = "worse"     # the response the API judge failed


def build_pairs(payload: dict, suite: str, limit: int | None) -> list[dict]:
    """One pair per case with a known better and worse response, from the artifact.

    The better/worse split is read off `judge_score` (the API judge's verdict),
    not off `gt`, because the anchor is "which response a competent judge prefers"
    — the same quantity the pairwise judge is asked for. `gt` is carried along so
    the pair's construction is auditable."""
    config = payload["config"]
    anchor = config["judges"][0]
    by_case: dict[str, dict[str, dict]] = {}
    for row in payload["pairs"]:
        if row["suite"] != suite or row["judge"] != anchor:
            continue
        by_case.setdefault(row["case_id"], {})[row["subject"]] = row

    cases = {c.id: c for c in load_suite(suite)}
    pairs = []
    for case_id, by_subject in sorted(by_case.items()):
        passed = [r for r in by_subject.values() if (r["judge_score"] or 0.0) >= 0.5]
        failed = [r for r in by_subject.values() if (r["judge_score"] or 0.0) < 0.5]
        if not passed or not failed:
            continue
        case = cases[case_id]
        pairs.append({"suite": suite, "case_id": case_id, "input": case.input,
                      "context": case.context, "expected": case.expected,
                      BETTER: passed[0]["output"], "better_subject": passed[0]["subject"],
                      "better_score": passed[0]["judge_score"],
                      WORSE: failed[0]["output"], "worse_subject": failed[0]["subject"],
                      "worse_score": failed[0]["judge_score"],
                      "gt": passed[0]["gt"]})
    if limit:
        pairs = pairs[:limit]
    return pairs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--artifact", default="results_calibration.json")
    ap.add_argument("--suite", default="factual")
    ap.add_argument("--limit", type=int, help="cap the number of pairs (cost control)")
    ap.add_argument("--repeats", type=int, default=2,
                    help="draws per order; the order is fixed, the framing alternates")
    ap.add_argument("--judge", action="append", help="judge model(s); repeatable")
    ap.add_argument("--out", default="results_pairwise.json")
    args = ap.parse_args()

    payload = json.loads(Path(args.artifact).read_text(encoding="utf-8"))
    judges = args.judge or payload["config"]["judges"]
    pairs = build_pairs(payload, args.suite, args.limit)
    if not pairs:
        print(f"no {args.suite} case has both a passing and a failing output from "
              f"{payload['config']['judges'][0]}; nothing to pair")
        return 1
    print(f"{len(pairs)} {args.suite} pair(s) from {args.artifact}, "
          f"{len(judges)} judge(s), {args.repeats} draw(s) per order")

    rows = []
    cases = {c.id: c for c in load_suite(args.suite)}
    for judge in judges:
        try:
            client, model_id = make_client(judge)
        except Exception as e:  # noqa: BLE001
            print(f"  {judge}: unreachable ({type(e).__name__}: {e})")
            continue
        orders: list[tuple[str, str]] = []
        detail = []
        for pair in pairs:
            case = cases[pair["case_id"]]
            forward = _draws(client, model_id, case, pair[BETTER], pair[WORSE], 0, args.repeats)
            backward = _draws(client, model_id, case, pair[BETTER], pair[WORSE], 1, args.repeats)
            # resolve to response identity: "A" forward is BETTER, "A" backward is WORSE
            f = _majority([_identity(d["winner"], forward=True) for d in forward])
            b = _majority([_identity(d["winner"], forward=False) for d in backward])
            draws = [d["winner"] for d in forward + backward]
            detail.append({**pair, "judge": judge,
                           "forward": [d["winner"] for d in forward],
                           "backward": [d["winner"] for d in backward],
                           "forward_winner": f, "backward_winner": b,
                           "unparsed": sum(1 for d in forward + backward if d["winner"] is None),
                           "flip": None if f is None or b is None else f != b})
            if f is not None and b is not None:
                orders.append((f, b))
        rate = pairwise_flip_rate(orders)
        better_share = (sum(1 for f, _ in orders if f == BETTER) / len(orders)) if orders else None
        print(f"\n{judge}")
        print(f"  pairs judged twice: {len(orders)}/{len(pairs)}"
              f"   draws: {args.repeats} forward + {args.repeats} backward")
        print(f"  dropped (no majority under either order): {len(pairs) - len(orders)}")
        print(f"  unparsed draws: {sum(d['unparsed'] for d in detail)}")
        print(f"  flip rate: {'-' if rate is None else format(rate, '.3f')}"
              f"   (share of pairs whose winner changed when A/B were swapped)")
        print(f"  picked the known-better response: "
              f"{'-' if better_share is None else format(better_share, '.3f')}")
        for d in detail:
            mark = " " if not d["flip"] else "X"
            print(f"   {mark} {d['case_id']:10s} fwd={str(d['forward_winner']):6s} "
                  f"bwd={str(d['backward_winner']):6s} "
                  f"raw_fwd={d['forward']} raw_bwd={d['backward']} unparsed={d['unparsed']}")
        rows.append({"judge": judge, "pairs": len(orders), "repeats": args.repeats,
                     "flip_rate": rate, "better_share": better_share,
                     "unparsed_draws": sum(d["unparsed"] for d in detail),
                     "detail": detail})

    Path(args.out).write_text(json.dumps(
        {"suite": args.suite, "artifact": args.artifact, "repeats": args.repeats,
         "pair_count": len(pairs), "judges": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"\nwrote {args.out}")
    return 0


def _draws(client, model_id: str, case, better: str, worse: str, order: int, repeats: int
           ) -> list[dict]:
    """`repeats` draws for one fixed presentation order, alternating the framing.

    `order` is passed straight through as `_judge_pair`'s `variant`, so the response
    presented as A never changes within a call; only `framing` alternates. Each draw
    keeps its raw text, so an unparseable verdict is diagnosable rather than just a
    hole in the rate."""
    out = []
    for d in range(repeats):
        verdict, raw = _judge_pair(client, model_id, case, better, worse,
                                   variant=order, framing=d)
        out.append({"winner": verdict.winner if verdict is not None else None,
                    "reason": verdict.reason if verdict is not None else "",
                    "raw": raw})
    return out


def _identity(winner: str, forward: bool) -> str | None:
    """Map a letter back to which response it names, in this presentation order."""
    if winner not in ("A", "B"):
        return None
    return (BETTER if winner == "A" else WORSE) if forward else (WORSE if winner == "A" else BETTER)


def _majority(resolved: list[str | None]) -> str | None:
    """The response named by most draws; ties and all-unparsed give None."""
    votes = [r for r in resolved if r is not None]
    if not votes:
        return None
    better = votes.count(BETTER)
    worse = votes.count(WORSE)
    if better == worse:
        return None
    return BETTER if better > worse else WORSE


if __name__ == "__main__":
    raise SystemExit(main())
