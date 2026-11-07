"""Append one placed model to scores_all.csv and re-rank, by the file's own rule.

scores_all.csv (README "Every score we have measured") ranks every ranked row
by value, descending, ties keeping their existing order. A new row is inserted
after every row with a value >= its own, and every rank at or below that point
moves down by one. No other row changes.

    python -m automation.add_score --placement placement_<slug>.json \
        --provider OpenAI --arm plain --issue 12
    python -m automation.add_score --check     # self-test, writes nothing

Standard library only.
"""
import argparse
import csv
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCORES = ROOT / "scores_all.csv"


def read(path=SCORES):
    with open(path, newline="") as f:
        rd = csv.DictReader(f)
        return rd.fieldnames, list(rd)


def write(fields, rows, path=SCORES):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    Path(path).write_text(buf.getvalue())


def insert_ranked(rows, new, idx):
    """Give `new` its {idx}_rank and shift the ranks below it. Mutates rows."""
    if new.get(f"{idx}_ranked") != "True" or new.get(idx, "") == "":
        new[f"{idx}_rank"] = ""
        return
    v = float(new[idx])
    ranked = [r for r in rows if r.get(f"{idx}_ranked") == "True" and r.get(idx, "") != ""]
    rank = 1 + sum(1 for r in ranked if float(r[idx]) >= v)
    for r in ranked:
        if int(r[f"{idx}_rank"]) >= rank:
            r[f"{idx}_rank"] = str(int(r[f"{idx}_rank"]) + 1)
    new[f"{idx}_rank"] = str(rank)


def remove_ranked(rows, old, idx):
    """Inverse of insert_ranked, used only by --check."""
    if old.get(f"{idx}_rank", "") == "":
        return
    k = int(old[f"{idx}_rank"])
    for r in rows:
        if r is not old and r.get(f"{idx}_rank", "") != "" and int(r[f"{idx}_rank"]) > k:
            r[f"{idx}_rank"] = str(int(r[f"{idx}_rank"]) - 1)


def fmt(x):
    return "" if x is None else f"{x:.2f}"


def row_from_placement(fields, p, provider, arm, issue):
    mid = p["model"]
    nc, nk = p.get("ncri") or {}, p.get("ncki") or {}
    ci = nc.get("interval") or {}
    row = {f: "" for f in fields}
    row.update({
        "model_id": mid, "slug": mid.replace("/", "_"), "lab": mid.split("/")[0],
        "source": "placed_after_release",
        "ncri": fmt(nc.get("display")), "ncri_lo95": fmt(ci.get("display_lo")),
        "ncri_hi95": fmt(ci.get("display_hi")),
        "ncri_ranked": "True" if nc.get("ranked") else "False",
        "ncki": fmt(nk.get("ncki")),
        "ncki_ranked": "True" if nk.get("ncki") is not None else "False",
        "ncri_uses_filler": "False",
        "model_group": mid.split("/", 1)[1],
        "in_ncri_chart": "True" if nc.get("ranked") else "False",
        "in_ncki_chart": "True" if nk.get("ncki") is not None else "False",
        "notes": (f"Placed by the automated run for issue #{issue}: provider {provider}, arm {arm}, "
                  f"coverage {nc.get('coverage_domains')}/{nc.get('coverage_total')}. "
                  "No NCKI interval or filler sweep yet; ladder figures not yet redrawn."),
    })
    return row


def check():
    fields, rows = read()
    original = SCORES.read_text()
    placed = [r for r in rows if r["source"] == "placed_after_release"]
    for old in placed:
        trial = [dict(r) for r in rows]
        tgt = next(r for r in trial if r["model_id"] == old["model_id"] and r["ncri"] == old["ncri"])
        for idx in ("ncri", "ncki"):
            remove_ranked(trial, tgt, idx)
        pos = trial.index(tgt)
        trial.remove(tgt)
        new = dict(tgt)
        for idx in ("ncri", "ncki"):
            insert_ranked(trial, new, idx)
        trial.insert(pos, new)
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n")
        w.writeheader(); w.writerows(trial)
        if buf.getvalue() != original:
            sys.exit(f"FAIL: re-inserting {old['model_id']} does not reproduce scores_all.csv")
    print(f"PASS: removing and re-inserting each of {len(placed)} post-release rows "
          "reproduces scores_all.csv exactly")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--placement")
    ap.add_argument("--provider")
    ap.add_argument("--arm", default="plain")
    ap.add_argument("--issue")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.check:
        return check()
    if not (a.placement and a.provider and a.issue):
        ap.error("--placement, --provider and --issue are required")
    fields, rows = read()
    p = json.loads(Path(a.placement).read_text())
    if any(r["model_id"] == p["model"] for r in rows):
        sys.exit(f"{p['model']} is already in scores_all.csv; not adding a second row")
    new = row_from_placement(fields, p, a.provider, a.arm, a.issue)
    for idx in ("ncri", "ncki"):
        insert_ranked(rows, new, idx)
    rows.append(new)
    write(fields, rows)
    print(f"added {new['model_id']}: NCRI {new['ncri']} rank {new['ncri_rank'] or 'unranked'}, "
          f"NCKI {new['ncki']} rank {new['ncki_rank'] or 'unranked'}")


if __name__ == "__main__":
    main()
