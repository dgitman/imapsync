# RFC 822 duplicate audit

These tools locate messages that share a normalized RFC 822 `Message-ID`
header across the configured Personal and Business Gmail accounts.

The workflow has three deliberately separate stages:

1. `scan_headers.py` performs a read-only, checkpointed IMAP scan.
2. `analyze_scan.py` validates the checkpoints and writes aggregate counts.
3. `build_manifest.py` selects one survivor per active duplicate group and
   writes Gmail message-ID target lists for review.

None of these scripts trashes, labels, moves, or deletes messages. Applying a
manifest remains a separate, explicit Gmail operation.

## Credentials

The scanner reads `IMAPSYNC_PASSWORD1` and `IMAPSYNC_PASSWORD2` from the
process environment. If either value is absent, it safely reads only those two
names from the repository's 1Password-mounted `.env.imapsync` file.

Never create a plaintext replacement for that mount.

## Small validation scan

From the repository root:

```bash
python3 dedupe/scan_headers.py \
  --output dedupe-output/sample \
  --max-per-folder 500

python3 dedupe/analyze_scan.py \
  --input dedupe-output/sample

python3 dedupe/build_manifest.py \
  --input dedupe-output/sample \
  --output dedupe-output/sample-manifest
```

`--max-per-folder` limits each of All Mail, Spam, and Trash independently. It
is useful for testing the connection and output format, but a sample manifest
is not a complete-mailbox result.

## Complete mailbox scan

Omit the sample limit:

```bash
python3 dedupe/scan_headers.py --output dedupe-output/full
python3 dedupe/analyze_scan.py --input dedupe-output/full
python3 dedupe/build_manifest.py \
  --input dedupe-output/full \
  --output dedupe-output/full-manifest
```

The scanner snapshots folder UIDs and writes batches atomically. Rerunning the
same command resumes from valid completed parts instead of restarting the
mailbox. Use a new output directory when a fresh UID snapshot is required.

## Survivor rule

For each normalized RFC 822 Message-ID with more than one active copy:

- Keep a Personal copy when one exists; otherwise keep a Business copy.
- Within the selected account, prefer All Mail, then a flagged message, then
  the oldest internal date, and finally the lowest Gmail message ID.
- Put every other active copy in that account-specific target list.
- Ignore copies already in Trash when choosing targets.

The manifest directory contains `manifest.json`, account-specific target
lists, and `survivors.json`. These files contain private mailbox metadata and
must remain untracked.
