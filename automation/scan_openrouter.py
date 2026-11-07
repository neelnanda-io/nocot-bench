"""Weekly scan of OpenRouter for models worth placing on NCRI / NCKI.

Deterministic half of the weekly task: it fetches the OpenRouter catalogue, drops
models already in models.csv / scores_all.csv or seen by an earlier scan, and
writes automation/candidates.json with prices, endpoints, a suggested provider pin
and an estimated buy cost. The agent running the weekly task then adds a
priority and a one-line "why" to each candidate and renders the page.

Standard library only, like the rest of the repo (python-dotenv is optional).

    python -m automation.scan_openrouter              # writes candidates.json
    python -m automation.scan_openrouter --since-days 60 --dry-run
"""
import argparse
import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:  # optional, matches the rest of the repo
    from dotenv import load_dotenv, find_dotenv
    load_dotenv(find_dotenv())
except ImportError:
    pass

ROOT = Path(__file__).resolve().parent.parent
AUTO = ROOT / "automation"
API = "https://openrouter.ai/api/v1"

# Measured on the clean-room buy of google/gemini-3-flash-preview (2026-09-18):
# 3,622 rows, 3.66M prompt tokens, 35k completion tokens, $2.70 billed including
# probes and re-buys. The estimate scales those token counts by a model's price,
# times a margin for probes, re-buys and any reasoning a leaky model emits.
BUY_PROMPT_TOKENS = 3.7e6
BUY_COMPLETION_TOKENS = 0.05e6
BUY_MARGIN = 1.5

# Provider guidance from ~/Code/CLAUDE.md (researched 2026-09-13).
GOOD_HOSTS = ["fireworks", "novita", "siliconflow", "cerebras"]
AVOID_HOSTS = ["targon", "chutes", "nebius", "digitalocean", "sail", "openinference",
               "io.net", "ionet", "mancer"]
FOUR_BIT = {"fp4", "int4"}
# Lab prefix -> the provider name its own endpoint uses on OpenRouter.
LAB_HOST = {"openai": "openai", "anthropic": "anthropic", "google": "google",
            "deepseek": "deepseek", "z-ai": "z.ai", "moonshotai": "moonshot",
            "qwen": "alibaba", "x-ai": "xai", "mistralai": "mistral",
            "meta-llama": "meta", "minimax": "minimax", "amazon": "amazon",
            "cohere": "cohere", "inception": "inception", "baidu": "baidu",
            "bytedance-seed": "seed", "stepfun-ai": "stepfun"}
CARRY_DAYS = 120  # an unmeasured candidate stays on the page this long

SKIP_PREFIXES = ("openrouter/", "~")
SKIP_SUFFIXES = (":free", ":extended", ":beta", ":thinking", ":online", ":nitro", ":floor", ":exacto")


