#!/usr/bin/env bash
#
# download_lanl.sh — fetch the LANL 2015 "Comprehensive, Multi-Source
# Cyber-Security Events" dataset into the layout `seerflow validate` reads.
#
# The dataset sits behind a soft self-service "fence": you submit an email +
# intended-use string to GET /data-fence/token, receive a short-lived signed
# token, and download from /data-fence/<token>/cyber1/<file>.txt.gz. This
# script performs that handshake, downloads the requested members, and
# decompresses each into <dest>/<name>.csv.
#
# The harness reads auth/proc/flows/redteam; it does NOT read dns, so dns is
# excluded by default. redteam is the ground truth (mandatory); auth carries
# most of the red-team signal.
#
# Usage:
#   EMAIL="you@example.com" tools/download_lanl.sh
#   EMAIL=... USAGE="evaluating seerflow" FILES="auth redteam" DEST=data/lanl tools/download_lanl.sh
#
# Env vars:
#   EMAIL  (required)  Address submitted to the LANL fence.
#   USAGE  (optional)  Intended-use string. Default: a seerflow-eval note.
#   FILES  (optional)  Space-separated members. Default: "auth proc flows redteam".
#                      Add "dns" only if you have a downstream use for it.
#   DEST   (optional)  Output directory. Default: "data/lanl".
#
# Notes:
#   * The token embeds a timestamp and expires. auth.txt.gz is 7.2 GB and may
#     outlast a token; this script re-mints a fresh token before each member
#     so a long auth download starts clean. A single member that itself
#     outlives its token will 403 mid-stream — re-run; completed members are
#     skipped.
#   * Re-running skips any member whose .csv already exists.

set -euo pipefail

usage() {
  cat <<'EOF'
download_lanl.sh — fetch the LANL 2015 dataset into the layout `seerflow validate` reads.

Usage:
  EMAIL="you@example.com" tools/download_lanl.sh
  EMAIL=... USAGE="evaluating seerflow" FILES="auth redteam" DEST=data/lanl tools/download_lanl.sh
  tools/download_lanl.sh -h | --help

Configured via env vars:
  EMAIL  (required)  Address submitted to the LANL fence.
  USAGE  (optional)  Intended-use string. Default: a seerflow-eval note.
  FILES  (optional)  Space-separated members. Default: "auth proc flows redteam".
                     The harness ignores dns; add it only if you need it.
  DEST   (optional)  Output directory. Default: "data/lanl".

The dataset sits behind a self-service token gate: this submits email+usage to
GET /data-fence/token, then downloads /data-fence/<token>/cyber1/<file>.txt.gz
and decompresses each into <DEST>/<file>.csv. redteam is the ground truth
(mandatory for scoring); auth carries most of the signal.
EOF
}

case "${1:-}" in
  -h | --help) usage; exit 0 ;;
  "") ;;
  *)
    echo "error: unknown argument '$1' (configure via env vars; see -h)" >&2
    exit 2
    ;;
esac

BASE="https://csr.lanl.gov"
EMAIL="${EMAIL:-}"
USAGE="${USAGE:-Evaluating Seerflow streaming log-anomaly detection}"
FILES="${FILES:-auth proc flows redteam}"
DEST="${DEST:-data/lanl}"

if [[ -z "$EMAIL" ]]; then
  echo "error: set EMAIL (e.g. EMAIL=you@example.com $0), or -h for help" >&2
  exit 2
fi

mint_token() {
  # GET /data-fence/token?email=..&usage=.. -> "<ts>/<sig>" (200) or error (403)
  local body status
  body="$(curl -sS -G "$BASE/data-fence/token" \
    --data-urlencode "email=$EMAIL" \
    --data-urlencode "usage=$USAGE" \
    -w $'\n%{http_code}')"
  status="${body##*$'\n'}"
  body="${body%$'\n'*}"
  if [[ "$status" != "200" ]]; then
    echo "error: token request failed ($status): $body" >&2
    exit 1
  fi
  printf '%s' "$body"
}

mkdir -p "$DEST"

read -ra members <<< "$FILES"
total=${#members[@]}
i=0
for name in "${members[@]}"; do
  i=$((i + 1))
  csv="$DEST/$name.csv"
  gz="$DEST/$name.txt.gz"
  if [[ -s "$csv" ]]; then
    echo "[$i/$total] skip $name — $csv already present"
    continue
  fi
  token="$(mint_token)"
  url="$BASE/data-fence/$token/cyber1/$name.txt.gz"
  echo "[$i/$total] downloading $name.txt.gz ..."
  curl -fSL --retry 3 --retry-delay 2 -C - "$url" -o "$gz"
  echo "          decompressing -> $csv"
  gunzip -kc "$gz" > "$csv"
  echo "          $(wc -l < "$csv") rows"
done

echo
echo "done. validate with:"
echo "  uv run python -m seerflow validate $DEST --json"
echo "(full dataset: use the streaming API — see documents/testing-seerflow-against-lanl.md §4.3)"
