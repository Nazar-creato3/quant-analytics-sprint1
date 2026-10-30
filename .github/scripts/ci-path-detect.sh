#!/usr/bin/env bash
# Classify PR/push paths for job gating. No GitHub-hosted cache.
set -euo pipefail
EVENT="${GITHUB_EVENT_NAME:-}"
# GITHUB_OUTPUT is a file. Do not mkdir it (fails on Windows self-hosted).

FILES=()
if [ "$EVENT" = "pull_request" ]; then
  BASE="${PR_BASE_SHA:?}"
  git fetch --no-tags --depth=1 origin "$BASE" 2>/dev/null || git fetch --no-tags origin "$BASE"
  while IFS= read -r line; do FILES+=("$line"); done < <(git diff --name-only "$BASE" HEAD)
else
  while IFS= read -r line; do FILES+=("$line"); done < <(git diff --name-only HEAD^ HEAD 2>/dev/null || git ls-files)
fi

be=0
fe=0
docs=0
other=0
for f in "${FILES[@]:-}"; do
  [ -z "$f" ] && continue
  case "$f" in
    frontend/*) fe=1 ;;
    backend/*) be=1 ;;
    docs/*) docs=1 ;;
    *.md) docs=1 ;;
    *) other=1 ;;
  esac
done

mode=all
if [ "$EVENT" != "pull_request" ]; then
  mode=all
elif [ "$other" = 1 ]; then
  mode=all
elif [ "$be" = 1 ] && [ "$fe" = 1 ]; then
  mode=all
elif [ "$be" = 1 ] && [ "$fe" = 0 ]; then
  mode=backend
elif [ "$fe" = 1 ] && [ "$be" = 0 ]; then
  mode=frontend
elif [ "$docs" = 1 ]; then
  mode=docs
else
  mode=all
fi

run_baseline=false
run_backend=false
run_frontend=false
run_gitleaks=false
case "$mode" in
  all)
    run_baseline=true; run_backend=true; run_frontend=true; run_gitleaks=true ;;
  backend)
    run_backend=true; run_gitleaks=true ;;
  frontend)
    run_frontend=true; run_gitleaks=true ;;
  docs) ;;
esac

{
  echo "mode=$mode"
  echo "run_baseline=$run_baseline"
  echo "run_backend=$run_backend"
  echo "run_frontend=$run_frontend"
  echo "run_gitleaks=$run_gitleaks"
} >> "$GITHUB_OUTPUT"
echo "CI path mode=$mode files=${#FILES[@]}"
