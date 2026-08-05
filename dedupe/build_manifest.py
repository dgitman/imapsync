#!/usr/bin/env python3
"""Build reviewable Gmail message-ID targets from a validated RFC 822 scan."""

import argparse
import collections
import email.utils
import glob
import json
import re
from pathlib import Path

PARSER = argparse.ArgumentParser(description=__doc__)
PARSER.add_argument("--input", type=Path, required=True)
PARSER.add_argument("--output", type=Path, required=True)
ARGS = PARSER.parse_args()
ROOT = ARGS.input
OUT = ARGS.output
OUT.mkdir(parents=True, exist_ok=True)


def normalize(value):
    value = (value or "").strip().strip("<>")
    return re.sub(r"\s+", "", value).casefold()


def keep_key(row):
    folder_rank = 0 if row.get("folder") == "all_mail" else 1
    flagged_rank = 0 if "\\Flagged" in row.get("flags", []) else 1
    try:
        timestamp = email.utils.parsedate_to_datetime(row.get("internalDate", "")).timestamp()
    except Exception:
        timestamp = float("inf")
    return folder_rank, flagged_rank, timestamp, row.get("gmailMessageId", "")


rows = [
    json.loads(line)
    for path in glob.glob(str(ROOT / "*" / "*" / "part_*.jsonl"))
    for line in open(path)
]

summary_path = ROOT / "summary.json"
if not summary_path.exists():
    raise RuntimeError("Run analyze_scan.py successfully before building a manifest")
summary = json.loads(summary_path.read_text())
for account in ("personal", "business"):
    if summary[account]["errors"]:
        raise RuntimeError(f"The {account} scan contains fetch errors")
    if any(
        not folder["uidsMatch"]
        for folder in summary[account]["validation"].values()
    ):
        raise RuntimeError(f"The {account} scan is incomplete")
expected_rows = summary["personal"]["rows"] + summary["business"]["rows"]
if len(rows) != expected_rows:
    raise RuntimeError("Scan parts changed after analysis; rerun analyze_scan.py")

groups = collections.defaultdict(lambda: {"personal": [], "business": []})
for row in rows:
    key = normalize(row.get("rfc822"))
    if key:
        groups[key][row["account"]].append(row)

personal_targets = []
business_targets = []
kept = []
processed_groups = 0

for key, by_account in groups.items():
    active_personal = [r for r in by_account["personal"] if r.get("folder") != "trash"]
    active_business = [r for r in by_account["business"] if r.get("folder") != "trash"]
    if len(active_personal) + len(active_business) <= 1:
        continue
    processed_groups += 1
    if active_personal:
        survivor = min(active_personal, key=keep_key)
        kept.append(survivor["gmailMessageId"])
        personal_targets.extend(
            r["gmailMessageId"] for r in active_personal if r["gmailMessageId"] != survivor["gmailMessageId"]
        )
        business_targets.extend(r["gmailMessageId"] for r in active_business)
    else:
        survivor = min(active_business, key=keep_key)
        kept.append(survivor["gmailMessageId"])
        business_targets.extend(
            r["gmailMessageId"] for r in active_business if r["gmailMessageId"] != survivor["gmailMessageId"]
        )

if len(personal_targets) != len(set(personal_targets)):
    raise RuntimeError("Duplicate Personal target IDs were generated")
if len(business_targets) != len(set(business_targets)):
    raise RuntimeError("Duplicate Business target IDs were generated")

personal_targets.sort()
business_targets.sort()
kept.sort()

(OUT / "personal_targets.json").write_text(json.dumps(personal_targets) + "\n")
(OUT / "business_targets.json").write_text(json.dumps(business_targets) + "\n")
(OUT / "survivors.json").write_text(json.dumps(kept, indent=2) + "\n")
(OUT / "manifest.json").write_text(
    json.dumps(
        {
            "sourceRows": len(rows),
            "duplicateGroupsProcessed": processed_groups,
            "personalTargets": len(personal_targets),
            "businessTargets": len(business_targets),
            "totalTargets": len(personal_targets) + len(business_targets),
            "survivorsKept": len(kept),
            "rule": "Keep one active Personal copy when available; otherwise keep one active Business copy. Prefer All Mail and flagged copies.",
        },
        indent=2,
    )
    + "\n"
)
print((OUT / "manifest.json").read_text())
