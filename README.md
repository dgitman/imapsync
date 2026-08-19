# IMAP mailbox tools

Private tools for copying and auditing mail in the Gmail accounts configured in
this repository. The migration wrappers use
[imapsync](https://imapsync.lamiral.info/); the RFC 822 dedupe tools use
Python's standard `imaplib` module and local JSON processing.

Passwords are supplied at runtime by 1Password Environments and are never
stored in the repository.

## Install

On macOS, install imapsync with Homebrew:

```bash
brew install imapsync
imapsync --version
```

The migration scripts require Bash. The dedupe tools require Python 3 and no
third-party packages. Both workflows use the 1Password desktop app with
Developer Environments enabled.

## Repository contents

- `imapsync-dgitman.sh` - migrates the configured David Gitman Gmail folder.
- `imapsync-bklein.sh` - migrates the configured Barry Klein Gmail account.
- `dedupe/` - scans RFC 822 Message-ID headers, validates scan results, and
  builds a reviewable cleanup manifest.

## Configure 1Password

Each migration script expects two concealed Environment variables:

- `IMAPSYNC_PASSWORD1` - source Gmail password or app password
- `IMAPSYNC_PASSWORD2` - destination Gmail password or app password

For normal interactive use, inject the matching 1Password Environment at runtime:

```bash
op run --env-file=.env.imapsync -- bash imapsync-dgitman.sh --justlogin --nolog
```

The scripts prefer inherited environment variables, so no mounted file is
required on additional machines. Existing `.env.imapsync` and `.env.bklein`
mounts remain supported as fallbacks for unattended or legacy workflows. They
are ignored by Git; do not replace them with plaintext credential files.
A 1Password Environment mount may appear as a FIFO, which the scripts read
safely without sourcing arbitrary shell content.

## Verify the connections

Test both IMAP logins without transferring messages:

```bash
op run --env-file=.env.imapsync -- bash imapsync-dgitman.sh --justlogin --nolog
bash imapsync-bklein.sh --justlogin --nolog
```

Run a dry test before a migration:

```bash
bash imapsync-dgitman.sh --dry --nolog
bash imapsync-bklein.sh --dry --nolog
```

Any arguments after the script name are passed through to imapsync. For
example, this limits a dry test to three messages:

```bash
bash imapsync-dgitman.sh --dry --maxmessages 3 --nolog
```

## Run a migration

The default behavior copies messages and leaves the source messages in place:

```bash
bash imapsync-dgitman.sh
bash imapsync-bklein.sh
```

`imapsync-dgitman.sh` copies only the Gmail folder named `Because Ventures`.
`imapsync-bklein.sh` uses imapsync's standard Gmail folder mapping.

Logs written under `LOG_imapsync/` are excluded from Git because they can
contain private mailbox metadata.

## Source deletion

Source deletion is disabled by default. To deliberately enable imapsync's
`--delete1` behavior, use the wrapper's explicit opt-in:

```bash
bash imapsync-dgitman.sh --delete-source
```

The scripts reject a directly supplied `--delete1` option. Review a dry run and
confirm the source and destination accounts before using `--delete-source`.

## Security notes

- Keep this repository private.
- Store passwords and app passwords only in 1Password.
- Do not commit mounted Environment files, logs, exported mail, or OAuth data.
- Rotate any credential that has been pasted into a terminal, chat, or Git
  history.

## RFC 822 deduplication

The dedupe workflow is documented in [`dedupe/README.md`](dedupe/README.md).
It is separate from imapsync: the scanner reads Gmail headers through IMAP,
while the analyzer and manifest builder operate only on local checkpoint data.

Generated scan data and manifests belong under `dedupe-output/`, which is
excluded from Git because it contains private mailbox metadata.
