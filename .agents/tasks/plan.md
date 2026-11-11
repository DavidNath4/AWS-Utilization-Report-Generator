# Implementation Plan: GuardDuty findings on "9. Security Alert and Finding" slide

## Findings from exploration
- Configured-regions mechanism: there is no region list. Each account has ONE region: `p["region"]` parsed from the uploaded .docx (`docx_parser.py`, `/generate`) or the `region` query param (`/generate-direct`, default `ap-southeast-3`). `app.py::_collect_for_account(account_id, region, ...)` calls `auth.assume_role(account_id, role_name, region)`, which returns a `boto3.Session(region_name=region)`. So "configured regions" = `session.region_name` of that session. Decision: `collect_guardduty(session, ...)` queries `[session.region_name]` only (kept as a list so more configured regions can be added later). Do NOT use `get_regions`/scan-all like Lightsail does.
- Report period: `start_date`/`end_date` (UTC datetimes, optional) and `period_days` are passed to every collector. Use `_et = end_date or now`, `_st = start_date or (_et - timedelta(days=pd))` as in `collect_cost_by_service`.
- Template: `template.pptx` contributes only slide 1; all others are built in code. The slide already exists as `slide_placeholder(prs, "9. Security Alert and Finding")` in `generate_report` (title only, empty). No template change needed. Agenda already lists it.
- Style: collectors use `logger = logging.getLogger(__name__)`, `logger.info("Collecting X...")`, try/except returning empty values, never raising. Slides use `_new_slide`, `add_title`, `add_table(slide, rows, headers)` (font 8/9pt, uses `L.ML/L.MT/L.CW/L.RH`), `add_table_split`. Per-account slides get `acct_data = {"label": ...}` and title suffix `f" ({label})"`.
- Merged flow: `_build_merged_report_data` builds `per_account` dicts; `generate_report` has a multi-account branch (per_account > 1) and single-account branch. Single path in `/generate` (len(parsed)==1) and `/generate-direct` build `report_data` dicts by hand.
- Assumed: no pytest suite exists; verification is by script. Assume-role IAM role used by the app needs new GuardDuty read permissions.

## Decisions
- Table columns (7): Severity, Type, Title, Resource Type, Region, Count, Last Seen. Severity shown as "High/Medium/Low" text. Top 10 sorted by severity desc, then updatedAt desc. Title truncated to ~60 chars, Type to ~45 so row heights stay in bounds.
- Summary line above table: "High: N | Medium: N | Low: N | Total: N". Computed from all fetched findings (not just top 10). Skip `get_findings_statistics` (extra permission/call; counts are already derivable from fetched findings). Still document the permission only if used; since not used, list it as optional in docs. (Requirement lists it, so document it as "optional/recommended" and add it to the IAM policy sample.)
- Data shape returned by `collect_guardduty`: `{"regions": [{"region": r, "status": "ok"|"not_enabled"|"access_denied"|"error", "message": str}], "summary": {"High":n,"Medium":n,"Low":n,"total":n}, "findings": [{"severity":"High","severity_score":float,"type","title","resource_type","region","count","last_seen"}]}`. Never raises; on total failure returns the same shape with a status.
- Not-enabled / access denied / zero findings: render a text message on the slide instead of an empty table.

## Items

- [ ] 1. Add `collect_guardduty(session, pd=30, start_date=None, end_date=None, max_findings=500)` to collectors.py (after `collect_efs` or before `collect_savings_plans`).
      Regions = `[session.region_name]`. Per region: `gd = session.client("guardduty", region_name=r)`; `list_detectors()`; empty -> status `not_enabled`, message "GuardDuty not enabled". Else for first detector: `list_findings` via paginator with `FindingCriteria={"Criterion": {"service.archived": {"Eq": ["false"]}, "updatedAt": {"Gte": ms_start, "Lte": ms_end}}}` (epoch milliseconds from the period), `SortCriteria={"AttributeName": "updatedAt", "OrderBy": "DESC"}`, cap at `max_findings` IDs; then `get_findings` in chunks of 50. Map: severity score >=7 High, >=4 Medium, else Low; Type=`Type`, Title=`Title`, Resource Type=`Resource.ResourceType`, Region=`Region`, Count=`Service.Count`, Last Seen=`UpdatedAt` (or `Service.EventLastSeen`) formatted `%Y-%m-%d %H:%M`. Catch `botocore.exceptions.ClientError`: codes `AccessDeniedException`/`UnauthorizedOperation`/`AccessDenied` -> `access_denied` with log warning; other errors -> `error`. Sort findings (score desc, last_seen desc), compute summary.
      Files: collectors.py
      Verify: `python -m py_compile collectors.py` succeeds; mocked test in item 5.

