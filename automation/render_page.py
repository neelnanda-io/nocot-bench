"""Render automation/page.html (the NCRI Candidates artifact) from
automation/candidates.json, the placed-after-release rows of scores_all.csv and automation/open_requests.json.

    python -m automation.render_page

The page is static: all data is embedded, so a scheduled run can republish it
without the page needing any runtime capability.
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUTO = ROOT / "automation"
CONFIG = json.loads((AUTO / "config.json").read_text())


def main():
    cands = json.loads((AUTO / "candidates.json").read_text())
    with open(ROOT / "scores_all.csv") as f:
        placements = [r for r in csv.DictReader(f) if r["source"] == "placed_after_release"]
    reqs_path = AUTO / "open_requests.json"
    reqs = json.loads(reqs_path.read_text()) if reqs_path.exists() else []
    data = {**cands, "placements": placements, "open_requests": reqs,
            "floor_usd": CONFIG["floor_usd"],
            "repo": CONFIG["repo"]}
    for c in data["candidates"]:
        c.pop("endpoints", None)      # keep the page small
        c.pop("description", None)
    blob = json.dumps(data).replace("</", "<\\/")
    html = (AUTO / "page_template.html").read_text().replace("__DATA__", blob)
    (AUTO / "page.html").write_text(html)
    print(f"wrote automation/page.html: {len(data['candidates'])} candidates, "
          f"{len(placements)} placements, {len(reqs)} open requests")


if __name__ == "__main__":
    main()
