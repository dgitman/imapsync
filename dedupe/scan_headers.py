#!/usr/bin/env python3
"""Checkpoint Gmail RFC 822 headers through read-only IMAP operations."""

import argparse
import concurrent.futures
import email
import imaplib
import json
import os
import re
import ssl
import time
from pathlib import Path

ACCOUNTS = {
    "personal": ("davidmarkgitman@gmail.com", "IMAPSYNC_PASSWORD1"),
    "business": ("david@because.ventures", "IMAPSYNC_PASSWORD2"),
}
SPECIALS = {"\\All": "all_mail", "\\Junk": "spam", "\\Trash": "trash"}
BATCH_SIZE = 500
ALLOWED_ENV_NAMES = {env_name for _, env_name in ACCOUNTS.values()}


def emit(**data):
    print(json.dumps(data, separators=(",", ":")), flush=True)


def load_environment_file(path):
    """Read only the expected values, including from a 1Password FIFO."""
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\r\n")
            if not line or line.lstrip().startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            name = name.strip()
            if name in ALLOWED_ENV_NAMES and name not in os.environ:
                os.environ[name] = value


def decode_mailbox(raw):
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
    match = re.search(r' "((?:[^"\\]|\\.)*)"$', text)
    if match:
        return match.group(1).replace(r'\"', '"').replace(r"\\\\", "\\")
    return text.rsplit(" ", 1)[-1].strip('"')


def connect(user, password):
    context = ssl.create_default_context()
    client = imaplib.IMAP4_SSL("imap.gmail.com", 993, ssl_context=context, timeout=120)
    status, _ = client.login(user, password)
    if status != "OK":
        raise RuntimeError(f"Login failed for {user}")
    return client


def discover_special_folders(client):
    status, rows = client.list()
    if status != "OK":
        raise RuntimeError("IMAP LIST failed")
    found = {}
    for raw in rows or []:
        text = raw.decode("utf-8", "replace")
        for flag, slug in SPECIALS.items():
            if re.search(rf"(?i)(?:^|\s){re.escape(flag)}(?:\s|\))", text):
                found[slug] = decode_mailbox(raw)
    if "all_mail" not in found:
        for raw in rows or []:
            mailbox = decode_mailbox(raw)
            if mailbox.casefold().endswith("/all mail"):
                found["all_mail"] = mailbox
                break
    missing = sorted(set(SPECIALS.values()) - set(found))
    if missing:
        raise RuntimeError(f"Missing Gmail special folders: {missing}; found={found}")
    return found


def snapshot_uids(client, mailbox, path, max_per_folder):
    if path.exists():
        return path.read_text().split()
    status, _ = client.select(f'"{mailbox}"', readonly=True)
    if status != "OK":
        raise RuntimeError(f"Cannot select {mailbox}")
    status, data = client.uid("SEARCH", None, "ALL")
    if status != "OK":
        raise RuntimeError(f"UID SEARCH failed for {mailbox}")
    uids = (data[0] or b"").decode().split()
    if max_per_folder:
        uids = uids[:max_per_folder]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(uids) + ("\n" if uids else ""))
    os.replace(tmp, path)
    return uids


def parse_fetch(data, requested):
    rows = {}
    for item in data or []:
        if not isinstance(item, tuple) or len(item) != 2:
            continue
        meta, header = item
        meta_text = meta.decode("utf-8", "replace")
        uid_match = re.search(r"\bUID (\d+)", meta_text)
        gm_match = re.search(r"\bX-GM-MSGID (\d+)", meta_text)
        thread_match = re.search(r"\bX-GM-THRID (\d+)", meta_text)
        date_match = re.search(r'\bINTERNALDATE "([^"]+)"', meta_text)
        flags_match = re.search(r"\bFLAGS \(([^)]*)\)", meta_text)
        if not uid_match:
            continue
        uid = uid_match.group(1)
        message_id = ""
        try:
            parsed = email.message_from_bytes(header or b"")
            message_id = (parsed.get("Message-ID") or "").strip()
        except Exception:
            pass
        if message_id.startswith("<") and message_id.endswith(">"):
            message_id = message_id[1:-1]
        gm_decimal = gm_match.group(1) if gm_match else ""
        thread_decimal = thread_match.group(1) if thread_match else ""
        rows[uid] = {
            "uid": uid,
            "gmailMessageId": format(int(gm_decimal), "x") if gm_decimal else "",
            "gmailThreadId": format(int(thread_decimal), "x") if thread_decimal else "",
            "rfc822": message_id,
            "internalDate": date_match.group(1) if date_match else "",
            "flags": flags_match.group(1).split() if flags_match else [],
        }
    return [rows.get(uid, {"uid": uid, "error": "missing_fetch_response"}) for uid in requested]