def get(url, key):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001 - transport errors retried, then raised
            if attempt == 3:
                raise
            print(f"retry {url}: {e}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))


def known_ids():
    """Model ids already measured: models.csv plus scores_all.csv."""
    ids = set()
    with open(ROOT / "models.csv") as f:
        for row in csv.DictReader(f):
            ids.add(row["model_id"])
    p = ROOT / "scores_all.csv"   # the release plus every model placed since
    if p.exists():
        with open(p) as f:
            for row in csv.DictReader(f):
                ids.add(row["model_id"])
    return ids


def per_million(price):
    """Price per million tokens; None when unknown or negative (OpenRouter marks
    routers with variable pricing as -1)."""
    try:
        v = float(price)
    except (TypeError, ValueError):
        return None
    return round(v * 1e6, 4) if v >= 0 else None


def summarise_endpoints(model_id, key):
    author, _, slug = model_id.partition("/")
    url = f"{API}/models/{urllib.parse.quote(author)}/{urllib.parse.quote(slug)}/endpoints"
    try:
        eps = get(url, key)["data"]["endpoints"]
    except Exception as e:  # noqa: BLE001
        return [], f"endpoint list failed: {e}"
    out = []
    for e in eps:
        out.append({
            "provider": e.get("provider_name"),
            "tag": e.get("tag"),
            "quantization": e.get("quantization"),
            "in_per_m": per_million((e.get("pricing") or {}).get("prompt")),
            "out_per_m": per_million((e.get("pricing") or {}).get("completion")),
            "tools": "tools" in (e.get("supported_parameters") or []),
            "status": e.get("status"),
        })
    return out, None


def suggest_pin(model_id, endpoints):
    """Lab's own endpoint first, then a known-good host, then the cheapest non-4-bit
    endpoint not on the avoid list. Returns (provider_name, reason)."""
    lab = model_id.split("/")[0]
    usable = [e for e in endpoints
              if (e["quantization"] or "").lower() not in FOUR_BIT
              and not any(a in (e["provider"] or "").lower() for a in AVOID_HOSTS)]
    own = LAB_HOST.get(lab)
    for e in usable:
        if own and own in (e["provider"] or "").lower():
            return e["provider"], "lab's own endpoint"
    for host in GOOD_HOSTS:
        for e in usable:
            if host in (e["provider"] or "").lower():
                return e["provider"], "known-good host"
    usable.sort(key=lambda e: (e["in_per_m"] is None, e["in_per_m"] or 0))
    if usable:
        return usable[0]["provider"], "cheapest non-4-bit endpoint; benchmark the host first"
    return None, "no endpoint that is not 4-bit or on the avoid list"


def est_cost(in_m, out_m):
    if in_m is None or out_m is None:
        return None
    return round(BUY_MARGIN * (BUY_PROMPT_TOKENS * in_m + BUY_COMPLETION_TOKENS * out_m) / 1e6, 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since-days", type=int, default=None,
                    help="only models created in this window (default: since last scan, else 45)")
    ap.add_argument("--dry-run", action="store_true", help="print, write nothing")
    args = ap.parse_args()
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        sys.exit("OPENROUTER_API_KEY is not set")

    state_path = AUTO / "seen.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {"seen": {}}
    now = datetime.now(timezone.utc)
    if args.since_days is not None:
        since = now - timedelta(days=args.since_days)
    elif state.get("last_scan_utc"):
        since = datetime.fromisoformat(state["last_scan_utc"]) - timedelta(days=2)
    else:
        since = now - timedelta(days=45)

    known = known_ids()
    models = get(f"{API}/models", key)["data"]
    credits = get(f"{API}/credits", key)["data"]
    balance = round(credits["total_credits"] - credits["total_usage"], 2)

    cands, skipped = [], {"known": 0, "seen": 0, "old": 0, "variant": 0, "not_text": 0}
    for m in models:
        mid = m["id"]
        if mid.startswith(SKIP_PREFIXES) or mid.endswith(SKIP_SUFFIXES) or ":" in mid:
            skipped["variant"] += 1
            continue
        arch = m.get("architecture") or {}
        if "text" not in (arch.get("input_modalities") or ["text"]) or \
           "text" not in (arch.get("output_modalities") or ["text"]):
            skipped["not_text"] += 1
            continue
        if mid in known or m.get("canonical_slug") in known:
            skipped["known"] += 1
            continue
        if mid in state["seen"]:
            skipped["seen"] += 1
            continue
        created = datetime.fromtimestamp(m.get("created", 0), timezone.utc)
        if created < since:
            skipped["old"] += 1
            continue
        pricing = m.get("pricing") or {}
        if any(float(pricing.get(k) or 0) < 0 for k in ("prompt", "completion")):
            skipped["variant"] += 1  # a router with variable pricing, not a model
            continue
        endpoints, err = summarise_endpoints(mid, key)
        pin, pin_reason = suggest_pin(mid, endpoints)
        in_m, out_m = per_million(pricing.get("prompt")), per_million(pricing.get("completion"))
        params = m.get("supported_parameters") or []
        cands.append({
            "model_id": mid,
            "name": m.get("name"),
            "lab": mid.split("/")[0],
            "created": created.date().isoformat(),
            "context_length": m.get("context_length"),
            "in_per_m": in_m,
            "out_per_m": out_m,
            "est_buy_usd": est_cost(in_m, out_m),
            "tools": "tools" in params,
            "reasoning_param": "reasoning" in params,
            "pin": pin,
            "pin_reason": pin_reason,
            "endpoints": endpoints,
            "endpoint_error": err,
            "description": (m.get("description") or "")[:600],
            # filled in by the agent running the weekly task:
            "priority": None,
            "why": None,
        })

    for c in cands:
        c["first_seen"] = now.date().isoformat()
        c["new"] = True
    # Carry forward earlier candidates that are still unmeasured, with their
    # ratings, so a model stays on the page until it is placed or ages out.
    prev_path = AUTO / "candidates.json"
    prev = json.loads(prev_path.read_text())["candidates"] if prev_path.exists() else []
    fresh_ids = {c["model_id"] for c in cands}
    live_ids = {m["id"] for m in models}
    cutoff = (now - timedelta(days=CARRY_DAYS)).date().isoformat()
    carried = dropped = 0
    for c in prev:
        mid = c["model_id"]
        if mid in fresh_ids or mid in known or mid not in live_ids:
            dropped += 1
            continue
        if (c.get("first_seen") or c.get("created") or "") < cutoff:
            dropped += 1
            continue
        c.setdefault("first_seen", c.get("created"))
        c["new"] = c["first_seen"] == now.date().isoformat()  # same-day rerun keeps "new"
        cands.append(c)
        carried += 1
    print(f"carried forward {carried} earlier candidates, dropped {dropped} "
          f"(placed, gone from OpenRouter, or older than {CARRY_DAYS} days)")

    cands.sort(key=lambda c: c["created"], reverse=True)
    out = {
        "scanned_utc": now.isoformat(timespec="seconds"),
        "window_start_utc": since.isoformat(timespec="seconds"),
        "openrouter_balance_usd": balance,
        "n_catalogue": len(models),
        "skipped": skipped,
        "candidates": cands,
    }
    n_new = sum(1 for c in cands if c.get("new"))
    print(f"{n_new} new candidates since {since.date()} "
          f"(catalogue {len(models)}, skipped {skipped}); balance ${balance}")
    for c in cands:
        if not c.get("new"):
            continue
        print(f"  {c['created']}  {c['model_id']:<45} ${c['in_per_m']}/{c['out_per_m']} per M  "
              f"est ${c['est_buy_usd']}  pin={c['pin']}  tools={c['tools']}")
    if args.dry_run:
        return
    (AUTO / "candidates.json").write_text(json.dumps(out, indent=1) + "\n")
    for c in cands:
        state["seen"].setdefault(c["model_id"], c["created"])
    state["last_scan_utc"] = out["scanned_utc"]
    state_path.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
