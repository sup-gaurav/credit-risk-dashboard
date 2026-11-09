# Credit Risk Job Dashboard — Gaurav Singh

A GitHub Pages adaptation of the supplied Flask dashboard, not an unchanged deployment of app.py.

## Operation
- The workflow publishes the current dashboard first, then runs the scanner and republishes results.
- Scheduled every six hours (17 minutes past the hour, UTC), plus manual workflow runs. Scheduled execution is best-effort, not an exact-time guarantee.
- 120 generated search queries: 72 company-labelled searches and 48 domain/seniority variants. Some company labels overlap; these are not 72 unique employers. Queries are adapted, not exact copies of the original Boolean queries.
- Attempts LinkedIn, Indeed and Glassdoor through JobSpy; Naukri through its search endpoint; Google News RSS for indirect portal/ATS discovery. Platform access and completeness are not guaranteed.
- Custom bank-ATS adapters from the original are not included because their endpoints have not been verified. RSS is not a substitute for direct ATS coverage.
- Uses revised, category-capped keyword scoring with technology counted once. Scores are points, not resume-match percentages, and are not the original 18-dimension scoring engine.
- Retains up to 3,000 jobs for 14 days since last discovery; listings are not checked for closure. Source-reported posting dates may be missing or unreliable.
- Application tracking is browser-local. No applications are submitted. No cross-device sync.

## Privacy and limitations
Code and job data are public. Do not commit credentials, a private resume, or personal application notes. No guarantees of free service forever, source availability, listing freshness, or successful scans. Source health counts successful requests, not independently verified coverage; JobSpy may internally suppress some source errors.

## Setup
In repository Settings > Pages, select GitHub Actions as the source. Approve the workflow if GitHub requests approval. The Pages deployment job exposes the actual site URL. Scan failures appear in Actions; the last published site remains available. If no results are published yet, the dashboard says so explicitly.