- [ ] 2. Wire into app.py (depends on 1).
      Import `collect_guardduty`; in `_collect_for_account` call `gd = collect_guardduty(session, period_days, start_date=start_date, end_date=end_date)` and return it as key `"guardduty"`. Add `"guardduty": data["guardduty"]` to both single-account `report_data` dicts (`/generate` len==1 branch and `/generate-direct`). In `_build_merged_report_data` add `"guardduty": data.get("guardduty")` to each `per_account` entry, and `"guardduty": <first/only or None>` is not needed at top level for multi-account; for a group with a single account the else-branch of generate_report needs `data["guardduty"]`, so set top-level `"guardduty"` to the merged object when exactly one account (else None).
      Files: app.py
      Verify: `python -m py_compile app.py`.

- [ ] 3. Add `slide_security(prs, data)` in report_generator.py and use it (depends on 1 shape).
      Replace `slide_placeholder(prs, "9. Security Alert and Finding")` in `generate_report`: in the multi-account branch loop `per_account` calling `slide_security(prs, {"label": label, "guardduty": acct.get("guardduty")})`; in the else branch call `slide_security(prs, data)`. Function: new slide, title `"9. Security Alert and Finding" + suffix`; if `guardduty` is None or no regions ok -> textbox message from region messages ("GuardDuty not enabled in <region>" / "Access denied to GuardDuty (check guardduty:* permissions)" / "Unable to retrieve GuardDuty findings"); if ok but zero findings -> "No active GuardDuty findings in this report period."; otherwise summary textbox (Font Calibri, `_set_font`) at `L.MT`, then `add_table(slide, rows[:10], headers, top=L.MT + Inches(0.5))` with the 7 columns, and a note "Showing top 10 of N findings" when N>10. Keep fixed shape bounds inside `L.W`/`L.H` (10 rows + header at `L.RH` must fit; reduce rows to fit if `top + RH*11 > L.H - bottom margin`).
      Files: report_generator.py
      Verify: `python -m py_compile report_generator.py`; script in item 5.

- [ ] 4. Docs: add a "Security Alert and Finding (GuardDuty)" section to docs/USER_GUIDE.md and a bullet/IAM section to README.md.
      Explain: only the configured region(s) of each account are queried, active (non-archived) findings updated within the report period, top 10 by severity then recency, severity mapping, behavior when not enabled / access denied / none. Add IAM policy snippet with `guardduty:ListDetectors`, `guardduty:ListFindings`, `guardduty:GetFindings`, `guardduty:GetFindingsStatistics` to the assumed role (`DEFAULT_ROLE_NAME`). Do not touch .env.
      Files: docs/USER_GUIDE.md, README.md
      Verify: read both files and confirm the permissions list and behavior notes are present and match code.

- [ ] 5. Verify with a mocked script (temp file, deleted afterwards): create `_verify_gd.py` in a temp dir (`tempfile.mkdtemp`), not committed.
      Use `unittest.mock.MagicMock` session (or botocore `Stubber` on a real `boto3.client("guardduty", region_name="ap-southeast-3", aws_access_key_id="x", aws_secret_access_key="x")`) to cover: (a) 120 findings of mixed severities (checks 50-batch chunking: 3 get_findings calls, severity mapping 7.0->High, 4.0->Medium, 3.9->Low, ordering), (b) empty `DetectorIds` -> not_enabled, (c) `AccessDeniedException` ClientError -> access_denied without raising, (d) zero findings. For each, call `generate_report(data, output_dir=tmp)` (must work with template.pptx present), reopen with `python-pptx`, find the slide whose title contains "Security Alert and Finding", assert: (a) table with 11 rows (header + 10) and 7 columns plus summary text; (b)/(c)/(d) no table and the expected message text; every shape satisfies `left>=0, top>=0, left+width<=prs.slide_width, top+height<=prs.slide_height`. Finally delete the temp dir and the script; confirm with `dir`.
      Files: temporary only
      Verify: `python _verify_gd.py` prints all assertions passed; `python -m py_compile collectors.py report_generator.py app.py auth.py` succeeds; no leftover temp files.

## Closing constraints
- Do not commit; do not read or modify `.env`.
- Decomposition: judged to be one coherent feature (single data flow collect -> pass -> render -> doc), so the existing implement-and-review loop is left unchanged and writes `.agents/tasks/review.json` with `verdict`.
