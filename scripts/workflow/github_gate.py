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


def evaluate(info, head, base, required):
    if info.get('state') != 'OPEN':
        return {'status': 'rework', 'reason': 'PR is not open'}
    if info.get('headRefOid') != head or (base and info.get('baseRefOid') != base):
        return {'status': 'rework', 'reason': 'remote PR candidate/base differs from local evidence'}
    checks = {}
    for item in info.get('statusCheckRollup') or []:
        name = item.get('name') or item.get('context')
        checks.setdefault(name, []).append(item)
    missing, failed = [], []
    for name in required:
        items = checks.get(name, [])
        if not items:
            missing.append(name)
        else:
            if len(items) > 1:
                workflows = {i.get('workflowName') for i in items}
                dates = [i.get('startedAt') or i.get('createdAt') for i in items]
                if (len(workflows) != 1 or None in workflows or '' in workflows or not all(d and d >= '1970' for d in dates)
                        or len(set(dates)) != len(dates)):
                    failed.append({'name': name, 'reason': 'ambiguous duplicate check contexts'})
                    continue
                item = max(items, key=lambda i: i.get('startedAt') or i['createdAt'])
            else:
                item = items[0]
            success = ((item.get('status') == 'COMPLETED' and item.get('conclusion') == 'SUCCESS')
                       if 'conclusion' in item else item.get('state') == 'SUCCESS')
            if not success:
                failed.append({'name': name, 'status': item.get('status') or item.get('state'),
                               'conclusion': item.get('conclusion')})
    pending_states = ('IN_PROGRESS', 'QUEUED', 'PENDING', 'EXPECTED')
    terminal = any(f.get('status') not in pending_states for f in failed)
    status = ('rework' if terminal else 'environment-error' if missing
              else 'waiting' if failed else 'passed')
    return {'status': status, 'head': head, 'base': info.get('baseRefOid'),
            'required': required, 'missing': missing, 'not_successful': failed, 'url': info.get('url')}


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
        if not 0 <= args.registration_timeout <= 600:
            raise ValueError('registration-timeout must be 0..600 seconds')
        deadline = time.monotonic() + args.registration_timeout
        while True:
            result = subprocess.run(['gh','pr','view',str(args.pr),'--repo',args.repo,'--json',
                                     'state,url,headRefOid,baseRefOid,statusCheckRollup'],
                                    capture_output=True,text=True,timeout=30)
            if result.returncode:
                raise ValueError('GitHub query failed; check network, gh authentication and access (raw auth output withheld)')
            verdict = evaluate(json.loads(result.stdout),head,base,args.required)
            if verdict['status'] != 'environment-error' or not verdict.get('missing'):
                break
            if time.monotonic() >= deadline:
                verdict['reason'] = 'required checks did not register within the bounded wait; inspect CI triggers'
                break
            time.sleep(min(5, max(0, deadline-time.monotonic())))
        print(json.dumps(verdict,ensure_ascii=False,indent=2))
        return {'passed': 0, 'rework': 1, 'waiting': 75, 'environment-error': 2}[verdict['status']]
    except (ValueError,KeyError,TypeError,OSError,subprocess.TimeoutExpired) as exc:
        print(json.dumps({'status':'environment-error','reason':str(exc)},ensure_ascii=False))
        return 2


if __name__ == '__main__':sys.exit(main())
