#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/migrate.sh FROM TO SOURCE_OR_TEMPLATE TARGET_NAME [--apply]

Examples:
  scripts/migrate.sh discord fluxer https://discord.new/abc123 "Fluxer Copy"
  scripts/migrate.sh fluxer stoat FLUXER_GUILD_ID "Stoat Copy" --apply

This wrapper chooses --template for Discord template URLs/codes and --source-id otherwise.
USAGE
}

if [[ $# -lt 4 ]]; then
  usage
  exit 2
fi

FROM="$1"
TO="$2"
SOURCE="$3"
TARGET_NAME="$4"
APPLY="${5:-}"

ARGS=(guildbridge migrate --from "$FROM" --to "$TO" --target-name "$TARGET_NAME" --template-out exported.template.json --plan-out migration.plan.json)

if [[ "$FROM" == "discord" && "$SOURCE" == http* ]]; then
  ARGS+=(--template "$SOURCE")
elif [[ "$FROM" == "discord" && ! "$SOURCE" =~ ^[0-9]+$ ]]; then
  # Discord template codes are usually alphanumeric; guild IDs are numeric snowflakes.
  ARGS+=(--template "$SOURCE")
else
  ARGS+=(--source-id "$SOURCE")
fi

if [[ "$APPLY" == "--apply" ]]; then
  ARGS+=(--apply --plan-out migration.result.json)
fi

"${ARGS[@]}"
