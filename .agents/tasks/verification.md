# Verification: GuardDuty on "Security Alert and Finding" slide

Ran: `python -m py_compile collectors.py report_generator.py app.py auth.py` -> OK.
Ran a mocked script (MagicMock session/client, python-pptx reopen, temp script deleted afterwards). Results:

- 120 findings (paginated in 2 pages): `get_findings` called 3 times (50/50/20).
- Severity mapping: 7.0 -> High, 4.0 -> Medium, 3.9 -> Low (8.0 High). Summary {High 40, Medium 40, Low 40, total 120}; sorted by severity desc.
- FindingCriteria contains `service.archived Eq false` and `updatedAt` range.
- Only `session.region_name` is queried (no all-region scan).
- (a) Slide: table 11 rows (header + 10) x 7 columns (Severity, Type, Title, Resource Type, Region, Count, Last Seen), summary "High: 40 | Medium: 40 | Low: 40 | Total: 120", note "Showing top 10 of 120 findings".
- (b) Not enabled: no table, "GuardDuty not enabled in ap-southeast-3".
- (c) AccessDeniedException: no crash, no table, "Access denied to GuardDuty (check guardduty:* permissions)".
- (d) Zero findings: no table, "No active GuardDuty findings in this report period."
- All shapes in every case within slide width/height (checked numerically, 13.333x7.5in).

Docs check: docs/USER_GUIDE.md (section "Security Alert and Finding (GuardDuty)", IAM JSON) and README.md both list guardduty:ListDetectors, ListFindings, GetFindings, GetFindingsStatistics (the last marked optional, not used by code). No full generate_report run was done (needs full account data); slide_security was exercised directly.
