# GitHub-only scan requests

No Cloudflare, external API backend, PAT or account setup is required by this change. The dashboard opens a GitHub issue form containing a random correlation ID. The signed-in repository owner must submit that issue; clicking the dashboard link alone does not start a scan. The issue and automation comment are public and must contain no private data.

The Owner scan request workflow accepts only issues authored by the repository owner with an exact [SCAN] UUID title. It reads only code from main, ignores issue-body instructions, and uses the server-side built-in GITHUB_TOKEN with actions:write to dispatch dashboard.yml on main. It posts a request-outcome comment. Active scans and a five-minute cooldown cause the request to be declined. GitHub workflow policy/availability still applies. This is a guard, not a transactional billing/rate-limit service.

The dashboard matches the UUID to the GitHub run name, polls public run metadata at most once per two minutes while visible, and checks published snapshot run_id before reporting availability. It handles failed/cancelled conclusions and stops monitoring after 90 minutes without cancelling the underlying run. API access, rate limits, network failures and GitHub Actions queuing can prevent automatic monitoring; links to GitHub remain the authoritative fallback. No token is embedded in browser code.

The existing strict 0–48-hour filter, expiry behavior, application-state storage, scanner and source configuration remain intact. Reload published results is separate from Request a background scan. Published counts are freshness-qualified candidates, not verified recommendations or proof of exhaustive coverage.

This patch does NOT add 72 validated employer adapters, change Naukri access, add pagination or enable new paid services. Those remain separate unfinished scanner work. No unvalidated career-system mappings are described as working.
