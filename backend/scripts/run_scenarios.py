#!/usr/bin/env python
"""Run the demo script against the live stack and the local model.

`tests/test_scenarios.py` proves the deterministic floor. This proves the thing
the factory manager will actually see: every case in docs/04 asked through
`/api/ask`, understood by the local model, explained by it, validated — and
checked against the SQL oracle, case by case.

    make scenarios                          # everything (~15 min on CPU)
    make scenarios ARGS="--only S1,S3,R3"   # a few cases
    make scenarios ARGS="--group variant"   # the fifteen phrasings

It prints a table as it goes and exits non-zero if any case fails. With
`--markdown PATH` it also writes the report kept in docs/12.
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import json
import sys
import time
from datetime import date
from pathlib import Path

import asyncpg
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# A run takes many minutes; each line should appear when it happens, including
# when the output is redirected to a file.
print = functools.partial(print, flush=True)  # noqa: A001

from app.config import get_settings  # noqa: E402
from scenarios.matrix import BY_ID, CASES, evaluate, extra_tools, load_oracle  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--only", help="comma-separated case ids")
    parser.add_argument("--group", choices=["scenario", "demo", "variant", "reliability"])
    parser.add_argument("--markdown", type=Path, help="write a report to this file")
    parser.add_argument("--json", type=Path, help="write every run and verdict to this file")
    args = parser.parse_args()

    cases = [
        c
        for c in CASES
        if (not args.only or c.id in args.only.split(","))
        and (not args.group or c.group == args.group)
    ]

    async with httpx.AsyncClient(base_url=args.api, timeout=900) as http:
        health = (await http.get("/api/health")).json()
        today = date.fromisoformat(health["factory"]["today"])
        conn = await asyncpg.connect(get_settings().database_url_ro)
        try:
            oracle = await load_oracle(conn, today)
        finally:
            await conn.close()

        print(
            f"factory {health['factory']['timezone']} · today {today:%a %Y-%m-%d}"
            f"{' (pinned)' if health['factory'].get('pinned') else ''} · "
            f"understanding: {health['agent']['understanding']} · {len(cases)} cases\n"
        )
        header = ("case", "result", "status", "intent", "gen", "ret", "secs")
        print("{:<5} {:<6} {:<24} {:<22} {:<3} {:<3} {:>5}".format(*header))

        runs: dict[str, dict] = {}
        rows: list[dict] = []
        for case in cases:
            started = time.perf_counter()
            response = await http.post("/api/ask", json={"question": case.question})
            seconds = time.perf_counter() - started
            run = response.json()
            runs[case.id] = run

            base = runs.get(case.base) if case.base else None
            if case.base and base is None:
                base_response = await http.post(
                    "/api/ask", json={"question": BY_ID[case.base].question}
                )
                base = runs[case.base] = base_response.json()

            failures = evaluate(case, run, oracle, base)
            validation = run.get("validation") or {}
            row = {
                "id": case.id,
                "question": case.question,
                "passed": not failures,
                "failures": failures,
                "extra_tools": extra_tools(case, run),
                "status": run.get("status"),
                "intent": run.get("intent"),
                "generated": run.get("answer_is_generated"),
                "retries": validation.get("retries"),
                "seconds": round(seconds, 1),
                "answer": run.get("answer"),
            }
            rows.append(row)
            print(
                f"{case.id:<5} {'PASS' if row['passed'] else 'FAIL':<6} {row['status'] or '':<24} "
                f"{row['intent'] or '':<22} {'✓' if row['generated'] else '·':<3} "
                f"{row['retries'] if row['retries'] is not None else '':<3} {seconds:>5.1f}"
            )
            for failure in failures:
                print(f"      ✗ {failure}")
            if row["extra_tools"]:
                print(f"      + model added tools: {row['extra_tools']}")

        # S1 pass criterion 4: the same question twice gives the same number.
        if "S1" in runs:
            again = (await http.post("/api/ask", json={"question": BY_ID["S1"].question})).json()
            same = again.get("headline") == runs["S1"].get("headline")
            print(f"\nS1 asked again: {'identical headline' if same else 'DIFFERENT headline'}")
            if not same:
                rows.append({"id": "S1-repeat", "passed": False, "failures": ["headline changed"]})

    passed = sum(r["passed"] for r in rows)
    print(f"\n{passed}/{len(rows)} passed")

    if args.json:
        args.json.write_text(
            json.dumps(
                {"today": str(today), "health": health, "rows": rows, "runs": runs}, indent=2
            )
        )
    if args.markdown:
        args.markdown.write_text(_markdown(rows, health, today))
    return 0 if passed == len(rows) else 1


def _markdown(rows: list[dict], health: dict, today: date) -> str:
    lines = [
        f"Live run · {today:%a %Y-%m-%d} · factory {health['factory']['timezone']} · "
        f"understanding: {health['agent']['understanding']}",
        "",
        "| Case | Result | Status | Intent | Phrased by model | Rewrites | Seconds |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        if "status" not in r:
            continue
        lines.append(
            f"| {r['id']} | {'✅' if r['passed'] else '❌'} | `{r['status']}` | `{r['intent']}` | "
            f"{'yes' if r['generated'] else 'no'} | {r['retries'] or 0} | {r['seconds']} |"
        )
    failing = [r for r in rows if not r["passed"]]
    if failing:
        lines += ["", "Failures:", ""]
        for r in failing:
            lines += [f"- **{r['id']}**: " + "; ".join(r["failures"])]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
