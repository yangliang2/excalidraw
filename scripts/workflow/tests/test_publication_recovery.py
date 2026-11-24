"""Actual runner/Git fixtures: a post-publication repair must republish once."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class PublicationRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.repo=self.root/'repo';self.repo.mkdir()
        self.git('init','-q');self.git('config','user.name','Fixture');self.git('config','user.email','fixture@example.invalid')
        (self.repo/'spec').write_text('Keep publication aligned with the reviewed candidate.')
        (self.repo/'value').write_text('bad');self.git('add','.');self.git('commit','-qm','fixture')
        self.head=self.git('rev-parse','HEAD');self.state=self.root/'state';self.plan_path=self.root/'plan.json'
        self.publications=self.root/'publications';self.work_count=self.root/'work-count'
        implement=self.command('implement',f"from pathlib import Path\np=Path({str(self.work_count)!r});p.write_text(p.read_text()+'x' if p.exists() else 'x')")
        publish=self.command('publish',f"import subprocess\nfrom pathlib import Path\np=Path({str(self.publications)!r});head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()\nwith p.open('a') as f:f.write(head+'\\n')")
        check=self.command('check',f"import subprocess\nfrom pathlib import Path\nassert Path({str(self.publications)!r}).read_text().splitlines()[-1]==subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()")
        review=self.command('review',"import json,os\nfrom pathlib import Path\nok=Path('value').read_text()=='good'\nprint(json.dumps({'candidate_id':os.environ['WORKFLOW_CANDIDATE_ID'],'reviewer':'explicit fixture','decision':'pass' if ok else 'rework','findings':[] if ok else ['value requires repair']}))")
        repair=self.command('repair',"import subprocess\nfrom pathlib import Path\nPath('value').write_text('good')\nsubprocess.run(['git','add','value'],check=True)\nsubprocess.run(['git','commit','-qm','repair'],check=True)")
        def step(id,kind,deps,argv):return dict(id=id,kind=kind,deps=deps,ac=['AC-1'],argv=argv)
        self.plan=dict(schema=1,repo=str(self.repo),base_ref=self.head,spec_files=['spec'],acceptance=['AC-1'],max_repairs=1,repair={'argv':repair},steps=[step('implement','work',[],implement),{**step('publish','work',['implement'],publish),'invalidate_on_change':True},step('verify','check',['publish'],check),step('review','review',['verify'],review),dict(id='accept',kind='human',deps=['review'],ac=['AC-1'])])

    def git(self,*args):return subprocess.check_output(['git','-C',str(self.repo),*args],text=True,stderr=subprocess.DEVNULL).strip()
    def command(self,name,code):
        p=self.root/(name+'.py');p.write_text(code+'\n');return [sys.executable,str(p)]
    def cli(self,cmd,expected,env=None,extra=()):
        result=subprocess.run([sys.executable,str(ROOT/'loop.py'),cmd,'--plan',str(self.plan_path),'--state',str(self.state),*extra],capture_output=True,text=True,env=env,timeout=20)
        self.assertEqual(result.returncode,expected,result.stdout+result.stderr);return json.loads(result.stdout)
    def init(self):self.plan_path.write_text(json.dumps(self.plan));self.cli('init',1)
    def test_repair_republishes_new_head_without_repeating_implementation(self):
        self.init();result=self.cli('run',3)
        self.assertEqual(result['ready'],['accept'])
        self.assertEqual(self.publications.read_text().splitlines(),[self.head,self.git('rev-parse','HEAD')])
        self.assertNotEqual(self.head,self.git('rev-parse','HEAD'))
        self.assertEqual(self.work_count.read_text(),'x')
        self.assertEqual(json.loads((self.state/'state.json').read_text())['repairs'],1)
        self.cli('run',3)
        self.assertEqual(len(self.publications.read_text().splitlines()),2)
    def test_remote_head_mismatch_is_environment_error_without_repair(self):
        fake=self.root/'bin';fake.mkdir();gh=fake/'gh'
        info=dict(state='OPEN',headRefOid='0'*40,baseRefOid=self.head,statusCheckRollup=[])
        gh.write_text('#!'+sys.executable+'\nprint('+repr(json.dumps(info))+')\n');gh.chmod(0o755)
        self.plan['steps'][2]['argv']=[sys.executable,str(ROOT/'github_gate.py'),'--repo','fixture/project','--pr','1','--required','browser']
        self.init();result=self.cli('run',2,{**os.environ,'PATH':str(fake)+os.pathsep+os.environ['PATH']})
        self.assertEqual(result['status'],'environment-error')
        self.assertEqual(json.loads((self.state/'state.json').read_text())['repairs'],0)
        self.assertEqual((self.repo/'value').read_text(),'bad')
    def test_non_boolean_replay_policy_is_rejected(self):
        self.plan['steps'][1]['invalidate_on_change']='false';self.plan_path.write_text(json.dumps(self.plan))
        self.assertIn('boolean',self.cli('init',2)['reason'])

    def test_same_candidate_repair_rechecks_without_republishing(self):
        fixed=self.root/'fixed'
        self.plan['repair']['argv']=self.command('same-head-repair',f"from pathlib import Path\nPath({str(fixed)!r}).touch()")
        self.plan['steps'][3]['argv']=self.command('same-head-review',f"import json,os\nfrom pathlib import Path\nok=Path({str(fixed)!r}).exists()\nprint(json.dumps({{'candidate_id':os.environ['WORKFLOW_CANDIDATE_ID'],'reviewer':'explicit fixture','decision':'pass' if ok else 'rework','findings':[] if ok else ['retry verification']}}))")
        self.init();self.cli('run',3)
        self.assertEqual(self.publications.read_text().splitlines(),[self.head])
        self.assertEqual(self.work_count.read_text(),'x')
        state=json.loads((self.state/'state.json').read_text())
        self.assertEqual(len([x for x in state['history'] if x.get('step')=='verify']),2)

    def test_environment_check_retry_preserves_implementation_and_publication(self):
        restored=self.root/'remote-restored'
        self.plan['max_repairs']=0
        self.plan['steps'][2]['argv']=self.command('environment-check',f"from pathlib import Path\nraise SystemExit(0 if Path({str(restored)!r}).exists() else 2)")
        self.plan['steps'][3]['argv']=self.command('passing-review',"import json,os\nprint(json.dumps({'candidate_id':os.environ['WORKFLOW_CANDIDATE_ID'],'reviewer':'explicit fixture','decision':'pass','findings':[]}))")
        self.init();self.cli('run',2)
        before=json.loads((self.state/'state.json').read_text())
        self.cli('retry',2,extra=['--step','publish'])
        restored.touch();self.cli('retry',1,extra=['--step','verify']);self.cli('run',3)
        after=json.loads((self.state/'state.json').read_text())
        self.assertEqual(after['steps']['implement'],before['steps']['implement'])
        self.assertEqual(after['steps']['publish'],before['steps']['publish'])
        self.assertEqual(self.publications.read_text().splitlines(),[self.head])
        self.assertEqual(self.work_count.read_text(),'x')
        self.assertEqual(after['repairs'],0)

    def test_environment_retry_rejects_changed_candidate(self):
        self.plan['steps'][2]['argv']=self.command('environment-check',"raise SystemExit(2)")
        self.init();self.cli('run',2)
        (self.repo/'value').write_text('changed');self.git('add','value');self.git('commit','-qm','changed')
        self.assertIn('changed',self.cli('retry',2,extra=['--step','verify'])['reason'])

if __name__=='__main__':unittest.main()
