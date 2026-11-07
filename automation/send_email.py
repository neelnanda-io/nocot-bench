"""Send a plain-text email to Neel through Resend, without shell quoting.

    python -m automation.send_email --subject "NCRI candidates: 3 new" --body-file email.txt

From SENDER_EMAIL to the address in the env var named by config.json's
notify_email_env. Standard library only.
"""
import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

try:
    from dotenv import load_dotenv, find_dotenv
    load_dotenv(find_dotenv())
except ImportError:
    pass

CONFIG = json.loads((Path(__file__).resolve().parent / "config.json").read_text())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--subject", required=True)
    ap.add_argument("--body-file", required=True)
    a = ap.parse_args()
    key, sender = os.getenv("RESEND_API_KEY"), os.getenv("SENDER_EMAIL")
    to = os.getenv(CONFIG["notify_email_env"])
    if not (key and sender and to):
        sys.exit("RESEND_API_KEY, SENDER_EMAIL or the notify address is not set")
    payload = {"from": sender, "to": to, "subject": a.subject,
               "text": Path(a.body_file).read_text()}
    req = urllib.request.Request("https://api.resend.com/emails", data=json.dumps(payload).encode(),
                                 headers={"Authorization": f"Bearer {key}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        print("sent:", json.load(r).get("id"))


if __name__ == "__main__":
    main()
