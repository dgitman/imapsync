#!/usr/bin/env python3
"""Validate a Gmail RFC 822 scan and write aggregate duplicate counts."""

import argparse
import collections
import glob
import json
import re
from pathlib import Path

PARSER = argparse.ArgumentParser(description=__doc__)
PARSER.add_argument("--input", type=Path, required=True)
PARSER.add_argument("--output", type=Path)
ARGS = PARSER.parse_args()
ROOT = ARGS.input


def norm(value):
    value = (value or "").strip()
    if value.startswith("<") and value.endswith(">"):
        value = value[1:-1]
    return re.sub(r"\s+", "", value).casefold()


def load_account(account):
    rows = []
    validation = {}
    for folder in ("all_mail", "spam", "trash"):
        root = ROOT / account / folder
        expected = (root / "uids.txt").read_text().split()
        parts = sorted(glob.glob(str(root / "part_*.jsonl")))
        actual = []
        for part in parts:
            actual.extend(json.loads(line) for line in open(part))
        validation[folder] = {
            "expected": len(expected),
            "rows": len(actual),
            "uidsMatch": expected == [row.get("uid") for row in actual],
            "parts": len(parts),
        }
        rows.extend(actual)
    return rows, validation


personal, personal_validation = load_account("personal")
business, business_validation = load_account("business")


def account_stats(rows, validation):
    by_rfc = collections.defaultdict(list)
    for row in rows:
        key = norm(row.get("rfc822"))
        if key:
            by_rfc[key].append(row)
    repeated = {key: group for key, group in by_rfc.items() if len(group) > 1}
    active_extra = 0
    for group in repeated.values():
        active = [row for row in group if row.get("folder") != "trash"]
        if active:
            active_extra += max(0, len(active) - 1)
    return {
        "rows": len(rows),
        "uniqueGmailMessageIds": len({row.get("gmailMessageId") for row in rows if row.get("gmailMessageId")}),
        "uniqueGmailThreadIds": len({row.get("gmailThreadId") for row in rows if row.get("gmailThreadId")}),
        "errors": sum(bool(row.get("error")) for row in rows),
        "missingRfc822": sum(not bool(norm(row.get("rfc822"))) for row in rows),
        "uniqueRfc822": len(by_rfc),
        "repeatedRfc822Groups": len(repeated),
        "extraMessagesInRepeatedGroups": sum(len(group) - 1 for group in repeated.values()),
        "activeExtraMessagesIfKeepOneActive": active_extra,
        "folders": collections.Counter(row.get("folder") for row in rows),
        "validation": validation,
    }, by_rfc, repeated


personal_stats, personal_by_rfc, personal_repeated = account_stats(personal, personal_validation)
business_stats, business_by_rfc, business_repeated = account_stats(business, business_validation)
shared = set(personal_by_rfc) & set(business_by_rfc)

cross = {
    "sharedRfc822Values": len(shared),
    "personalMessages": sum(len(personal_by_rfc[key]) for key in shared),
    "businessMessages": sum(len(business_by_rfc[key]) for key in shared),
    "activePersonalMessages": sum(
        row.get("folder") != "trash" for key in shared for row in personal_by_rfc[key]
    ),
    "trashedPersonalMessages": sum(
        row.get("folder") == "trash" for key in shared for row in personal_by_rfc[key]
    ),
    "activeBusinessMessages": sum(
        row.get("folder") != "trash" for key in shared for row in business_by_rfc[key]
    ),
    "trashedBusinessMessages": sum(
        row.get("folder") == "trash" for key in shared for row in business_by_rfc[key]
    ),
    "headersWithActiveCopiesBothAccounts": sum(
        any(row.get("folder") != "trash" for row in personal_by_rfc[key])
        and any(row.get("folder") != "trash" for row in business_by_rfc[key])
        for key in shared
    ),
    "activeBusinessMessagesWithActivePersonalCopy": sum(
        sum(row.get("folder") != "trash" for row in business_by_rfc[key])
        for key in shared
        if any(row.get("folder") != "trash" for row in personal_by_rfc[key])
    ),
    "activeBusinessMessagesWithoutActivePersonalCopy": sum(
        sum(row.get("folder") != "trash" for row in business_by_rfc[key])
        for key in shared
        if not any(row.get("folder") != "trash" for row in personal_by_rfc[key])
    ),
    "repeatedBusinessGroupsAlsoCrossAccount": len(set(business_repeated) & shared),
    "repeatedBusinessGroupsBusinessOnly": len(set(business_repeated) - shared),
    "repeatedPersonalGroupsAlsoCrossAccount": len(set(personal_repeated) & shared),
    "repeatedPersonalGroupsPersonalOnly": len(set(personal_repeated) - shared),
}

strict_personal = {((row.get("rfc822") or "").strip().strip("<>")) for row in personal if row.get("rfc822")}
strict_business = {((row.get("rfc822") or "").strip().strip("<>")) for row in business if row.get("rfc822")}

summary = {
    "personal": personal_stats,
    "business": business_stats,
    "crossAccount": cross,
    "strictCaseSensitiveSharedRfc822Values": len(strict_personal & strict_business),
    "normalizedSharedRfc822Values": len(shared),
}

out = ARGS.output or ROOT / "summary.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(summary, indent=2, default=dict) + "\n")
print(json.dumps(summary, indent=2, default=dict))

validations = (personal_validation, business_validation)
if any(
    not folder["uidsMatch"]
    for validation in validations
    for folder in validation.values()
):
    raise SystemExit("Scan validation failed; do not build or apply a manifest.")
if personal_stats["errors"] or business_stats["errors"]:
    raise SystemExit("Scan contains fetch errors; do not build or apply a manifest.")
