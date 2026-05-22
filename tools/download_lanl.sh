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
# The harness reads auth/proc/flows/redteam; it does NOT read dns. All five
# members are downloaded by default — drop dns via --files to save 177 MB.
# redteam is the ground truth (mandatory); auth carries most of the signal.
#
# Usage:
#   tools/download_lanl.sh --email you@example.com
#   tools/download_lanl.sh --email you@example.com --files "auth redteam" --dest data/lanl
#   tools/download_lanl.sh                 # prompts for the email if not given
#   tools/download_lanl.sh -h
#
# Flags (override the env var of the same name); see -h for details:
#   --email <addr>   --usage <text>   --files "<list>"   --dest <dir>
#
# Notes:
#   * The token embeds a timestamp and expires. auth.txt.gz is 7.2 GB and may
#     outlast a token; this script re-mints a fresh token before each member
#     so a long auth download starts clean. A single member that itself
#     outlives its token will 403 mid-stream — re-run; completed members are
#     skipped.
#   * Re-running skips any member whose .csv already exists.

set -euo pipefail

# Defaults (env vars seed them; --flags below override).
BASE="https://csr.lanl.gov"
EMAIL="${EMAIL:-}"
USAGE="${USAGE:-Evaluating Seerflow streaming log-anomaly detection}"
FILES="${FILES:-auth proc flows dns redteam}"
DEST="${DEST:-data/lanl}"

usage() {
  cat <<'EOF'
download_lanl.sh — fetch the LANL 2015 dataset into the layout `seerflow validate` reads.

Usage:
  tools/download_lanl.sh --email you@example.com
  tools/download_lanl.sh --email you@example.com --files "auth redteam" --dest data/lanl
  EMAIL=you@example.com tools/download_lanl.sh        # env vars also work
  tools/download_lanl.sh                              # prompts for the email if unset
  tools/download_lanl.sh -h | --help

Options (flags override env vars of the same name):
  --email <addr>   Address submitted to the LANL fence. Prompted if unset.
  --usage <text>   Intended-use string. Default: a seerflow-eval note.
  --files <list>   Space-separated members. Default: "auth proc flows dns redteam"
                   (all). The harness ignores dns — drop it to save 177 MB.
  --dest  <dir>    Output directory. Default: "data/lanl".
  -h, --help       Show this help and exit.

The dataset sits behind a self-service token gate: this submits email+usage to
GET /data-fence/token, then downloads /data-fence/<token>/cyber1/<file>.txt.gz
and decompresses each into <DEST>/<file>.csv. redteam is the ground truth
(mandatory for scoring); auth carries most of the signal.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --email) EMAIL="${2:-}"; shift 2 || shift ;;
    --email=*) EMAIL="${1#*=}"; shift ;;
    --usage) USAGE="${2:-}"; shift 2 || shift ;;
    --usage=*) USAGE="${1#*=}"; shift ;;
    --files) FILES="${2:-}"; shift 2 || shift ;;
    --files=*) FILES="${1#*=}"; shift ;;
    --dest) DEST="${2:-}"; shift 2 || shift ;;
    --dest=*) DEST="${1#*=}"; shift ;;
    -h | --help) usage; exit 0 ;;
    *)
      echo "error: unknown argument '$1' (see -h)" >&2
      exit 2
      ;;
  esac
done

# Email is required. Prompt for it interactively when neither --email nor the
# EMAIL env var supplied one; fail clearly if there's no terminal to ask.
if [[ -z "$EMAIL" ]]; then
  if [[ -t 0 ]]; then
    read -rp "LANL fence email: " EMAIL || true
  fi
  if [[ -z "$EMAIL" ]]; then
    echo "error: email required — pass --email <addr>, set EMAIL, or run interactively" >&2
    exit 2
  fi
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
