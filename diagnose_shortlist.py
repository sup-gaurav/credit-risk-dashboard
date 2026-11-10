import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import freshness


def diagnose(state, now):
    rows = []
    counts = Counter()
    for url, item in state.get('items', {}).items():
        events = item.get('posting_events', [])
        verdicts = [freshness.assess({'date_posted': e.get('value'), 'job_url': e.get('url', url)}, now)['status'] for e in events]
        status = next((v for v in ['within_48h', 'boundary_unverified', 'older_than_48h'] if v in verdicts), 'date_unverified')
        reasons = []
        if status != 'within_48h':
            reasons.append(status)
        gates = item.get('gates') or {}
        for gate in ['domain', 'seniority', 'india']:
            if not gates.get(gate):
                reasons.append(gate + '_not_passed')
        if not item.get('description_available'):
            reasons.append('description_unavailable')
        if item.get('eligibility') != 'eligible':
            reasons.append('eligibility_not_passed')
        if item.get('detail_error'):
            reasons.append('detail_fetch_error')
        published = status == 'within_48h' and item.get('eligibility') == 'eligible'
        counts.update(reasons)
        counts['freshness_qualified'] += status == 'within_48h'
        counts['publication_rule_passed'] += published
        rows.append({'title': item.get('title', ''), 'company': item.get('company', ''), 'url': url, 'source': item.get('site', ''), 'freshness_status': status, 'eligibility': item.get('eligibility', ''), 'publication_rule_passed': published, 'reasons': '; '.join(reasons), 'detail_error': item.get('detail_error', ''), 'first_seen': item.get('first_seen', ''), 'last_seen': item.get('last_seen', '')})
    return rows, dict(counts)


def main():
    state = json.loads(Path('data/ordered-state.json').read_text())
    snapshot = json.loads(Path('site/jobs.json').read_text())
    reference = datetime.fromisoformat(snapshot['last_scan'].replace('Z', '+00:00'))
    rows, counts = diagnose(state, reference)
    _, current_counts = diagnose(state, datetime.now(timezone.utc))
    out = Path('diagnostic-output')
    out.mkdir(exist_ok=True)
    with (out / 'candidate-exclusions.csv').open('w', newline='', encoding='utf-8') as f:
        fields = ['title', 'company', 'url', 'source', 'freshness_status', 'eligibility', 'publication_rule_passed', 'reasons', 'detail_error', 'first_seen', 'last_seen']
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    employers = state.get('employer_coverage', {})
    gaps = [{'employer': name, **entry} for name, entry in employers.items() if entry.get('state') != 'exhausted_accessible_listing']
    issues = Counter(issue for entry in gaps for issue in entry.get('issues', []))
    summary = {'generated_at': datetime.now(timezone.utc).isoformat(), 'reference_scan_at': snapshot['last_scan'], 'source_run_id': snapshot.get('run_id'), 'unique_checkpoint_candidates': len(rows), 'observation_count': state.get('observations'), 'counts_at_scan_time': counts, 'counts_now': current_counts, 'counts_overlap': True, 'eligibility_note': 'Eligibility is the saved scanner decision; this report cannot distinguish every historical scoring rejection.', 'source_timestamps_note': 'last_seen is observation time, not proof of a fresh source collection or posting date.', 'checkpoint_phase': state.get('phase'), 'campaign_started_at': state.get('started_at'), 'completed_boards': state.get('completed_boards', []), 'deferred_boards': state.get('deferred_boards', {}), 'employer_issue_counts': dict(issues), 'employer_gaps': gaps}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in summary.items() if k != 'employer_gaps'}, indent=2))


if __name__ == '__main__':
    main()
