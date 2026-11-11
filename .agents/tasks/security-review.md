# GuardDuty findings on the "Security Alert and Finding" slide

Adds `collect_guardduty` (collectors.py), wires its result through app.py into every report_data path, and replaces the empty placeholder slide with `slide_security` (report_generator.py). Only the session's configured region is queried, findings are active (non-archived) within the report period, and the slide shows a severity summary plus a top-10 table, or a message when GuardDuty is unavailable.

Watch for: summary counts and top-10 are computed from the newest 500 findings only, so a High finding older than that window can be missed (confirmed, low impact).

**Verdict**: APPROVED

## High-level view

Region scoping reuses the existing mechanism: the assumed-role session carries the one configured region, and the collector queries `[session.region_name]` only, with no scan of all regions.

Pagination uses the `list_findings` paginator with an `updatedAt` range and archived filter, capped at 500 IDs, then `get_findings` in chunks of 50. Severity maps to High at 7 or above, Medium at 4 or above, otherwise Low.

Failures never raise. Not enabled, access denied, other errors and zero findings each render a text note instead of an empty table. The slide is built per account for multi-account reports and directly for single-account reports.

<details>
<summary>Issues (2)</summary>

1. **Cap by recency, not severity** (confirmed, non-blocking) — the 500 cap takes the newest IDs, so summary counts and top-10 may omit older High findings. Optionally sort criteria by severity or document the cap.
2. **Verification gaps** (confirmed, non-blocking) — no full `generate_report` run and no real AWS call. The mocked slide test covers each case.

</details>

<details>
<summary>Details</summary>

## Cap behavior
`list_findings` is sorted by `updatedAt` DESC and truncated at `max_findings=500`. The summary's High/Medium/Low/Total are computed from fetched findings, not the account total. On a noisy account the slide could under-report. The "Showing top N of M" note uses M from the capped set.

## Evidence
verification.md reports a mocked run: 120 findings gave 3 `get_findings` calls (50/50/20). The mapping boundaries 7.0, 4.0 and 3.9 were checked. The not-enabled, AccessDenied and zero-findings cases produced messages with no table. The 11x7 table stayed within slide bounds. The docs list the IAM permissions in USER_GUIDE.md and README.md. `slide_security` also limits rows to fit the slide height.

</details>

<details>
<summary>File map</summary>

- collectors.py: `_gd_severity`, `collect_guardduty`
- app.py: collected, merged and passed as `guardduty` in all report_data paths
- report_generator.py: `slide_security`, `_trunc`, replaces placeholder
- docs/USER_GUIDE.md, README.md: behavior and IAM permissions

</details>
