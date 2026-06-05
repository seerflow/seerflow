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
#   * The token embeds a timestamp and expires, and the fence resets long
#     transfers; auth.txt.gz is 7.2 GB and outlives a single token. download_gz
#     handles this in-process: it re-mints a fresh token and resumes the partial
#     .gz (`-C -`) on every attempt, aborting stalled sockets, until the file
#     reaches its probed full size (capped at MAX_ATTEMPTS=300 per member).
#   * Re-running skips any member whose .csv already exists; a partial .gz from
#     an interrupted run is resumed, not restarted.

set -euo pipefail

# Defaults (env vars seed them; --flags below override).
BASE="https://csr.lanl.gov"
EMAIL="${EMAIL:-}"
USAGE="${USAGE:-Evaluating Seerflow streaming log-anomaly detection}"
FILES="${FILES:-auth proc flows dns redteam}"
DEST="${DEST:-data/lanl}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-300}"

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

probe_size() {
  # Total byte length of a member, via a one-byte Range probe on a fresh token.
  # Echoes the size (e.g. "7626505158") or empty string if the server withholds
  # Content-Range — callers must tolerate an empty result.
  local name="$1" token cr
  token="$(mint_token)"
  cr="$(curl -sS -r 0-0 -D - -o /dev/null \
    "$BASE/data-fence/$token/cyber1/$name.txt.gz" 2>/dev/null \
    | tr -d '\r' | grep -i '^Content-Range:' | tail -1 || true)"
  # cr = "Content-Range: bytes 0-0/7626505158" -> strip everything up to "/"
  [[ "$cr" == *"/"* ]] && printf '%s' "${cr##*/}"
}

download_gz() {
  # Resilient resume loop for one member. The LANL fence resets long transfers
  # and its tokens expire before a 7 GB member finishes, so a single curl is
  # not enough. We probe the target size, then loop: re-mint a fresh token,
  # resume the partial .gz with `-C -`, and abort stalled sockets quickly
  # (--speed-time) so the next attempt starts clean. Completed bytes persist
  # on disk between attempts. Returns 0 once the file reaches its full size.
  local name="$1" gz="$2" target attempt=0 have
  target="$(probe_size "$name")"
  while :; do
    have="$(stat -c %s "$gz" 2>/dev/null || echo 0)"
    if [[ -n "$target" && "$have" -ge "$target" ]]; then
      return 0
    fi
    attempt=$((attempt + 1))
    if [[ "$attempt" -gt "$MAX_ATTEMPTS" ]]; then
      echo "error: $name still incomplete after $MAX_ATTEMPTS attempts" \
        "($have/${target:-?} bytes) — re-run to continue" >&2
      return 1
    fi
    echo "          [attempt $attempt] resuming from $have bytes${target:+ / $target}"
    if curl -fSL -C - \
      --retry 5 --retry-all-errors --retry-delay 5 \
      --speed-time 60 --speed-limit 500 \
      "$BASE/data-fence/$(mint_token)/cyber1/$name.txt.gz" -o "$gz"; then
      # curl reports success; with no known target trust it, else re-check size.
      [[ -z "$target" ]] && return 0
    fi
    sleep 3
  done
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
  echo "[$i/$total] downloading $name.txt.gz ..."
  download_gz "$name" "$gz"
  echo "          decompressing -> $csv"
  gunzip -kc "$gz" > "$csv"
  echo "          $(wc -l < "$csv") rows"
done

echo
echo "done. validate with:"
echo "  uv run python -m seerflow validate $DEST --json"
echo "(full dataset: use the streaming API — see documents/testing-seerflow-against-lanl.md §4.3)"