def valid_part(path, expected_uids):
    if not path.exists():
        return False
    try:
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        return len(rows) == len(expected_uids) and [r.get("uid") for r in rows] == expected_uids
    except Exception:
        return False


def fetch_part(client, mailbox, uids):
    status, _ = client.select(f'"{mailbox}"', readonly=True)
    if status != "OK":
        raise RuntimeError(f"Cannot select {mailbox}")
    status, data = client.uid(
        "FETCH",
        ",".join(uids),
        "(UID X-GM-MSGID X-GM-THRID FLAGS INTERNALDATE BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])",
    )
    if status != "OK":
        raise RuntimeError(f"UID FETCH failed for {mailbox}")
    return parse_fetch(data, uids)


def scan_account(name, output, max_per_folder):
    user, env_name = ACCOUNTS[name]
    password = os.environ.get(env_name, "")
    if not password:
        raise RuntimeError(f"Missing {env_name}")
    client = connect(user, password)
    folders = discover_special_folders(client)
    emit(event="folders", account=name, folders=folders)
    totals = {}
    try:
        for slug in ("all_mail", "spam", "trash"):
            mailbox = folders[slug]
            root = output / name / slug
            uid_path = root / "uids.txt"
            uids = snapshot_uids(client, mailbox, uid_path, max_per_folder)
            totals[slug] = len(uids)
            emit(event="inventory", account=name, folder=slug, messages=len(uids))
            for part_no, start in enumerate(range(0, len(uids), BATCH_SIZE)):
                batch = uids[start : start + BATCH_SIZE]
                part_path = root / f"part_{part_no:05d}.jsonl"
                if not valid_part(part_path, batch):
                    last_error = None
                    for attempt in range(3):
                        try:
                            rows = fetch_part(client, mailbox, batch)
                            break
                        except Exception as exc:
                            last_error = exc
                            try:
                                client.logout()
                            except Exception:
                                pass
                            time.sleep(2 ** attempt)
                            client = connect(user, password)
                    else:
                        raise RuntimeError(f"{name}/{slug} part {part_no}: {last_error}")
                    root.mkdir(parents=True, exist_ok=True)
                    tmp = part_path.with_suffix(".jsonl.tmp")
                    with tmp.open("w") as handle:
                        for row in rows:
                            row.update({"account": name, "folder": slug})
                            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
                    os.replace(tmp, part_path)
                emit(event="progress", account=name, folder=slug, done=min(start + len(batch), len(uids)), total=len(uids))
    finally:
        try:
            client.logout()
        except Exception:
            pass
    return {"account": name, "folders": totals, "total": sum(totals.values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-per-folder", type=int, default=0)
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(__file__).resolve().parents[1] / ".env.imapsync",
    )
    args = parser.parse_args()
    if args.max_per_folder < 0:
        parser.error("--max-per-folder must be zero or greater")
    if any(not os.environ.get(env_name) for env_name in ALLOWED_ENV_NAMES):
        load_environment_file(args.env_file)
    missing = [name for name in sorted(ALLOWED_ENV_NAMES) if not os.environ.get(name)]
    if missing:
        parser.error("missing required credentials: " + ", ".join(missing))
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(scan_account, name, args.output, args.max_per_folder) for name in ACCOUNTS]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
    emit(event="complete", results=results)


if __name__ == "__main__":
    main()
