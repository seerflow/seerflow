#!/usr/bin/env bash
#
# S-346 — Dark-mode / brand-token sweep CI grep gate.
#
# Parity wrapper around the regex set enforced by
# `frontend/src/design-tokens.guard.test.ts`. Provides a fast, vitest-free way
# for CI or a developer to verify that no source file under `frontend/src/`
# (re-)introduces the forbidden Tailwind palette utilities or inline hex colour
# literals targeted by the S-346 sweep.
#
# Exits 0 when no violations are found, 1 otherwise. The authoritative source
# of truth (including the narrow allowlist) is the vitest guard test; this
# script is a fast first line of defence for CI pipelines that don't want to
# spin up the full test suite.
set -euo pipefail

# Compute the frontend root from this script's location so the script works
# whether invoked from the repo root or from inside `frontend/`.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_ROOT="$(cd "$HERE/.." && pwd)"
SRC_ROOT="$FRONTEND_ROOT/src"

if [[ ! -d "$SRC_ROOT" ]]; then
  echo "S-346 guard: expected $SRC_ROOT to exist" >&2
  exit 2
fi

# Combined regex covering the forbidden surface/text/border palette utilities
# and inline hex literals (AC1 of S-346), plus the bright semantic palette
# families S-349 migrated to the brand crit/warn/info/destructive tokens.
PATTERN='(\b(bg|text|border|hover:bg|hover:text|divide)-zinc-[0-9]+|\b(bg|text)-(white|black)(/[0-9]+)?\b|#[0-9a-fA-F]{3,8}\b|\b(bg|text|border|hover:bg|hover:text|divide)-(red|orange|amber|yellow|green|emerald|lime|teal)-[0-9]+)'

# Files we deliberately allow to contain at least one of the patterns. Keep in
# sync with the ALLOWLIST in `src/design-tokens.guard.test.ts`. Each entry is a
# path suffix relative to $FRONTEND_ROOT.
ALLOW=(
  "src/components/SigmaRules/monacoTheme.ts"
  "src/components/SigmaRules/monacoTheme.test.ts"
  "src/components/ui/alert-dialog.tsx"
  "src/components/ui/sheet.tsx"
  "src/components/AttackHeatmap/TechniqueCell.tsx"
  "src/components/AttackHeatmap/DrilldownPanel.tsx"
  "src/design-tokens.guard.test.ts"
)

allow_skip() {
  local path="$1"
  for a in "${ALLOW[@]}"; do
    if [[ "$path" == *"$a" ]]; then
      return 0
    fi
  done
  return 1
}

violations=0
while IFS= read -r -d '' file; do
  rel="${file#"$FRONTEND_ROOT"/}"
  # Test files may legitimately mention the forbidden tokens in regex
  # assertions — skip them here. The vitest guard applies the same exception.
  case "$rel" in
    *.test.ts|*.test.tsx|*.spec.ts|*.spec.tsx)
      continue
      ;;
  esac
  if allow_skip "$file"; then
    continue
  fi
  if grep -nEH "$PATTERN" "$file" >/dev/null; then
    grep -nEH "$PATTERN" "$file" || true
    violations=$((violations + 1))
  fi
done < <(find "$SRC_ROOT" -type f \( -name '*.ts' -o -name '*.tsx' \) -print0)

if [[ $violations -gt 0 ]]; then
  echo
  echo "S-346 guard: $violations file(s) violate the dark-mode / brand-token sweep." >&2
  echo "Migrate to brand CSS tokens (var(--surface) / var(--text-3) etc.)" >&2
  echo "or add a justified allowlist entry (see frontend/src/design-tokens.guard.test.ts)." >&2
  exit 1
fi

echo "S-346 guard: clean."
