#!/usr/bin/env python3
"""Post-deploy smoke: the ladder a judge actually walks.

Run this after every production deploy. On 2026-07-26 a Backblaze transaction
cap made every storage read fail; /healthz stayed green (it touches nothing)
while the homepage, the scoreboard and every decide were down. A health check
that cannot see the failure it is meant to catch is not a health check, so this
walks the paths a visitor uses instead.

    python tools/smoke.py [BASE_URL] [--spend]

Free by default: it exercises the homepage, the scoreboard, the budget precheck
and one EXACT-repeat decide (a reuse costs no generation and no embedding).
Pass --spend to also exercise a novel prompt, which really generates and really
costs money.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "https://reprise-murex.vercel.app"
EXACT_PROMPT = "a red bicycle leaning against a white brick wall, product photo"
TIMEOUT = 60


def call(url: str, body: dict[str, object] | None = None) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, headers={"content-type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read()
            try:
                return r.status, json.loads(raw)
            except json.JSONDecodeError:
                return r.status, raw.decode(errors="replace")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw.decode(errors="replace")
    except OSError as e:
        return 0, str(e)


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--spend"]
    spend = "--spend" in sys.argv[1:]
    base = (args[0] if args else BASE).rstrip("/")
    failures: list[str] = []

    def check(label: str, ok: bool, detail: object = "") -> None:
        print(f"{'PASS' if ok else 'FAIL'}  {label}  {str(detail)[:150]}")
        if not ok:
            failures.append(label)

    status, body = call(f"{base}/healthz")
    check("healthz", status == 200, body)

    status, page = call(f"{base}/")
    check("homepage renders", status == 200 and "Reprise" in str(page))
    # The cap outage rendered a page that loaded but could not show its numbers.
    # Catch that explicitly rather than treating a 200 as proof of health.
    check(
        "scoreboard is readable (not degraded)",
        "ledger unreadable" not in str(page),
        "homepage is showing the degraded scoreboard",
    )

    status, board = call(f"{base}/api/scoreboard")
    check("scoreboard endpoint", status == 200 and isinstance(board, dict), board)

    status, pre = call(f"{base}/api/precheck")
    ok = status == 200 and isinstance(pre, dict) and "generation_cap" in pre
    check("precheck (budgets readable)", ok, pre)
    if isinstance(pre, dict) and pre.get("generation_available") is False:
        check("generation budget has headroom", False, pre)

    status, decision = call(f"{base}/api/decide", {"prompt": EXACT_PROMPT})
    ok = status == 200 and isinstance(decision, dict) and decision.get("verdict") == "reuse"
    check("exact repeat returns REUSE", ok, decision if not ok else "")
    if isinstance(decision, dict):
        check("reuse carries a serve url", bool(decision.get("serve_url")))
        proof = decision.get("proof") or {}
        check(
            "reuse carries a proof receipt",
            bool(proof.get("manifest_hash") and proof.get("asset_key")),
            proof,
        )
        url = decision.get("serve_url")
        if isinstance(url, str) and url:
            status, _ = call(url)
            check("served asset fetches from B2", status == 200, status)

    if spend:
        novel = "a brass sextant on a navigation chart, studio photograph"
        status, gen = call(f"{base}/api/decide", {"prompt": novel})
        ok = status == 200 and isinstance(gen, dict) and gen.get("verdict") == "generate"
        check("novel prompt generates (real spend)", ok, gen if not ok else "")

    print()
    if failures:
        print(f"SMOKE FAILED: {len(failures)} check(s): {', '.join(failures)}")
        raise SystemExit(1)
    print("SMOKE PASSED")


if __name__ == "__main__":
    main()
