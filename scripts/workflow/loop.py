#!/usr/bin/env python3
"""Single-host, cooperative workflow runner. Not a sandbox or approval authority."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def save(path, data):
    path = Path(path)
    tmp = path.with_name(path.name + '.tmp-' + uuid.uuid4().hex)
    with tmp.open('x') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.PIPE).decode().strip()


def load_plan(path):
    raw = Path(path).read_bytes()
    p = json.loads(raw)
    if p.get('schema') != 1:
        raise ValueError('plan schema must be 1')
    repo = Path(p['repo']).resolve()
    if Path(path).resolve().is_relative_to(repo):
        raise ValueError('plan must be outside candidate repository')
    if Path(git(repo, 'rev-parse', '--show-toplevel')).resolve() != repo:
        raise ValueError('repo must be the Git top level')
    p['repo'] = str(repo)
    ac = p['acceptance']
    if not ac or len(set(ac)) != len(ac) or not all(isinstance(x, str) and x for x in ac):
        raise ValueError('acceptance IDs must be nonempty and unique')
    if not p.get('spec_files'):
        raise ValueError('spec_files required')
    for name in p['spec_files']:
        f = (repo / name).resolve()
        if not f.is_relative_to(repo) or not f.is_file():
            raise ValueError('spec file must exist inside repo')
        git(repo, 'ls-files', '--error-unmatch', name)
    steps = p['steps']
    ids = [s['id'] for s in steps]
    if not steps or len(ids) != len(set(ids)):
        raise ValueError('steps must be nonempty and unique')
    for s in steps:
        if not isinstance(s['id'], str) or not s['id'] or s['kind'] not in ('work', 'check', 'review', 'human'):
            raise ValueError('invalid step')
        if not set(s.get('ac', [])) <= set(ac) or not s.get('ac'):
            raise ValueError('every step must reference known acceptance IDs')
        if not set(s.get('deps', [])) <= set(ids):
            raise ValueError('unknown dependency')
        if s['kind'] != 'human':
            validate_command(s)
    byid = {s['id']: s for s in steps}
    visited, active = set(), set()
    def visit(key):
        if key in active:
            raise ValueError('dependency cycle')
        if key in visited:
            return
        active.add(key)
        for dep in byid[key].get('deps', []):
            visit(dep)
        active.remove(key)
        visited.add(key)
    for key in ids:
        visit(key)
    for kind in ('check', 'review'):
        covered = {a for s in steps if s['kind'] == kind for a in s['ac']}
        if covered != set(ac):
            raise ValueError('each acceptance ID requires check and review coverage')
    if not any(s['kind'] == 'human' for s in steps):
        raise ValueError('at least one human handoff required')
    if not isinstance(p.get('max_repairs', 0), int) or not 0 <= p.get('max_repairs', 0) <= 10:
        raise ValueError('max_repairs must be 0..10')
    if p.get('repair'):
        validate_command(p['repair'])
    adapters = {}
    for command in [s for s in steps if s['kind'] != 'human'] + ([p['repair']] if p.get('repair') else []):
        for arg in command['argv']:
            f = Path(arg)
            if f.is_absolute() and f.is_file() and not f.resolve().is_relative_to(repo):
                adapters[str(f.resolve())] = sha(f.read_bytes())
    p['_adapter_hashes'] = adapters
    return p, sha(raw + json.dumps(adapters, sort_keys=True).encode())


def validate_command(s):
    if not isinstance(s.get('argv'), list) or not s['argv'] or not all(isinstance(x, str) and x for x in s['argv']):
        raise ValueError('argv must be a nonempty string array; shell strings are not accepted')
    if not isinstance(s.get('timeout', 300), int) or not 1 <= s.get('timeout', 300) <= 7200:
        raise ValueError('timeout must be 1..7200 seconds')


def snapshot(p):
    repo = p['repo']
    if git(repo, 'status', '--porcelain', '--untracked-files=all'):
        raise ValueError('candidate is dirty; preserve edits and commit before running')
    value = {'head': git(repo, 'rev-parse', 'HEAD'),
             'base': git(repo, 'rev-parse', p['base_ref'] + '^{commit}'),
             'spec': {n: sha((Path(repo)/n).read_bytes()) for n in p['spec_files']}}
    value['id'] = sha(json.dumps(value, sort_keys=True).encode())
    return value


def invalidate(p, state):
    for s in p['steps']:
        if s['kind'] != 'work':
            state['steps'][s['id']] = {'status': 'pending'}


def receipt_valid(r, folder):
    return all((folder / r[k]).is_file() and sha((folder / r[k]).read_bytes()) == r[k + '_sha256']
               for k in ('stdout', 'stderr'))


def finish(p, state, folder):
    running = state.get('running')
    if not running:
        return None
    result_path = folder/'runs'/running['run_id']/'result.json'
    if not result_path.exists():
        return {'status': 'awaiting-human', 'reason': 'execution outcome unknown; reconcile external effects before retry',
                'run_id': running['run_id']}
    r = read(result_path)
    if r.get('run_id') != running['run_id'] or not receipt_valid(r, folder):
        return {'status': 'environment-error', 'reason': 'missing or changed run evidence'}
    current = snapshot(p)
    step = running['step']
    kind = step['kind']
    outcome = 'passed' if r['returncode'] == 0 else 'failed'
    if r.get('returncode') == 75:
        outcome = 'waiting'
    if r.get('returncode') == 2 or r.get('timeout') or r.get('launch_error'):
        outcome = 'environment-error'
    if kind in ('check', 'review') and current != running['candidate']:
        outcome = 'environment-error'
    report = None
    if kind == 'review' and outcome == 'passed':
        try:
            report = json.loads((folder/r['stdout']).read_text())
            if (report['candidate_id'] != current['id'] or not report['reviewer']
                    or report['decision'] not in ('pass', 'rework', 'human')
                    or not isinstance(report['findings'], list)):
                raise ValueError('invalid review contract')
            if report['decision'] == 'pass' and report['findings']:
                raise ValueError('pass requires resolved findings')
            outcome = {'pass': 'passed', 'rework': 'failed', 'human': 'awaiting-human'}[report['decision']]
        except (ValueError, KeyError, TypeError):
            outcome = 'environment-error'
    if kind in ('work', 'repair') and (current['spec'] != running['candidate']['spec'] or current['base'] != running['candidate']['base']):
        outcome = 'environment-error'
        state['halt'] = {'status': 'awaiting-human', 'reason': 'work changed specification or baseline; review scope before refresh'}
    if kind in ('work', 'repair') and current != state['candidate']:
        invalidate(p, state)
        state['candidate'] = current
    result = {'status': outcome, 'run_id': r['run_id'], 'candidate': current,
              'receipt': str(result_path.relative_to(folder)), 'receipt_sha256': sha(result_path.read_bytes())}
    if report is not None:
        result['review'] = report
    state['history'].append({'step': step['id'], **result})
    state['running'] = None
    if kind == 'repair':
        if outcome == 'passed':
            invalidate(p, state)  # same-SHA repairs also require a fresh verification attempt
            for value in state['steps'].values():
                if value['status'] == 'failed':
                    value.clear()
                    value['status'] = 'pending'
        else:
            state['halt'] = {'status': 'environment-error' if outcome == 'environment-error' else 'awaiting-human',
                             'reason': 'repair failed; diagnose before another attempt', 'run_id': r['run_id']}
    else:
        state['steps'][step['id']] = result
    save(folder/'state.json', state)
    return None


def verify_evidence(state, folder):
    for key, s in state['steps'].items():
        if s['status'] != 'passed':
            continue
        if 'receipt' in s:
            path = folder / s['receipt']
            if not path.is_file() or sha(path.read_bytes()) != s['receipt_sha256']:
                return 'receipt changed for ' + key
            if not receipt_valid(read(path), folder):
                return 'run log changed for ' + key
        elif 'decision_source' in s:
            path = Path(s['decision_source'])
            if not path.is_file() or sha(path.read_bytes()) != s['source_sha256']:
                return 'human decision source changed for ' + key
    return None


def inspect(p, state, folder):
    for name, expected in p['_adapter_hashes'].items():
        if not Path(name).is_file() or sha(Path(name).read_bytes()) != expected:
            return {'status': 'environment-error', 'reason': 'external command adapter changed'}
    if state.get('running'):
        return {'status': 'environment-error', 'reason': 'pending execution receipt; run resume to reconcile'}
    if snapshot(p) != state['candidate']:
        return {'status': 'rework', 'reason': 'candidate/base/spec changed; explicit refresh required'}
    problem = verify_evidence(state, folder)
    if problem:
        return {'status': 'rework', 'reason': problem}
    if state.get('halt'):
        return state['halt']
    values = state['steps']
    for key, s in values.items():
        if s['status'] == 'environment-error':
            return {'status': 'environment-error', 'step': key}
    waiting = [k for k, v in values.items() if v['status'] == 'waiting']
    failed = [k for k, v in values.items() if v['status'] == 'failed']
    if failed:
        return {'status': 'rework', 'failed': failed}
    ready = [s['id'] for s in p['steps'] if values[s['id']]['status'] == 'pending'
             and all(values[d]['status'] == 'passed' for d in s.get('deps', []))]
    automatic = [k for k in ready if next(s for s in p['steps'] if s['id'] == k)['kind'] != 'human']
    if automatic:
        return {'status': 'rework', 'ready': automatic, 'reason': 'automatic steps remain'}
    blocked = [k for k, v in values.items() if v['status'] in ('awaiting-human', 'rejected')]
    if waiting:
        return {'status': 'environment-error', 'waiting': waiting, 'ready': blocked + ready,
                'candidate': state['candidate'], 'reason': 'external checks pending; resume polls without repair; ready lists available human decisions'}
    if blocked:
        return {'status': 'awaiting-human', 'ready': blocked + ready, 'candidate': state['candidate'], 'reason': 'record actual human review/decision for these steps'}
    if ready:
        return {'status': 'awaiting-human', 'ready': ready, 'candidate': state['candidate']}
    if all(v['status'] == 'passed' for v in values.values()):
        return {'status': 'ready', 'candidate': state['candidate'], 'notice': 'configured checks only; no merge or release performed'}
    return {'status': 'environment-error', 'reason': 'no runnable task'}


def worker(request_path, lock_fd):
    # Inherited flock stays held even if the coordinating process is terminated.
    req = read(request_path)
    folder = Path(request_path).parent
    result = {'run_id': req['run_id'], 'started_at': time.time(), 'returncode': None}
    env = os.environ.copy()
    env.update({'WORKFLOW_RUN_ID': req['run_id'], 'WORKFLOW_CANDIDATE_ID': req['candidate']['id'],
                'WORKFLOW_REQUEST': str(request_path)})
    try:
        with (folder/'stdout.log').open('wb') as out, (folder/'stderr.log').open('wb') as err:
            child = subprocess.Popen(req['step']['argv'], cwd=req['repo'], stdout=out, stderr=err,
                                     env=env, start_new_session=True)
            try:
                result['returncode'] = child.wait(timeout=req['step'].get('timeout', 300))
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
                result.update(returncode=124, timeout=True)
    except OSError as exc:
        result.update(returncode=127, launch_error=str(exc))
    for name in ('stdout', 'stderr'):
        path = folder/(name + '.log')
        if not path.exists():
            path.touch()
        result[name] = str(path.relative_to(folder.parent.parent))
        result[name + '_sha256'] = sha(path.read_bytes())
    result['finished_at'] = time.time()
    save(folder/'result.json', result)
    os.close(lock_fd)


def execute(p, state, folder, step, lock_fd):
    run_id = uuid.uuid4().hex
    target = folder/'runs'/run_id
    target.mkdir(parents=True)
    request = {'run_id': run_id, 'repo': p['repo'], 'candidate': state['candidate'], 'step': step,
               'prior_failures': [h for h in state['history'] if h.get('status') not in (None, 'passed')]}
    save(target/'request.json', request)
    state['running'] = {'run_id': run_id, 'candidate': state['candidate'], 'step': step}
    save(folder/'state.json', state)
    proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '_worker',
                             str(target/'request.json'), str(lock_fd)], pass_fds=(lock_fd,),
                            start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    proc.wait()
    return finish(p, state, folder)


def run(p, state, folder, lock_fd):
    unresolved = finish(p, state, folder)
    if unresolved:
        return unresolved
    polls = {}
    while True:
        result = inspect(p, state, folder)
        if result.get('waiting'):
            key = result['waiting'][0]
            if polls.get(key, 0) >= 2:
                return result
            polls[key] = polls.get(key, 0) + 1
            time.sleep(1)
            state['steps'][key] = {'status': 'pending'}
            save(folder/'state.json', state)
            step = next(s for s in p['steps'] if s['id'] == key)
        elif result.get('failed') and p.get('repair'):
            if state['repairs'] >= p.get('max_repairs', 0):
                return {'status': 'awaiting-human', 'reason': 'repair budget exhausted', 'failed': result['failed']}
            state['repairs'] += 1
            step = {'argv': p['repair']['argv'], 'timeout': p['repair'].get('timeout', 300), 'id': '__repair__', 'kind': 'repair'}
        elif result.get('ready') and result['status'] == 'rework':
            step = next(s for s in p['steps'] if s['id'] == result['ready'][0])
        else:
            return result
        unresolved = execute(p, state, folder, step, lock_fd)
        if unresolved:
            return unresolved


def main():
    if len(sys.argv) > 1 and sys.argv[1] == '_worker':
        worker(Path(sys.argv[2]), int(sys.argv[3])); return 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['init', 'gate', 'run', 'refresh', 'decide', 'reconcile'])
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--step')
    parser.add_argument('--source', type=Path)
    parser.add_argument('--actor')
    parser.add_argument('--decision', choices=['accept', 'reject', 'retry'])
    args = parser.parse_args()
    try:
        p, plan_sha = load_plan(args.plan)
        folder = args.state.resolve()
        repo = Path(p['repo'])
        if folder.is_relative_to(repo) or repo.is_relative_to(folder):
            raise ValueError('state and repo must be separate directories')
        folder.mkdir(parents=True, exist_ok=True)
        lockpath = Path(git(repo, 'rev-parse', '--path-format=absolute', '--git-common-dir'))/'workflow-loop.lock'
        with lockpath.open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('repository already has an active runner/worker')
            path = folder/'state.json'
            if args.command == 'init':
                if path.exists():
                    raise ValueError('state already exists; use run to resume')
                state = {'schema': 1, 'plan_sha256': plan_sha, 'candidate': snapshot(p), 'repairs': 0,
                         'steps': {s['id']: {'status': 'pending'} for s in p['steps']},
                         'history': [], 'running': None}
                save(path, state)
                result = inspect(p, state, folder)
            else:
                state = read(path)
                if state['plan_sha256'] != plan_sha:
                    raise ValueError('plan changed; review separately and initialize a new state directory')
                if args.command == 'run':
                    result = run(p, state, folder, lock.fileno())
                elif args.command == 'gate':
                    result = inspect(p, state, folder)
                elif args.command == 'refresh':
                    if state['running']:
                        raise ValueError('unresolved execution; reconcile first')
                    state['history'].append({'event': 'refresh', 'prior': state['candidate'], 'steps': state['steps']})
                    state['candidate'] = snapshot(p)
                    state['steps'] = {s['id']: {'status': 'pending'} for s in p['steps']}
                    state['halt'] = None
                    # Repair budget is lifetime per plan/state; refresh cannot reset it.
                    save(path, state)
                    result = inspect(p, state, folder)
                else:
                    if not args.source or not args.actor or not args.source.is_file():
                        raise ValueError('source file and actor required; CLI records a decision, does not authenticate it')
                    decision = {'actor': args.actor, 'decision_source': str(args.source.resolve()),
                                'source_sha256': sha(args.source.read_bytes()), 'at': time.time()}
                    source = read(args.source)
                    if (source.get('actor') != args.actor or source.get('decision') != args.decision
                            or not source.get('source_ref')):
                        raise ValueError('decision source must bind actor, decision and actual source_ref')
                    if args.command == 'reconcile':
                        if not state['running'] or args.decision != 'retry' or source.get('run_id') != state['running']['run_id']:
                            raise ValueError('reconcile only permits explicit retry after external-state inspection')
                        state['history'].append({'event': 'reconciled-retry', 'execution': state['running'], **decision})
                        state['running'] = None
                        save(path, state)
                        result = inspect(p, state, folder)
                    else:
                        status = inspect(p, state, folder)
                        if (status['status'] not in ('awaiting-human', 'environment-error') or args.step not in status.get('ready', [])
                                or args.decision not in ('accept', 'reject') or source.get('candidate_id') != state['candidate']['id']
                                or source.get('step') != args.step):
                            raise ValueError('human step is not ready for this candidate')
                        state['steps'][args.step] = {'status': 'passed' if args.decision == 'accept' else 'rejected',
                                                    'candidate': state['candidate'], **decision}
                        state['history'].append({'event': 'human-decision', 'step': args.step, **state['steps'][args.step]})
                        save(path, state)
                        result = inspect(p, state, folder)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return {'ready': 0, 'rework': 1, 'awaiting-human': 3, 'environment-error': 2}[result['status']]
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError) as exc:
        print(json.dumps({'status': 'environment-error', 'reason': str(exc)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.exit(main())
