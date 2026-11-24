import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('router', ROOT/'agent_router.py')
router = importlib.util.module_from_spec(spec)
spec.loader.exec_module(router)


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root/'repo'
        self.repo.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        (self.repo/'spec.md').write_text('Keep existing behavior.\n')
        self.git('add', 'spec.md')
        self.git('commit', '-qm', 'fixture')
        head = self.git('rev-parse', 'HEAD').strip()
        self.request = self.root/'state/runs/one/request.json'
        self.request.parent.mkdir(parents=True)
        self.request.write_text(json.dumps({'run_id':'one','repo':str(self.repo),'candidate':{
            'head':head,'base':head,'id':'candidate','spec':{'spec.md':'hash'}}}))
        self.instructions = self.root/'scope.md'
        self.instructions.write_text('Work within scope.\n')
        self.primary = self.root/'codex'
        self.fallback = self.root/'claude'
        self.policy = self.root/'policy.json'
        self.config = {'codex':str(self.primary),'claude':str(self.fallback),'codex_attempts':2,
                       'backoff_seconds':0,'attempt_timeout':3,'total_timeout':10,
                       'fault_injection':'unit-test provider fixtures', 'write_paths':['answer.txt']}
        self.provider(self.primary, "print(json.dumps({'type':'error','message':'Selected model is at capacity. Please try a different model.'}),flush=True)\ntime.sleep(10)")
        self.provider(self.fallback, "print(json.dumps({'type':'result','is_error':False,'session_id':'real-fixture-session','structured_output':{'candidate_id':'candidate','decision':'pass','findings':[]}}))")

    def tearDown(self):
        self.tmp.cleanup()

    def git(self,*args):
        return subprocess.check_output(['git','-C',str(self.repo),*args],text=True,stderr=subprocess.DEVNULL)

    def provider(self,path,body):
        path.write_text('#!'+sys.executable+'\nimport sys,json,time,os\nfrom pathlib import Path\n'+body+'\n')
        path.chmod(0o755)

    def command(self,mode='review'):
        self.policy.write_text(json.dumps(self.config))
        return [sys.executable,str(ROOT/'agent_router.py'),mode,'--policy',str(self.policy),
                '--instructions',str(self.instructions)]

    def run_router(self,mode='review'):
        return subprocess.run(self.command(mode),env={**os.environ,'WORKFLOW_REQUEST':str(self.request)},
                              text=True,capture_output=True,timeout=15)

    def journal(self):
        return json.loads((self.request.parent/'agents/journal.json').read_text())

    def test_capacity_retries_then_real_fallback_contract(self):
        result=self.run_router()
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual([a['provider'] for a in self.journal()['attempts']],['codex','codex','claude'])
        self.assertEqual(self.journal()['selected_provider'],'claude')
        self.assertIn('capacity-retry',result.stderr)
        self.assertIn('capacity-fallback',result.stderr)
        self.assertEqual(json.loads(result.stdout)['reviewer'],'claude session real-fixture-session')

    def test_non_capacity_failures_do_not_retry_or_switch(self):
        self.provider(self.primary,"print(json.dumps({'type':'error','message':'401 unauthorized or permission denied'}))\nsys.exit(1)")
        result=self.run_router()
        self.assertEqual(result.returncode,2)
        self.assertEqual(len(self.journal()['attempts']),1)

    def test_quoted_capacity_in_agent_content_is_not_service_failure(self):
        self.provider(self.primary,"print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'Selected model is at capacity'}}))\nsys.exit(1)")
        self.assertEqual(self.run_router().returncode,2)
        self.assertEqual(len(self.journal()['attempts']),1)

    def test_partial_work_blocks_switch_even_if_git_stays_clean(self):
        self.provider(self.primary,"print(json.dumps({'type':'item.started','item':{'type':'command_execution','command':'external action'}}),flush=True)\nprint(json.dumps({'type':'error','message':'Selected model is at capacity'}),flush=True)\ntime.sleep(10)")
        self.assertEqual(self.run_router('work').returncode,2)
        self.assertIn('reconcile',self.journal()['reason'])
        self.assertEqual(len(self.journal()['attempts']),1)

    def test_dirty_work_preserved_and_no_fallback(self):
        self.provider(self.primary,"Path('answer.txt').write_text('partial')\nprint(json.dumps({'type':'error','message':'Selected model is at capacity'}),flush=True)\ntime.sleep(10)")
        self.assertEqual(self.run_router('work').returncode,2)
        self.assertEqual((self.repo/'answer.txt').read_text(),'partial')
        self.assertEqual(len(self.journal()['attempts']),1)

    def test_fallback_capacity_exhaustion_stops(self):
        self.provider(self.fallback,"print(json.dumps({'type':'result','is_error':True,'result':'overloaded_error'}),flush=True)\ntime.sleep(10)")
        self.assertEqual(self.run_router().returncode,2)
        self.assertEqual(len(self.journal()['attempts']),3)

    def test_timeout_is_not_assumed_capacity(self):
        self.config['attempt_timeout']=1
        self.provider(self.primary,'time.sleep(10)')
        self.assertEqual(self.run_router().returncode,2)
        self.assertEqual(len(self.journal()['attempts']),1)
        self.assertIn('timeout',self.journal()['reason'])

    def test_cancel_kills_provider_and_does_not_fallback(self):
        marker=self.root/'pid'
        self.provider(self.primary,"Path("+repr(str(marker))+").write_text(str(os.getpid()))\ntime.sleep(10)")
        proc=subprocess.Popen(self.command(),env={**os.environ,'WORKFLOW_REQUEST':str(self.request)},stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            deadline=time.monotonic()+5
            while not marker.exists() and time.monotonic()<deadline:time.sleep(.02)
            self.assertTrue(marker.exists())
            proc.send_signal(signal.SIGTERM)
            output,error=proc.communicate(timeout=6)
            self.assertEqual(proc.returncode,2,(output,error))
            self.assertEqual(len(self.journal()['attempts']),1)
            attempt=self.journal()['attempts'][0]
            self.assertEqual(attempt['reason'],'cancelled')
            self.assertIsNotNone(attempt['returncode'])
            self.assertIn('finished_at',attempt)
            self.assertTrue((self.request.parent/'agents/01-codex/result.json').exists())
            with self.assertRaises(ProcessLookupError):os.kill(int(marker.read_text()),0)
        finally:
            if proc.poll() is None:proc.kill();proc.communicate()

    def test_wrong_candidate_cannot_pass(self):
        self.provider(self.fallback,"print(json.dumps({'type':'result','is_error':False,'session_id':'s','structured_output':{'candidate_id':'wrong','decision':'pass','findings':[]}}))")
        self.assertEqual(self.run_router().returncode,2)

    def test_review_rework_is_not_capacity_retry(self):
        self.provider(self.fallback,"print(json.dumps({'type':'result','is_error':False,'session_id':'s','structured_output':{'candidate_id':'candidate','decision':'rework','findings':['bug']}}))")
        result=self.run_router()
        self.assertEqual(result.returncode,0)
        self.assertEqual(json.loads(result.stdout)['decision'],'rework')
        self.assertEqual(len(self.journal()['attempts']),3)

    def test_same_request_cannot_replay_provider_actions(self):
        self.assertEqual(self.run_router().returncode,0)
        self.assertEqual(self.run_router().returncode,2)
        self.assertEqual(len(self.journal()['attempts']),3)

    def test_work_fallback_commits_only_allowed_changes(self):
        self.provider(self.fallback,"Path('answer.txt').write_text('42\\n')\nprint(json.dumps({'type':'result','is_error':False,'session_id':'s','structured_output':{'candidate_id':'candidate','decision':'completed','summary':'wrote answer'}}))")
        result=self.run_router('work')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual((self.repo/'answer.txt').read_text(),'42\n')
        self.assertFalse(self.git('status','--porcelain').strip())
        self.assertEqual(self.git('show','--format=','--name-only','HEAD').strip(),'answer.txt')

    def test_out_of_scope_edits_not_committed_or_discarded(self):
        self.provider(self.fallback,"Path('other.txt').write_text('keep')\nprint(json.dumps({'type':'result','is_error':False,'session_id':'s','structured_output':{'candidate_id':'candidate','decision':'completed','summary':'wrote other'}}))")
        self.assertEqual(self.run_router('work').returncode,2)
        self.assertEqual((self.repo/'other.txt').read_text(),'keep')
        self.assertEqual(self.git('log','-1','--format=%s').strip(),'fixture')

    def test_transport_capacity_diagnostic_recognized(self):
        action,capacity=router.classify_line('2026-11-24 WARN codex_core::responses_retry: stream disconnected - retrying sampling_error=Selected model is at capacity.','stderr')
        self.assertFalse(action)
        self.assertTrue(capacity)

    def test_provider_attachment_tampering_invalidates_receipt(self):
        spec=importlib.util.spec_from_file_location('loop',ROOT/'loop.py')
        loop=importlib.util.module_from_spec(spec);spec.loader.exec_module(loop)
        files={name:self.root/name for name in ['out','err','journal']}
        for p in files.values():p.write_text('original')
        r={'stdout':'out','stderr':'err','stdout_sha256':loop.sha(files['out'].read_bytes()),
           'stderr_sha256':loop.sha(files['err'].read_bytes()),'attachments':{'journal':loop.sha(files['journal'].read_bytes())}}
        self.assertTrue(loop.receipt_valid(r,self.root))
        files['journal'].write_text('changed')
        self.assertFalse(loop.receipt_valid(r,self.root))

    def test_second_codex_attempt_succeeds_without_fallback(self):
        marker=self.root/'attempt-count'
        self.provider(self.primary, "counter=Path("+repr(str(marker))+")\n"+
                      "if not counter.exists():\n counter.write_text('one')\n print(json.dumps({'type':'error','message':'Selected model is at capacity'}),flush=True)\n time.sleep(10)\n"+
                      "else:\n Path(sys.argv[sys.argv.index('-o')+1]).write_text(json.dumps({'candidate_id':'candidate','decision':'pass','findings':[]}))\n print(json.dumps({'type':'thread.started','thread_id':'codex-retry-session'}))")
        result=self.run_router()
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual([a['provider'] for a in self.journal()['attempts']],['codex','codex'])
        self.assertEqual(json.loads(result.stdout)['reviewer'],'codex session codex-retry-session')

    def test_staged_out_of_scope_change_is_not_committed(self):
        self.provider(self.fallback, "import subprocess\noriginal=Path('spec.md').read_text()\nPath('spec.md').write_text('staged unauthorized')\nsubprocess.run(['git','add','spec.md'],check=True)\nPath('spec.md').write_text(original)\nPath('answer.txt').write_text('42')\nprint(json.dumps({'type':'result','is_error':False,'session_id':'s','structured_output':{'candidate_id':'candidate','decision':'completed','summary':'done'}}))")
        self.assertEqual(self.run_router('work').returncode,2)
        self.assertIn('index',self.journal()['reason'])
        self.assertEqual(self.git('log','-1','--format=%s').strip(),'fixture')
        self.assertEqual(self.git('show',':spec.md'),'staged unauthorized')

    def test_capacity_drains_backlogged_tool_event_before_switch(self):
        # A TERM handler emits a queued event on the other stream during shutdown.
        # Switching before draining that stream would repeat an unknown action.
        self.provider(self.primary, "import signal\ndef end(signum,frame):\n sys.stdout.write('x'*70000+'\\n')\n print(json.dumps({'type':'item.started','item':{'type':'command_execution'}}),flush=True)\n sys.exit(0)\nsignal.signal(signal.SIGTERM,end)\nprint(json.dumps({'type':'error','message':'Selected model is at capacity'}),file=sys.stderr,flush=True)\ntime.sleep(10)")
        result=self.run_router('work')
        self.assertEqual(result.returncode,2,result.stdout+result.stderr)
        self.assertEqual(len(self.journal()['attempts']),1)
        # Either we observe the event, or shutdown cannot drain it: neither may replay.
        self.assertNotEqual(self.journal()['status'],'completed')

    def test_worker_timeout_stops_term_ignoring_descendant(self):
        import fcntl
        runs=self.root/'worker-state/runs/timeout'
        runs.mkdir(parents=True)
        tick=self.root/'ticks'
        child=self.root/'descendant.py'
        child.write_text("import signal,time\nfrom pathlib import Path\nsignal.signal(signal.SIGTERM,signal.SIG_IGN)\np=Path("+repr(str(tick))+")\nwhile True:\n with p.open('a') as f:f.write('tick\\n')\n time.sleep(.02)\n")
        parent=self.root/'parent.py'
        parent.write_text("import subprocess,sys,time\nsubprocess.Popen([sys.executable,"+repr(str(child))+"])\ntime.sleep(30)\n")
        request=runs/'request.json'
        request.write_text(json.dumps({'run_id':'timeout','repo':str(self.repo),'candidate':{'id':'c'},'step':{'argv':[sys.executable,str(parent)],'timeout':1}}))
        with (self.root/'lock').open('w') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            result=subprocess.run([sys.executable,str(ROOT/'loop.py'),'_worker',str(request),str(lock.fileno())],pass_fds=(lock.fileno(),),capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        receipt=json.loads((runs/'result.json').read_text())
        self.assertTrue(receipt['timeout'])
        size=tick.stat().st_size
        time.sleep(.2)
        self.assertEqual(tick.stat().st_size,size,'descendant must stop writing after timeout receipt')

    def test_cancel_during_capacity_shutdown_still_closes_attempt(self):
        marker=self.root/'started'
        self.provider(self.primary,"import signal\nsignal.signal(signal.SIGTERM,signal.SIG_IGN)\nPath("+repr(str(marker))+").write_text('ready')\nprint(json.dumps({'type':'error','message':'Selected model is at capacity'}),flush=True)\ntime.sleep(10)")
        proc=subprocess.Popen(self.command(),env={**os.environ,'WORKFLOW_REQUEST':str(self.request)},stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            deadline=time.monotonic()+5
            while not marker.exists() and time.monotonic()<deadline:time.sleep(.02)
            self.assertTrue(marker.exists())
            time.sleep(.2)
            proc.send_signal(signal.SIGTERM)
            output,error=proc.communicate(timeout=6)
            self.assertEqual(proc.returncode,2,(output,error))
            attempt=self.journal()['attempts'][0]
            self.assertEqual(len(self.journal()['attempts']),1)
            self.assertEqual(attempt['reason'],'cancelled')
            self.assertIn('finished_at',attempt)
            self.assertIn('stdout_sha256',attempt)
            self.assertTrue((self.request.parent/'agents/01-codex/result.json').exists())
        finally:
            if proc.poll() is None:proc.kill();proc.communicate()


if __name__=='__main__':unittest.main()
