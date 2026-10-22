# RTMS collection incident — 2026-10-22 (KST)

## Verified evidence
- Run 39529004811 (October 21): collection step exited successfully; commit 3afdbeb changed 51 files; push rejected with fetch first. Five commercial API requests timed out, so the source snapshot was incomplete.
- October 19 and 20 collection runs failed; failures also predate October 19.
- Before the fix, summary.json and the checked Jongno housing CSV last changed on August 30 (7ce43524163beb680f17c76a07353420546fc252). Published snapshots are stale; exact missing-record count is unverified.
- October 21 has no recovery artifacts. The unpushed ephemeral commit cannot be reconstructed from logs alone.
- The collector recollects housing years 2025/2026 and commercial months from January 2025 through the present month. A complete new run can refresh that range, but cannot recreate historical daily snapshots.

## Fix
Commit 4c0a32f45d0c81584e02de47f1675d666012e926 changes infrastructure only. No existing data files were edited.
- All five workflows share rtms-repo-push, cancel-in-progress false, and check out current main with full history.
- Shared push script fetches/rebases and retries non-force pushes five times. Content conflicts abort rebase without choosing either side.
- Collected files are archived before push for 14 days.
- Daily RTMS collection refuses publication on logged API failures, missing keys, or failed months.

## Validation and limits
- Five YAML files parsed; shell syntax checked.
- Isolated real Git tests passed: stale checkout retains both writers; unchanged data succeeds; same-file conflict fails and preserves local and remote versions.
- Main file read verified the applied change.
- Corrected production execution remains unverified. No new run for the fix commit appeared in the latest check. The connector exposes reruns but no workflow_dispatch. Old-run reruns use old settings and would not validate this fix.
- Run 39706872763 was already running the OLD workflow during the fix; it does not validate this change.
- Both connected Desktop Commander devices were offline.

## Next action
Dispatch daily-rtms-collect on main, verify collection completeness, archive, commit and remote push; compare updated summary/CSV history and counts to logs. Investigate upstream errors before publishing incomplete data. GitHub concurrency permits one pending run per group; a newer pending run may replace an older pending run, though running collection is not cancelled. Displaced scheduled snapshots are refreshed by the next full run.
