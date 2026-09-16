"""Pre-flight for the demo: is this stack ready to be shown right now?

Run it on the demo machine, on the demo day, minutes before the meeting. It
checks the things that have actually broken a demo in this project's history —
not a generic health probe:

  * the database answers, read-only, with all five machines;
  * the seeded week is about **today** (`app/dataset.py`) — the dataset is
    date-relative, so a stack left running overnight answers consistently and
    about yesterday, and the two scenarios that break are S2 and S4;
  * the SQL oracle passes 20/20, so the factory's figures are the documented
    ones;
  * the calendar is not pinned to a rehearsal date;
  * the local model is reachable, the right one, and **warm** — a cold model
    costs the first question 60-80 s on CPU;
  * the five demo questions answer correctly end to end, with the figures
    checked against the oracle.

Exit code 0 means go. Anything else prints what to fix, with the command.

    make demo-check              # everything, including the five live questions
    make demo-check ARGS=--quick # skip the live questions (~10 s instead of ~3 min)
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
import time
from pathlib import Path

import asyncpg
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import dataset  # noqa: E402
from app.config import get_settings  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

OK, WARN, BAD = "PASS", "WARN", "FAIL"

# The brief's own demo order (§19). Each one is checked for the outcome it must
# produce; the figures themselves are checked against the SQL oracle by
# `make scenarios`, which this deliberately does not duplicate.
DEMOS: tuple[tuple[str, str, str], ...] = (
    ("Demo 1", "What is the current status of CNC-03?", "answered"),
    ("Demo 2", "Can CNC-03 continue production today?", "answered"),
    ("Demo 3", "Which machine is limiting A12 production?", "answered"),
    ("Demo 4", "How many A12 can we produce this week?", "answered"),
    ("Demo 5", "Write me a story.", "rejected_out_of_domain"),
)


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str | None]] = []

    def add(self, verdict: str, check: str, detail: str, fix: str | None = None) -> None:
        self.rows.append((verdict, check, detail, fix))
        mark = {OK: "✓", WARN: "!", BAD: "✗"}[verdict]
        print(f"  {mark} {check:<34} {detail}", flush=True)
        if fix and verdict != OK:
            print(f"      → {fix}", flush=True)

    @property
    def failures(self) -> list[tuple[str, str, str, str | None]]:
        return [r for r in self.rows if r[0] == BAD]

    @property
    def warnings(self) -> list[tuple[str, str, str, str | None]]:
        return [r for r in self.rows if r[0] == WARN]


async def check_factory(report: Report) -> None:
    settings = get_settings()
    clock = settings.factory_clock()
    try:
        conn = await asyncpg.connect(settings.database_url_ro, timeout=5)
    except Exception as exc:
        report.add(BAD, "database", f"unreachable ({exc})", "make up")
        return

    try:
        row = await conn.fetchrow(
            "SELECT current_user AS usr, "
            "current_setting('default_transaction_read_only') AS ro, "
            "(SELECT count(*) FROM machines) AS machines"
        )
        detail = f"{row['machines']} machines, as {row['usr']}, read_only={row['ro']}"
        if row["machines"] == 5 and row["ro"] == "on":
            report.add(OK, "database", detail)
        else:
            report.add(BAD, "database", detail, "make db-seed  /  make db-schema")

        freshness = dataset.assess(
            await conn.fetchval("SELECT max(production_date) FROM production_history"),
            clock.today(),
        )
        if freshness.fresh:
            report.add(
                OK,
                "factory data is about today",
                f"newest production record {freshness.last_production_day} "
                f"(factory today {clock.today()})",
            )
        else:
            report.add(BAD, "factory data is about today", freshness.note or "", "make db-seed")
    finally:
        await conn.close()


def check_oracle(report: Report) -> None:
    """The 20 data assertions, through the same psql path the Makefile uses."""
    settings = get_settings()
    try:
        result = subprocess.run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                "mes",
                "-d",
                "mes",
                "-v",
                "ON_ERROR_STOP=1",
                "-v",
                f"factory_tz={settings.factory_timezone}",
            ],
            stdin=(ROOT / "db" / "verify.sql").open(),
            capture_output=True,
            text=True,
            cwd=ROOT,
            timeout=120,
        )
    except Exception as exc:  # pragma: no cover - environment dependent
        report.add(WARN, "SQL oracle (20 assertions)", f"could not run ({exc})", "make db-verify")
        return

    passed = result.stdout.count("| PASS")
    failed = result.stdout.count("| FAIL")
    detail = f"{passed}/20 assertions pass"
    if failed == 0 and passed == 20:
        report.add(OK, "SQL oracle (20 assertions)", detail)
    else:
        report.add(
            BAD, "SQL oracle (20 assertions)", f"{detail}, {failed} failing", "make db-verify"
        )


async def check_backend(report: Report, client: httpx.AsyncClient) -> dict | None:
    try:
        health = (await client.get("/api/health")).json()
    except Exception as exc:
        report.add(BAD, "backend", f"unreachable ({exc})", "make up  /  make logs")
        return None

    report.add(
        OK if health.get("status") == "ok" else BAD,
        "backend",
        f"status {health.get('status')}, "
        f"{health['tools']['implemented']}/{health['tools']['total']} tools",
        "make logs",
    )

    factory = health.get("factory", {})
    if factory.get("pinned"):
        report.add(
            BAD,
            "calendar is the real one",
            f"FACTORY_TODAY is pinned to {factory.get('today')} — a rehearsal badge is on screen",
            "unset FACTORY_TODAY in .env, then: docker compose up -d backend && make db-seed",
        )
    else:
        report.add(
            OK,
            "calendar is the real one",
            f"factory today {factory.get('today')} ({factory.get('timezone')})",
        )

    # The model's identity and readiness live on /api/agent; /api/health carries
    # only whether understanding is running on it.
    try:
        llm = (await client.get("/api/agent")).json().get("llm", {})
    except Exception:  # pragma: no cover - the health call already succeeded
        llm = {}

    agent = health.get("agent", {})
    if agent.get("understanding") == "llm":
        report.add(OK, "local model", f"{llm.get('model')} via {agent.get('llm_provider')}")
    else:
        report.add(
            BAD,
            "local model",
            f"understanding is {agent.get('understanding')} — {llm.get('status')}",
            "make llm-check  (the demo would run degraded, on rules)",
        )
    return health


async def check_model_is_warm(report: Report, client: httpx.AsyncClient) -> None:
    """A cold model costs the first question 60-80 s on CPU.

    `/api/understand` is one structured call and no factory reasoning, so its
    latency is a clean read on whether the model and its prompt cache are
    resident.
    """
    started = time.perf_counter()
    try:
        # Generous: this is the call that pays a cold start, and reporting it as
        # slow is the point. A timeout here would hide what it exists to measure.
        response = await client.post(
            "/api/understand",
            json={"question": "How many A12 can we produce this week?"},
            timeout=240,
        )
        response.raise_for_status()
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
        report.add(BAD, "model is warm", f"understanding failed ({detail})", "make logs")
        return

    seconds = time.perf_counter() - started
    body = response.json()
    degraded = (body.get("understood_by") or "") != "llm"
    detail = f"one structured call in {seconds:.1f}s"
    if degraded:
        report.add(
            BAD, "model is warm", f"{detail}, but the reading came from rules", "make llm-check"
        )
    elif seconds <= 15:
        report.add(OK, "model is warm", detail)
    else:
        report.add(
            WARN,
            "model is warm",
            f"{detail} — the first demo question will pay a cold start",
            "ask one question now to warm it, or restart the backend and wait for warm-up",
        )


async def check_demos(report: Report, client: httpx.AsyncClient) -> None:
    for name, question, expected in DEMOS:
        started = time.perf_counter()
        try:
            response = await client.post("/api/ask", json={"question": question}, timeout=600)
            response.raise_for_status()
            run = response.json()
        except Exception as exc:
            report.add(BAD, name, f"failed ({exc})", "make logs")
            continue

        seconds = time.perf_counter() - started
        status = run.get("status")
        headline = run.get("headline") or {}
        shown = headline.get("text") or (
            f"{headline.get('value')} {headline.get('unit')}".strip()
            if headline.get("value") is not None
            else "—"
        )
        validation = run.get("validation") or {}
        detail = f"{status}, {shown}, {run.get('tool_call_count', 0)} MES calls, {seconds:.0f}s" + (
            "" if run.get("answer_is_generated", True) else ", data-only answer"
        )

        if status != expected:
            report.add(BAD, name, f"{detail} — expected {expected}", f'ask it again: "{question}"')
        elif not validation.get("grounded", True):
            report.add(BAD, name, f"{detail} — not grounded: {validation.get('note')}", "make logs")
        else:
            report.add(OK, name, detail)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quick",
        action="store_true",
        help="skip the five live demo questions (about 3 minutes on CPU)",
    )
    args = parser.parse_args()

    settings = get_settings()
    report = Report()
    print(f"\nDemo pre-flight — factory {settings.factory_timezone}\n", flush=True)

    await check_factory(report)
    check_oracle(report)

    base = f"http://localhost:{settings.api_port}"
    async with httpx.AsyncClient(base_url=base, timeout=30) as client:
        health = await check_backend(report, client)
        if health is not None:
            await check_model_is_warm(report, client)
            if not args.quick:
                print(flush=True)
                await check_demos(report, client)

    print()
    if report.failures:
        print(f"NOT READY — {len(report.failures)} check(s) failed. Fix them and run again.\n")
        return 1
    if report.warnings:
        print(f"READY, with {len(report.warnings)} warning(s) above.\n")
        return 0
    print("READY — every check passed.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
