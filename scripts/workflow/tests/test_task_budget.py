"""Real Git/runner fixtures; injected outcomes are not actual provider outages."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/app-workflow/scripts'
if not SCRIPTS.exists():
    SCRIPTS = Path(__file__).resolve().parents[1]


class TaskBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Budget fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        (self.repo / 'spec').write_text('Keep the approved scope and human merge gate.')
        (self.repo / 'attempt').write_text('0')
        self.git('add', '.')
        self.git('commit', '-qm', 'fixture')
        self.base = self.git('rev-parse', 'HEAD')
        self.path = self.root / 'plan.json'
        self.state = self.root / 'state'
        self.ledger_path = self.repo / '.git/workflow-task-budgets.json'
        self.review_code = "decision='rework';findings=['history defect']"
        self.assess_code = "findings=[dict(id='history',family='history',severity=2,summary='history defect')]"
        self.design_decision = 'proceed'
        self.check_code = "print('check passed')"
        self.configure()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], text=True,
                                       stderr=subprocess.DEVNULL).strip()

    def script(self, name, code):
        p = self.root / (name + '.py')
        p.write_text(code + '\n')
        return [sys.executable, str(p)]

    def configure(self):
        common = "import json,os\nfrom pathlib import Path\nr=json.loads(Path(os.environ['WORKFLOW_REQUEST']).read_text())\nn=int(Path('attempt').read_text())\n"
        review = self.script('review', common + self.review_code + "\nprint(json.dumps(dict(candidate_id=r['candidate']['id'],reviewer='explicit fixture',decision=decision,findings=findings)))")
        assess = self.script('assess', common + self.assess_code + "\nprint(json.dumps(dict(candidate_id=r['candidate']['id'],decision='proceed',rationale='fixture evidence',evidence_runs=r['failure_runs'],scope_unchanged=True,findings=findings)))")
        design = self.script('design', common + "\nprint(json.dumps(dict(candidate_id=r['candidate']['id'],decision=" + repr(self.design_decision) + ",rationale='repeated cause',evidence_runs=r['failure_runs'],plan='Revisit state transition and verify baseline controls.')))" )
        repair = self.script('repair', "import subprocess\nfrom pathlib import Path\np=Path('attempt');p.write_text(str(int(p.read_text())+1))\nsubprocess.run(['git','add','attempt'],check=True)\nsubprocess.run(['git','commit','-qm','fixture repair'],check=True)")
        self.plan = dict(schema=1, repo=str(self.repo), base_ref=self.base,
                         spec_files=['spec'], acceptance=['A'], task_id='fixture/repo#1',
                         budget=dict(assess={'argv': assess}, design={'argv': design}, backoff_seconds=0),
                         repair={'argv': repair}, steps=[
                             dict(id='check', kind='check', ac=['A'], deps=[], retry_safe=True,
                                  argv=self.script('check', self.check_code)),
                             dict(id='review', kind='review', ac=['A'], deps=['check'], argv=review),
                             dict(id='product', kind='human', ac=['A'], deps=['review'])])

    def cli(self, command, expected, *args):
        proc = subprocess.run([sys.executable, str(SCRIPTS / 'loop.py'), command,
                               '--plan', str(self.path), '--state', str(self.state), *args],
                              capture_output=True, text=True, timeout=50)
        self.assertEqual(proc.returncode, expected, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)

    def init(self):
        self.path.write_text(json.dumps(self.plan))
        return self.cli('init', 1)

    def ledger(self):
        return json.loads(self.ledger_path.read_text())['tasks']['fixture/repo#1']

    def test_default_five_repairs_and_repeated_family_design_review(self):
        self.init()
        result = self.cli('run', 3)
        self.assertEqual(result['repairs'], 5)
        self.assertEqual(int((self.repo / 'attempt').read_text()), 5)
        ledger = self.ledger()
        self.assertEqual(len(ledger['repairs']), 5)
        self.assertEqual(len(ledger['designs']), 3)
        self.assertEqual([x['observation_index'] for x in ledger['designs']], [1, 3, 5])
        self.assertFalse(ledger['extensions'])
        before = (self.state / 'state.json').read_bytes()
        self.cli('run', 3)
        self.assertEqual(before, (self.state / 'state.json').read_bytes())

    def test_convergence_adds_three_once_and_total_stops_at_eight(self):
        self.assess_code = "findings=[dict(id=x,family='history',severity=2,summary=x) for x in (['a','b'] if n<5 else ['a'])]"
        self.configure(); self.init()
        self.assertEqual(self.cli('run', 3)['limit'], 8)
        self.assertEqual(len(self.ledger()['repairs']), 8)
        self.assertEqual(len(self.ledger()['extensions']), 1)
        self.assertEqual(self.ledger()['extensions'][0]['added'], 3)

    def test_fewer_but_new_blockers_do_not_justify_extension(self):
        self.assess_code = "findings=[dict(id=x,family='history',severity=2,summary=x) for x in (['a','b'] if n<5 else ['new'])]"
        self.configure(); self.init(); self.cli('run', 3)
        self.assertEqual(len(self.ledger()['repairs']), 5)
        self.assertFalse(self.ledger()['extensions'])

    def test_increased_severity_prevents_extension(self):
        self.assess_code = "findings=[dict(id=x,family='history',severity=2 if n<5 else 3,summary=x) for x in (['a','b'] if n<5 else ['a'])]"
        self.configure(); self.init(); self.cli('run', 3)
        self.assertFalse(self.ledger()['extensions'])

    def test_new_state_and_plan_cannot_reset_requirement_budget(self):
        self.init(); self.cli('run', 3)
        self.state = self.root / 'continuation'
        self.path = self.root / 'continuation.json'
        self.plan['max_repairs'] = 10  # Legacy plan-local value cannot override task policy.
        self.init(); self.cli('run', 3)
        self.assertEqual(len(self.ledger()['repairs']), 5)
        self.plan['task_id'] = 'renamed-task'
        self.state = self.root / 'renamed'
        self.path.write_text(json.dumps(self.plan))
        self.assertIn('cannot rename', self.cli('init', 2)['reason'])
        self.plan.pop('task_id'); self.plan.pop('budget')
        self.path.write_text(json.dumps(self.plan))
        self.assertIn('cannot rename', self.cli('init', 2)['reason'])

    def test_environment_retries_three_without_product_budget_or_work_replay(self):
        calls = self.root / 'calls'
        self.check_code = "import json\nfrom pathlib import Path\np=Path(" + repr(str(calls)) + ");p.write_text(p.read_text()+'x' if p.exists() else 'x')\nprint(json.dumps(dict(status='environment-error',retryable=True)))\nraise SystemExit(2)"
        self.configure(); self.init(); self.cli('run', 2)
        self.assertEqual(calls.read_text(), 'xxxx')
        self.assertEqual(len(self.ledger()['environment_retries']), 3)
        self.assertFalse(self.ledger()['repairs'])
        self.assertIn('retry budget exhausted', self.cli('retry', 2, '--step', 'check')['reason'])
        self.state = self.root / 'new-state'
        self.init(); self.cli('run', 2)
        self.assertEqual(calls.read_text(), 'xxxxx')
        self.assertEqual(len(self.ledger()['environment_retries']), 3)

    def test_environment_retry_recovers_then_continues(self):
        calls = self.root / 'calls'
        self.check_code = "import json\nfrom pathlib import Path\np=Path(" + repr(str(calls)) + ");n=int(p.read_text()) if p.exists() else 0;p.write_text(str(n+1))\nprint(json.dumps(dict(retryable=True)))\nraise SystemExit(2 if n<2 else 0)"
        self.review_code = "decision='pass';findings=[]"
        self.configure(); self.init()
        self.assertEqual(self.cli('run', 3)['ready'], ['product'])
        self.assertEqual(len(self.ledger()['environment_retries']), 2)
        self.assertFalse(self.ledger()['repairs'])

    def test_unknown_environment_error_is_not_blindly_retried(self):
        self.check_code = "raise SystemExit(2)"
        self.configure(); self.init(); self.cli('run', 2)
        self.assertFalse(self.ledger()['environment_retries'])

    def test_design_can_escalate_without_another_repair(self):
        self.design_decision = 'human'
        self.configure(); self.init()
        self.assertIn('task-level budget decision', self.cli('run', 3)['reason'])
        self.assertEqual(len(self.ledger()['repairs']), 1)

    def test_human_hold_survives_new_state_and_requires_bound_resolution(self):
        self.design_decision = 'human'
        self.configure(); self.init()
        hold = self.cli('run', 3)
        self.assertEqual(len(self.ledger()['repairs']), 1)
        self.state = self.root / 'continuation'
        self.assertEqual(self.cli('init', 3)['hold_run_id'], hold['hold_run_id'])
        self.cli('run', 3)
        self.assertEqual(len(self.ledger()['repairs']), 1)
        state = json.loads((self.state / 'state.json').read_text())
        source = self.root / 'fixture-human-decision.json'
        decision = dict(actor='fixture-user', decision='accept', task_id=self.plan['task_id'],
                        hold_run_id=hold['hold_run_id'], candidate_id='wrong',
                        source_ref='explicit test fixture, not a real approval',
                        resolution='Fixture permits the proposed in-scope design; no product acceptance.')
        source.write_text(json.dumps(decision))
        args = ['--source', str(source), '--actor', 'fixture-user', '--decision', 'accept']
        self.cli('budget-decide', 2, *args)
        self.assertEqual(len(self.ledger()['repairs']), 1)
        decision['candidate_id'] = state['candidate']['id']
        source.write_text(json.dumps(decision))
        self.cli('budget-decide', 1, *args)
        self.assertEqual(len(self.ledger()['repairs']), 1)
        next_hold = self.cli('run', 3)
        self.assertNotEqual(next_hold['hold_run_id'], hold['hold_run_id'])
        self.assertEqual(len(self.ledger()['repairs']), 3)
        source.write_text('tampered decision')
        self.assertIn('decision evidence changed', self.cli('run', 2)['reason'])

    def test_non_object_retry_metadata_stays_environment_error(self):
        for raw in ('[]', 'null', '42', '"string"'):
            with self.subTest(raw=raw):
                self.check_code = 'print(' + repr(raw) + ')\nraise SystemExit(2)'
                self.configure()
                self.state = self.root / ('state-' + str(len(raw)))
                # Keep subtests distinct even when JSON strings have equal length.
                self.state = self.root / ('state-' + hashlib.sha256(raw.encode()).hexdigest()[:8])
                self.init()
                self.assertEqual(self.cli('run', 2)['status'], 'environment-error')
                self.assertFalse(self.ledger()['repairs'])
                self.assertFalse(self.ledger()['environment_retries'])

    def test_changed_assessment_evidence_blocks_resume(self):
        self.init(); self.cli('run', 3)
        record = self.ledger()['observations'][-1]
        receipt = json.loads(Path(record['receipt']).read_text())
        (self.state / receipt['stdout']).write_text('tampered')
        self.assertIn('evidence changed', self.cli('run', 2)['reason'])
        self.assertEqual(len(self.ledger()['repairs']), 5)

    def test_run_artifacts_are_isolated_and_receipted(self):
        self.check_code = "import os\nfrom pathlib import Path\np=Path(os.environ['ARTIFACT_DIR']);p.mkdir(exist_ok=True);(p/'scene.json').write_text(Path('attempt').read_text())"
        self.review_code = "decision='pass' if n>=2 else 'rework';findings=[] if n>=2 else ['history']"
        self.configure(); self.init(); self.cli('run', 3)
        state = json.loads((self.state / 'state.json').read_text())
        receipts = [json.loads((self.state / x['receipt']).read_text()) for x in state['history'] if x.get('step') == 'check']
        paths = [next(k for k in r['attachments'] if k.endswith('/scene.json')) for r in receipts]
        self.assertEqual(len(set(paths)), 3)
        self.assertEqual([(self.state / p).read_text() for p in paths], ['0', '1', '2'])
        for r in receipts:
            for path, digest in r['attachments'].items():
                self.assertEqual(hashlib.sha256((self.state / path).read_bytes()).hexdigest(), digest)
        (self.state / paths[-1]).write_text('changed')
        self.assertIn('log changed', self.cli('gate', 1)['reason'])

    def test_initial_implementation_is_not_replayed_by_new_state(self):
        self.review_code = "decision='pass';findings=[]"
        self.configure()
        self.plan['steps'].insert(0, dict(id='implement', kind='work', ac=['A'], deps=[], argv=self.script('implement', 'print(1)')))
        self.plan['steps'][1]['deps'] = ['implement']
        self.init(); self.cli('run', 3)
        self.state = self.root / 'new-state'
        self.path.write_text(json.dumps(self.plan))
        self.assertIn('omit completed implementation', self.cli('init', 2)['reason'])

    def test_import_legacy_repairs_preserves_reservations(self):
        modern = self.plan
        self.plan = {k: v for k, v in modern.items() if k not in ('task_id', 'budget')}
        self.plan['max_repairs'] = 1
        self.init(); self.cli('run', 3)
        old = self.state / 'state.json'
        self.plan = modern; self.state = self.root / 'modern'; self.init()
        source = self.root / 'import.json'
        source.write_text(json.dumps(dict(task_id='fixture/repo#1', states=[str(old), str(old)])))
        result = self.cli('budget-import', 1, '--source', str(source))
        self.assertEqual(result['imported_repairs'], 1)
        self.cli('run', 3)
        self.assertEqual(len(self.ledger()['repairs']), 5)
        self.assertEqual(int((self.repo / 'attempt').read_text()), 5)


if __name__ == '__main__':
    unittest.main()
