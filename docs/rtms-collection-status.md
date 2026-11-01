# RTMS recovery — 2026-11-01 (KST)

## Verified recovery
- Incident run: https://github.com/jcrkorea11-cyber/rtms-data/actions/runs/41264888905
- Actual failed partitions: commercial 11320/202508 and 11560/202511. The latter was November 2025, not November 2026.
- Failure artifact contained 0 retained rows in both failed months. Existing published data retained 6 and 66 rows respectively.
- Fix commits: c4125d36813ca72d5e2527daac5b7b4e78603244; 6c8a3a45afc310142bcdf87432eea96f6b1d2662.
- Bounded GET retries (default four attempts), exponential backoff/jitter, increasing timeouts (90/120/150/180 seconds), Retry-After handling. Certificate validation and non-retryable authentication errors are not bypassed. Request URLs/secrets are not logged.
- Commercial pagination validates explicit success, totalCount and page completeness.
- Collection uses a temporary staging directory; published files remain untouched on collection failure or unverified historical row removal.
- Existing cancellation filtering remains. Removal is permitted only when the old record exactly matches an explicitly cancelled upstream record after excluding cancellation status fields. Unknown differences block publication and preserve candidates.
- Comparison, cancellation evidence and candidate outputs are retained as Actions artifacts. Shared concurrency and non-force push retries remain.

## Validation
- 11 unit tests pass locally and the final Actions test step passes; additional isolated end-to-end staging tests verify that unverified removal preserves existing files and exact cancellation evidence is accepted.
- First recovery run: https://github.com/jcrkorea11-cyber/rtms-data/actions/runs/41313421649
- All 25 commercial districts completed with zero failed months. Two real network timeouts recovered on retry (14:01:32 and 14:07:51 UTC), distinct from mocked test retries.
- The two incident months returned 7 and 70 raw rows; after existing cancellation filtering, 6 and 66 remained, exactly matching the published baseline, including row values and order.
- Full first candidate: 26,935 rows versus 26,888 baseline rows; 92 added row occurrences and 45 removed row occurrences. Changes include housing, beyond the incident commercial months.
- Publication was correctly blocked by the first conservative comparison. The first recovery artifact contains unchanged baseline data plus the full candidate, comparison and collection log: artifact 13085604868, retained through November 15.
- Final evidence-aware run: https://github.com/jcrkorea11-cyber/rtms-data/actions/runs/41313807243 — completed; all API queries returned, but publication blocked by historical-data comparison.

## Final status — verified 2026-11-01 23:30 KST
- Final run 41313807243 finished at 23:24 KST. All 575 commercial district/month partitions returned (25 districts × January 2025 through November 2026), all districts reported zero failed months. Two real timeouts recovered on retry. Both incident partitions again exactly match the 6/66-row baseline after cancellation filtering.
- Final candidate totals: 26,962 rows versus 26,888 published baseline; 106 added and 32 removed row occurrences.
- Final audit replay also normalizes numeric JSON cancellation fields to CSV strings. Twelve unit tests pass. Replaying the actual final artifact with this correction proves 7 removals are explicit cancellations; 25 remain unverified (24 housing row occurrences, 1 Jongno commercial row).
- Numeric normalization was validated locally against the real artifact; a new live API run of that final normalization-only revision was not performed. It would still block the same candidate because 25 removals lack exact cancellation evidence.
- No data files were published or overwritten. Both validation runs skipped Commit & push. Current published data remains the baseline; automatic collection is NOT declared fully healthy.
- Final artifact 13087756340 retains baseline, candidate, cancellation evidence, comparison and collection log through November 15: https://github.com/jcrkorea11-cyber/rtms-data/actions/runs/41313807243/artifacts/13087756340
- Detailed corrected per-file comparison: docs/rtms-recovery-comparison-20261101.json.
- Next action: investigate the 25 unverified row removals against upstream records and paging consistency. Housing candidate membership changed between the two complete runs; the root cause is not established. Do not relax the guard, union snapshots blindly, or publish the incomplete/ambiguous replacement. Re-run after resolving these differences and verify the final push.
- No verification run remains active and no new background follow-up automation was configured.

## Previous incident (historical record)

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

