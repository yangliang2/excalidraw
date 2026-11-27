"""Requirement-level budgets for the cooperative, single-host runner.

The Git common directory owns the ledger, not a replaceable plan/state folder.
Caller holds workflow-loop.lock for every read/modify/write transaction.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

BASE_REPAIRS = 5
EXTRA_REPAIRS = 3
ENV_RETRIES = 3


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def write(path, value):
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex)
    with tmp.open('x') as out:
        json.dump(value, out, indent=2)
        out.flush()
        os.fsync(out.fileno())
    os.replace(tmp, path)


def schema(mode):
    props = {'candidate_id': {'type': 'string'},
             'decision': {'type': 'string', 'enum': ['proceed', 'human']},
             'rationale': {'type': 'string'},
             'evidence_runs': {'type': 'array', 'items': {'type': 'string'}}}
    if mode == 'assess':
        item = {'type': 'object', 'properties': {
            'id': {'type': 'string'}, 'family': {'type': 'string'},
            'severity': {'type': 'integer', 'minimum': 1, 'maximum': 3},
            'summary': {'type': 'string'}},
            'required': ['id', 'family', 'severity', 'summary'], 'additionalProperties': False}
        props.update(scope_unchanged={'type': 'boolean'},
                     findings={'type': 'array', 'items': item})
    else:
        props['plan'] = {'type': 'string'}
    return {'type': 'object', 'properties': props, 'required': list(props),
            'additionalProperties': False}


def validate(report, mode, candidate, evidence_runs):
    if (not isinstance(report, dict) or report.get('candidate_id') != candidate['id']
            or report.get('decision') not in ('proceed', 'human')
            or not isinstance(report.get('rationale'), str) or not report['rationale'].strip()
            or not isinstance(report.get('evidence_runs'), list)
            or sorted(report['evidence_runs']) != sorted(evidence_runs)):
        raise ValueError('budget report must bind candidate and all failed receipts')
    if mode == 'assess':
        findings = report.get('findings')
        if (not isinstance(report.get('scope_unchanged'), bool)
                or not isinstance(findings, list) or not findings):
            raise ValueError('assessment requires scope and nonempty structured findings')
        ids = []
        for f in findings:
            if (not isinstance(f, dict) or any(not isinstance(f.get(k), str) or not f[k].strip()
                    for k in ('id', 'family', 'summary'))
                    or type(f.get('severity')) is not int or f['severity'] not in (1, 2, 3)):
                raise ValueError('invalid structured finding')
            ids.append(f['id'])
        if len(ids) != len(set(ids)):
            raise ValueError('finding IDs must be unique')
    elif not isinstance(report.get('plan'), str) or not report['plan'].strip():
        raise ValueError('design review requires a concrete implementation/verification plan')


class Budget:
    def __init__(self, plan):
        self.plan = plan
        repo = plan['repo']
        def git(*args):
            return subprocess.check_output(['git', '-C', repo, *args], text=True).strip()
        common = Path(git('rev-parse', '--path-format=absolute', '--git-common-dir'))
        self.path = common / 'workflow-task-budgets.json'
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {
            'schema': 1, 'branches': {}, 'tasks': {}}
        if self.data.get('schema') != 1:
            raise ValueError('unknown task budget ledger schema')
        branch = subprocess.run(['git', '-C', repo, 'symbolic-ref', '--quiet', 'HEAD'], capture_output=True, text=True)
        self.branch = branch.stdout.strip() if branch.returncode == 0 else None
        self.task_id = plan.get('task_id')
        if self.branch is None and (self.task_id or self.data['tasks']):
            raise ValueError('task budgets require a named branch; detached checkout cannot bypass registration')
        bound = self.data['branches'].get(self.branch)
        if bound and bound != self.task_id:
            raise ValueError('branch already bound to task budget; continuation cannot rename or disable it')
        self.task = self.data['tasks'].get(self.task_id)
        if bound and self.task is None:
            raise ValueError('registered task ledger missing')

    def attach(self, candidate):
        if not self.task_id:
            return
        if self.task is not None and self.task.get('initial_work') and any(
                step['kind'] == 'work' and not step.get('invalidate_on_change', False)
                for step in self.plan['steps']):
            raise ValueError('continuation must omit completed implementation work; repairs use repair command')
        if self.task is None:
            self.task = {'repairs': [], 'observations': [], 'designs': [], 'extensions': [],
                         'environment_retries': [], 'imports': [], 'scope': self.scope(candidate)}
            self.data['tasks'][self.task_id] = self.task
        self.data['branches'][self.branch] = self.task_id
        self.save()

    def scope(self, candidate):
        return digest({'base': candidate['base'], 'spec': candidate['spec'],
                       'acceptance': sorted(self.plan['acceptance'])})

    def save(self):
        write(self.path, self.data)

    def context(self):
        return {'task_id': self.task_id, 'base_limit': BASE_REPAIRS,
                'extension_limit': EXTRA_REPAIRS, **self.task}

    def add_once(self, bucket, entry):
        if not any(x['run_id'] == entry['run_id'] for x in self.task[bucket]):
            self.task[bucket].append(entry)
            self.save()

    def reserve_repair(self, run_id, candidate):
        limit = BASE_REPAIRS + (EXTRA_REPAIRS if self.task['extensions'] else 0)
        if len(self.task['repairs']) >= limit:
            raise ValueError('requirement repair budget exhausted')
        self.add_once('repairs', {'run_id': run_id, 'candidate': candidate['id'], 'at': time.time()})

    def control_step(self, mode, episode):
        return {**self.plan['budget'][mode], 'id': '__' + mode + '__',
                'kind': mode, 'episode': episode}

    def choose(self, state, folder, failed, verify):
        records = [state['steps'][key] for key in failed]
        for record in records:
            verify(record, folder)
        runs = sorted(r['run_id'] for r in records)
        episode = digest({'candidate': state['candidate']['id'], 'runs': runs})
        observations = self.task['observations']
        current = next((x for x in observations if x['episode'] == episode), None)
        if current is None:
            return self.control_step('assess', episode)
        self.verify_control(current)
        report = current['report']
        if (report['decision'] == 'human' or not report['scope_unchanged']) and not self.resolved(current['run_id']):
            return {'status': 'awaiting-human', 'reason': 'assessment requires scope/product decision'}
        index = observations.index(current)
        if index:
            previous = observations[index - 1]
            self.verify_control(previous)
            repeated = {f['family'] for f in report['findings']} & {
                f['family'] for f in previous['report']['findings']}
            last_design_round = max((observations[x['observation_index']]['repair_count']
                                     for x in self.task['designs']), default=-1)
            if (repeated and current['repair_count'] > previous['repair_count']
                    and (last_design_round < 0 or current['repair_count'] - last_design_round >= 2)):
                return self.control_step('design', episode)
        design = next((x for x in reversed(self.task['designs']) if x['episode'] == episode), None)
        if design:
            self.verify_control(design)
            if design['report']['decision'] == 'human' and not self.resolved(design['run_id']):
                return {'status': 'awaiting-human', 'reason': 'design review requires product decision'}
        spent = len(self.task['repairs'])
        limit = BASE_REPAIRS + (EXTRA_REPAIRS if self.task['extensions'] else 0)
        if spent >= limit:
            if spent == BASE_REPAIRS and not self.task['extensions'] and index:
                prior = observations[index - 1]
                self.verify_control(prior)
                old = {f['id']: f['severity'] for f in prior['report']['findings']}
                new = {f['id']: f['severity'] for f in report['findings']}
                converging = (current['repair_count'] > prior['repair_count']
                              and set(new) < set(old) and all(new[k] <= old[k] for k in new)
                              and current['coverage_complete'] and prior['coverage_complete']
                              and prior['report']['scope_unchanged']
                              and self.scope(state['candidate']) == self.task['scope'])
                if converging:
                    self.task['extensions'].append({'from_run': prior['run_id'], 'to_run': current['run_id'],
                        'added': EXTRA_REPAIRS, 'reason': 'strict subset of blocker IDs, no severity/scope growth, complete checks/reviews'})
                    self.save()
                    return {'kind': 'repair'}
            return {'status': 'awaiting-human', 'reason': 'requirement repair budget exhausted; no evidenced convergence',
                    'repairs': spent, 'limit': limit}
        return {'kind': 'repair'}

    def verify_control(self, record):
        path = Path(record['receipt'])
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != record['receipt_sha256']:
            raise ValueError('budget assessment/design receipt changed')
        receipt = json.loads(path.read_text())
        folder = path.parents[2]
        for key in ('stdout', 'stderr'):
            f = folder / receipt[key]
            if not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest() != receipt[key + '_sha256']:
                raise ValueError('budget assessment/design evidence changed')
        for name, expected in receipt.get('attachments', {}).items():
            f = folder / name
            if not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest() != expected:
                raise ValueError('budget control attachment changed')

    def record_control(self, mode, state, folder, result, step):
        record = {**result, 'receipt': str((folder / result['receipt']).resolve()),
                  'episode': step['episode']}
        if mode == 'assess':
            record['repair_count'] = len(self.task['repairs'])
            record['coverage_complete'] = all(
                state['steps'][s['id']]['status'] in ('passed', 'failed')
                and state['steps'][s['id']].get('candidate') == state['candidate']
                for s in self.plan['steps'] if s['kind'] in ('check', 'review'))
            self.add_once('observations', record)
        else:
            record['observation_index'] = len(self.task['observations']) - 1
            self.add_once('designs', record)

    def retry(self, state, folder, key, verify, automatic):
        record = state['steps'][key]
        verify(record, folder)
        step = next(s for s in self.plan['steps'] if s['id'] == key)
        if step['kind'] not in ('check', 'review'):
            return None
        if automatic and not step.get('retry_safe', False):
            return None
        receipt = json.loads((folder / record['receipt']).read_text())
        try:
            info = json.loads((folder / receipt['stdout']).read_text())
        except (ValueError, OSError):
            info = {}
        if not isinstance(info, dict):
            info = {}
        if automatic and info.get('retryable') is not True:
            return None
        identity = digest({'step': key, 'candidate': state['candidate']['id']})
        attempts = [x for x in self.task['environment_retries'] if x['identity'] == identity]
        existing = next((x for x in attempts if x['failed_run'] == record['run_id']), None)
        if len(attempts) >= ENV_RETRIES and existing is None:
            return None
        delay = min(30, self.plan['budget'].get('backoff_seconds', 2) * 2 ** len(attempts))
        retry = next((x for x in attempts if x['failed_run'] == record['run_id']), None)
        if retry is None:
            retry = {'run_id': uuid.uuid4().hex, 'identity': identity, 'failed_run': record['run_id'],
                     'attempt': len(attempts) + 1, 'not_before': time.time() + delay}
            self.add_once('environment_retries', retry)
        time.sleep(max(0, min(30, retry['not_before'] - time.time())))
        return retry

    def reserve_initial_work(self, run_id):
        if self.task.get('initial_work'):
            raise ValueError('implementation already attempted; reconcile instead of replaying work')
        self.task['initial_work'] = run_id
        self.save()

    def import_history(self, source):
        if source.get('task_id') != self.task_id or not isinstance(source.get('states'), list) or not source['states']:
            raise ValueError('history import must name the task and source states')
        if self.task['repairs'] or self.task['observations'] or self.task['imports']:
            raise ValueError('import only into an unused task ledger; never replace accumulated history')
        anchors = source.get('spec_files', self.plan['spec_files'])
        if not isinstance(anchors, list) or not anchors or not set(anchors) <= set(self.plan['spec_files']):
            raise ValueError('import anchors must be confirmed task spec files')
        reservations = {}
        inputs = []
        for name in source['states']:
            path = Path(name).resolve()
            state = json.loads(path.read_text())
            inputs.append({'state': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
            entries = list(state['history'])
            if state.get('running'):
                entries.append(state['running'])
            for entry in entries:
                run_id = entry.get('run_id')
                if not run_id:
                    continue
                request_path = path.parent / 'runs' / run_id / 'request.json'
                request = json.loads(request_path.read_text())
                if request['run_id'] != run_id:
                    raise ValueError('import request/run mismatch')
                # Never adopt evidence from another requirement's specification/base.
                if request['candidate']['base'] != state['candidate']['base']:
                    raise ValueError('imported state/request scope mismatch')
                for spec in anchors:
                    expected = hashlib.sha256((Path(self.plan['repo']) / spec).read_bytes()).hexdigest()
                    if request['candidate']['spec'].get(spec) != expected:
                        raise ValueError('import must match the confirmed specification anchor')
                step = request['step']
                argv = step.get('argv', [])
                is_repair = step['kind'] == 'repair' or (
                    'repair' in argv and any(str(x).endswith('agent_router.py') for x in argv))
                if is_repair:
                    reservations[run_id] = {'run_id': run_id, 'candidate': request['candidate']['id'],
                        'imported_request': str(request_path),
                        'request_sha256': hashlib.sha256(request_path.read_bytes()).hexdigest()}
        self.task['repairs'] = list(reservations.values())
        self.task['imports'] = inputs
        self.task['initial_work'] = 'legacy-imported'
        self.save()
        return {'imported_repairs': len(reservations), 'states': len(inputs)}

    def resolved(self, run_id):
        accepted = False
        for decision in self.task.get('decisions', []):
            source = Path(decision['source'])
            if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != decision['source_sha256']:
                raise ValueError('budget human decision evidence changed')
            if decision['hold_run_id'] == run_id and decision['decision'] == 'accept':
                accepted = True
        return accepted

    def pending_hold(self):
        # Reports themselves are durable task-level holds, including reports
        # created before this entry point existed. New plan/run IDs cannot waive them.
        for record in self.task['observations'] + self.task['designs']:
            report = record['report']
            if (report['decision'] == 'human' or report.get('scope_unchanged') is False) and not self.resolved(record['run_id']):
                self.verify_control(record)
                return {'status': 'awaiting-human', 'reason': 'task-level budget decision required',
                        'task_id': self.task_id, 'hold_run_id': record['run_id'],
                        'held_candidate': record['candidate']['id'], 'rationale': report['rationale']}
        # Also verify already resolved decisions when no hold remains.
        self.resolved('')
        return None

    def decide(self, source_path, actor, decision, candidate):
        hold = self.pending_hold()
        if not hold or decision not in ('accept', 'reject'):
            raise ValueError('no unresolved task budget decision')
        source = json.loads(source_path.read_text())
        if (source.get('actor') != actor or source.get('decision') != decision
                or source.get('task_id') != self.task_id
                or source.get('hold_run_id') != hold['hold_run_id']
                or source.get('candidate_id') != candidate['id']
                or not isinstance(source.get('source_ref'), str) or not source['source_ref'].strip()
                or not isinstance(source.get('resolution'), str) or not source['resolution'].strip()):
            raise ValueError('decision must bind actor/task/hold/current candidate and actual resolution source')
        self.task.setdefault('decisions', []).append({**source, 'source': str(source_path.resolve()),
            'source_sha256': hashlib.sha256(source_path.read_bytes()).hexdigest(), 'at': time.time()})
        self.save()
        return {'status': 'rework' if decision == 'accept' else 'awaiting-human',
                'reason': 'budget decision recorded; counters and product acceptance unchanged',
                'task_id': self.task_id, 'hold_run_id': hold['hold_run_id']}
