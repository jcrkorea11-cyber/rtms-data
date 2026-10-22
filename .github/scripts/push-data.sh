#!/usr/bin/env bash
# Never force-push or choose a conflict side automatically.
set -euo pipefail
git config user.name "rtms-bot"
git config user.email "bot@users.noreply.github.com"
git add -- data/
if git diff --cached --quiet; then
  echo "No data changes"
  exit 0
fi
git commit -m "${1:-data: automated update}"
for attempt in 1 2 3 4 5; do
  git fetch origin main
  if ! git rebase origin/main; then
    git rebase --abort
    echo "::error::Data conflict; original local commit preserved. Recover from uploaded artifact."
    exit 1
  fi
  if git push origin HEAD:main; then
    echo "Published $(git rev-parse HEAD)"
    exit 0
  fi
  if [ "$attempt" -lt 5 ]; then sleep $((attempt * 3)); fi
done
echo "::error::Push failed after 5 attempts; data preserved in artifact."
exit 1
