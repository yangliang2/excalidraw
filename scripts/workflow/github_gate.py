#!/usr/bin/env python3
"""Read-only GitHub PR checks adapter. No rerun, merge or approval operations."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import urlsplit


PRODUCTION_CHECK = 'empty-text-history'
PRODUCTION_WORKFLOW = 'Empty text history acceptance'
PRODUCTION_PATH = '.github/workflows/empty-text-history.yml'
PRODUCT_CLASSIFIER = 'Classify production browser product failure'
ENVIRONMENT_CLASSIFIER = 'Classify production browser environment failure'
BROWSER_STEP = 'Verify production empty text history'
PROTOCOL_STEP = 'Verify browser check exit protocol'
PROTOCOL_CLASSIFIER = 'Classify browser check protocol failure'
PROTOCOL_ENVIRONMENT_CLASSIFIER = 'Classify browser check protocol environment failure'
PENDING = {'IN_PROGRESS', 'QUEUED', 'PENDING', 'EXPECTED', 'REQUESTED', 'WAITING'}


class GitHubQueryError(ValueError):
    def __init__(self, reason, *, retryable=False):
        super().__init__(reason)
        self.retryable = retryable


def evidence(condition, reason):
    if not condition:
        raise ValueError(reason)


def actions_job_ids(url, repo):
    parsed = urlsplit(url)
    evidence(parsed.scheme == 'https' and parsed.netloc.lower() == 'github.com',
             'production check does not link to GitHub Actions')
    match = re.fullmatch(
        rf'/{re.escape(repo)}/actions/runs/([1-9][0-9]*)/job/([1-9][0-9]*)',
        parsed.path, re.IGNORECASE,
    )
    evidence(match, 'production check does not identify an Actions run and job in this repository')
    return tuple(map(int, match.groups()))


def completed_step(steps, name):
    matches = [step for step in steps if step['name'] == name]
    evidence(len(matches) == 1 and matches[0]['status'] == 'completed',
             'production job is missing a unique completed ' + name + ' step')
    return matches[0]['conclusion']


def classify_production_check(items, head, base, repo, pr, api):
    evidence(repo and pr and base and api, 'exact PR and Actions metadata are required')
    candidates = {}
    for item in items:
        evidence(item.get('workflowName') == PRODUCTION_WORKFLOW,
                 'unexpected production workflow name')
        ids = actions_job_ids(item['detailsUrl'], repo)
        evidence(ids not in candidates, 'ambiguous duplicate production check contexts')
        candidates[ids] = item
    run_id, job_id = max(candidates)
    item = candidates[run_id, job_id]
    if item['status'] in PENDING:
        return 'waiting', 'production job is still running'
    conclusion = item['conclusion']
    if item['status'] != 'COMPLETED' or conclusion not in ('SUCCESS', 'FAILURE'):
        return 'environment-error', f'production job concluded {conclusion}; a new CI attempt may be needed'

    run_endpoint = f'repos/{repo}/actions/runs/{run_id}'
    run = api(run_endpoint)
    evidence(
        run['id'] == run_id
        and run['repository']['full_name'].lower() == repo.lower()
        and run['event'] == 'pull_request'
        and run['path'].partition('@')[0] == PRODUCTION_PATH,
        'production run does not match the PR workflow',
    )
    if run['status'].upper() in PENDING:
        return 'waiting', 'production workflow is still running'
    evidence(
        run['status'] == 'completed' and run['conclusion'] == conclusion.lower(),
        'production workflow conclusion differs from the check',
    )
    attempt = run['run_attempt']
    evidence(type(attempt) is int and attempt > 0, 'production run has no exact attempt number')
    response = api(f'{run_endpoint}/attempts/{attempt}/jobs?per_page=100')
    jobs = response['jobs']
    matches = [job for job in jobs if job['name'] == PRODUCTION_CHECK]
    evidence(
        response['total_count'] == len(jobs) and len(matches) == 1
        and matches[0]['id'] == job_id,
        'production check does not match a unique job in the current attempt',
    )
    job = matches[0]
    check_path = rf'/repos/{re.escape(repo)}/check-runs/([1-9][0-9]*)'
    check_url = urlsplit(job['check_run_url'])
    check_match = re.fullmatch(check_path, check_url.path, re.IGNORECASE)
    evidence(
        job['run_id'] == run_id and job.get('run_attempt', attempt) == attempt
        and actions_job_ids(job['html_url'], repo) == (run_id, job_id)
        and check_url.scheme == 'https' and check_url.netloc.lower() == 'api.github.com'
        and check_match,
        'production job does not identify a GitHub check run in this repository',
    )
    check = api(check_url.path[1:])
    evidence(
        check['id'] == int(check_match[1])
        and check['name'] == PRODUCTION_CHECK
        and check['app']['slug'] == 'github-actions'
        and check['check_suite']['id'] == run['check_suite_id']
        and actions_job_ids(check['details_url'], repo) == (run_id, job_id)
        and all(record['status'] == 'completed'
                and record['conclusion'] == conclusion.lower() for record in (job, check)),
        'production check run metadata does not match the Actions job',
    )

    steps = job['steps']
    checkout_pattern = (
        rf'Verify checkout ([0-9a-f]{{40}}) for PR {pr}'
        rf' at {re.escape(head)} into {re.escape(base)}'
    )
    checkouts = [
        step['name'] for step in steps if step['name'].startswith('Verify checkout ')
    ]
    checkout = re.fullmatch(checkout_pattern, checkouts[0]) if len(checkouts) == 1 else None
    evidence(checkout and completed_step(steps, checkouts[0]) == 'success',
             'production checkout is not bound to the expected PR, head and base')
    sha = checkout[1]
    if sha != head:
        merge = api(f'repos/{repo}/git/commits/{sha}')
        evidence(merge['sha'] == sha and [p['sha'] for p in merge['parents']] == [base, head],
                 'production merge checkout does not have the expected base and head parents')
    evidence(all(record['head_sha'] in (head, sha) for record in (run, job, check)),
             'production workflow, job or check ran for a different revision')

    protocol = completed_step(steps, PROTOCOL_STEP)
    protocol_failure = completed_step(steps, PROTOCOL_CLASSIFIER)
    protocol_environment = completed_step(steps, PROTOCOL_ENVIRONMENT_CLASSIFIER)
    browser = completed_step(steps, BROWSER_STEP)
    product = completed_step(steps, PRODUCT_CLASSIFIER)
    environment = completed_step(steps, ENVIRONMENT_CLASSIFIER)
    if (conclusion == 'FAILURE' and protocol == 'failure'
            and (browser, product, environment) == ('skipped', 'skipped', 'skipped')):
        if (protocol_failure, protocol_environment) == ('success', 'skipped'):
            return 'rework', 'browser check exit protocol tests failed'
        if (protocol_failure, protocol_environment) == ('skipped', 'success'):
            return 'environment-error', 'browser check protocol environment failed; a new CI attempt is needed'
    if (protocol, protocol_failure, protocol_environment) != ('success', 'skipped', 'skipped'):
        return 'environment-error', 'browser check exit protocol classification is missing or inconsistent'
    if conclusion == 'SUCCESS' and (browser, product, environment) == ('success', 'skipped', 'skipped'):
        return 'passed', None
    if conclusion == 'FAILURE' and browser == 'failure':
        if (product, environment) == ('success', 'skipped'):
            return 'rework', 'production browser build or behavior check failed'
        if (product, environment) == ('skipped', 'success'):
            return 'environment-error', 'production browser environment failed; a new CI attempt is needed'
    return 'environment-error', 'production failure classification is missing or inconsistent'


def classify_required_check(items):
    if len(items) > 1:
        workflows = {i.get('workflowName') for i in items}
        dates = [i.get('startedAt') or i.get('createdAt') for i in items]
        if (len(workflows) != 1 or None in workflows or '' in workflows
                or not all(d and d >= '1970' for d in dates)
                or len(set(dates)) != len(dates)):
            return 'environment-error', 'ambiguous duplicate check contexts'
        item = items[dates.index(max(dates))]
    else:
        item = items[0]
    state = item.get('status') or item.get('state')
    conclusion = item.get('conclusion') if 'conclusion' in item else state
    if state in PENDING:
        return 'waiting', state
    if conclusion == 'SUCCESS' and state in ('COMPLETED', 'SUCCESS'):
        return 'passed', None
    if conclusion in ('FAILURE', 'ERROR'):
        return 'rework', conclusion
    return 'environment-error', f'check state {state} with conclusion {conclusion}'


def evaluate(info, head, base, required, *, repo=None, pr=None, api=None):
    if info.get('state') != 'OPEN':
        return {'status': 'environment-error', 'reason': 'PR is not open'}
    if info.get('headRefOid') != head or (base and info.get('baseRefOid') != base):
        return {'status': 'environment-error', 'reason': 'remote PR candidate/base differs from local evidence; reconcile publication or baseline before retry'}
    if PRODUCTION_CHECK in required and (
        not repo or info.get('url', '').lower() != f'https://github.com/{repo}/pull/{pr}'.lower()
    ):
        return {'status': 'environment-error', 'reason': 'GitHub response does not identify the expected PR'}
    checks = {}
    for item in info.get('statusCheckRollup') or []:
        name = item.get('name') or item.get('context')
        checks.setdefault(name, []).append(item)
    missing, incomplete = [], []
    for name in required:
        items = checks.get(name, [])
        if not items:
            missing.append(name)
            continue
        retryable = False
        try:
            if name == PRODUCTION_CHECK:
                status, reason = classify_production_check(
                    items, head, base or info.get('baseRefOid'), repo, pr, api,
                )
            else:
                status, reason = classify_required_check(items)
        except GitHubQueryError as error:
            status, reason, retryable = 'environment-error', str(error), error.retryable
        except ValueError as error:
            status, reason = 'environment-error', str(error)
        except (KeyError, TypeError, AttributeError):
            status, reason = 'environment-error', 'required check metadata is unreadable'
        if status != 'passed':
            incomplete.append({'name': name, 'status': status, 'reason': reason, 'retryable': retryable})

    environments = [result for result in incomplete if result['status'] == 'environment-error']
    if environments:
        status = 'environment-error'
    elif any(result['status'] == 'rework' for result in incomplete):
        status = 'rework'
    elif missing:
        status = 'environment-error'
    else:
        status = 'waiting' if incomplete else 'passed'
    return {'status': status, 'head': head, 'base': info.get('baseRefOid'),
            'required': required, 'missing': missing, 'not_successful': incomplete, 'url': info.get('url'),
            'registration_pending': bool(missing and not environments and status == 'environment-error'),
            'retryable': status == 'environment-error' and all(result['retryable'] for result in environments)}


def gh_json(arguments):
    try:
        result = subprocess.run(
            ['gh', *arguments], capture_output=True, text=True, timeout=15,
        )
    except subprocess.TimeoutExpired as error:
        raise GitHubQueryError('GitHub query timed out', retryable=True) from error
    if result.returncode:
        retryable = bool(re.search(
            r'\bHTTP (429|5[0-9]{2})\b|\b(connection reset|i/o timeout|TLS handshake timeout)\b',
            result.stderr, re.IGNORECASE,
        )) and not re.search(r'\bHTTP (401|403)\b', result.stderr, re.IGNORECASE)
        raise GitHubQueryError(
            'GitHub query failed; inspect service availability, gh authentication and access',
            retryable=retryable,
        )
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--pr', type=int, required=True)
    parser.add_argument('--required', action='append', required=True)
    parser.add_argument('--head')
    parser.add_argument('--base')
    parser.add_argument('--registration-timeout', type=int, default=60)
    args = parser.parse_args()
    try:
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repo) or args.pr <= 0:
            raise ValueError('invalid repository or PR')
        if os.environ.get('WORKFLOW_REQUEST'):
            candidate = json.loads(Path(os.environ['WORKFLOW_REQUEST']).read_text())['candidate']
            head, base = candidate['head'], candidate['base']
        else:
            head, base = args.head, args.base
        if not head or not re.fullmatch(r'[a-f0-9]{40,64}', head):
            raise ValueError('exact --head or runner WORKFLOW_REQUEST is required')
        if base and not re.fullmatch(r'[a-f0-9]{40,64}', base):
            raise ValueError('invalid exact base SHA')
        if not 0 <= args.registration_timeout <= 600:
            raise ValueError('registration-timeout must be 0..600 seconds')
        deadline = time.monotonic() + args.registration_timeout
        while True:
            info = gh_json(['pr', 'view', str(args.pr), '--repo', f'github.com/{args.repo}',
                            '--json', 'state,url,headRefOid,baseRefOid,statusCheckRollup'])
            verdict = evaluate(
                info, head, base, args.required, repo=args.repo, pr=args.pr,
                api=lambda endpoint: gh_json(['api', '--hostname', 'github.com', endpoint]),
            )
            if not verdict.get('registration_pending'):
                break
            if time.monotonic() >= deadline:
                verdict['reason'] = 'required checks did not register within the bounded wait; inspect CI triggers'
                break
            time.sleep(min(5, max(0, deadline-time.monotonic())))
        print(json.dumps(verdict,ensure_ascii=False,indent=2))
        return {'passed': 0, 'rework': 1, 'waiting': 75, 'environment-error': 2}[verdict['status']]
    except (ValueError, KeyError, TypeError, OSError, AttributeError) as exc:
        print(json.dumps({'status': 'environment-error', 'reason': str(exc),
                          'retryable': isinstance(exc, GitHubQueryError) and exc.retryable},
                         ensure_ascii=False))
        return 2


if __name__ == '__main__':sys.exit(main())
