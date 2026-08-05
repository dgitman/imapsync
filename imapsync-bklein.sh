#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
env_file="${IMAPSYNC_ENV_FILE:-$script_dir/.env.bklein}"

if [[ -r "$env_file" ]]; then
  # 1Password mounts Environment files as FIFOs, which Bash cannot source.
  while IFS='=' read -r name value; do
    case "$name" in
      IMAPSYNC_PASSWORD1|IMAPSYNC_PASSWORD2)
        export "$name=$value"
        ;;
    esac
  done < "$env_file"
fi

delete_source=false
extra_args=()

for arg in "$@"; do
  case "$arg" in
    --delete-source)
      delete_source=true
      ;;
    --delete1)
      echo "Use --delete-source to explicitly enable source deletion." >&2
      exit 2
      ;;
    -h|--help)
      cat <<'EOF'
Usage: imapsync-bklein.sh [--delete-source] [imapsync options]

Passwords are read from IMAPSYNC_PASSWORD1 and IMAPSYNC_PASSWORD2. They can be
injected by 1Password or loaded from the 1Password-managed .env.bklein mount.

By default, source messages are not deleted. --delete-source explicitly adds
imapsync's --delete1 option.
EOF
      exit 0
      ;;
    *)
      extra_args+=("$arg")
      ;;
  esac
done

: "${IMAPSYNC_PASSWORD1:?Set IMAPSYNC_PASSWORD1 through 1Password}"
: "${IMAPSYNC_PASSWORD2:?Set IMAPSYNC_PASSWORD2 through 1Password}"

args=(
  imapsync
  --user1 drbarryklein@gmail.com
  --user2 drklein@drbarryklein.com
  --gmail1
  --gmail2
)

if [[ "$delete_source" == true ]]; then
  args+=(--delete1)
fi

exec "${args[@]}" "${extra_args[@]}"
