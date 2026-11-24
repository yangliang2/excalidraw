#!/usr/bin/env python3
"""Prepare the real-fork capacity-recovery pilot. Injection is explicit and recorded."""
import argparse
import json
from pathlib import Path
import shutil
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('run_directory', type=Path)
parser.add_argument('--inject-capacity', action='store_true')
args = parser.parse_args()
repo = Path(__file__).resolve().parents[2]
folder = args.run_directory.resolve()
if folder.is_relative_to(repo) or repo.is_relative_to(folder):
    parser.error('run_directory must be outside repository')
folder.mkdir(parents=True, exist_ok=True)
policy = {'codex_attempts': 2, 'backoff_seconds': 2, 'attempt_timeout': 900, 'total_timeout': 2400,
          'codex': shutil.which('codex'), 'claude': shutil.which('claude'),
          'write_paths': ['docs/bugs/13-rtl-opacity/agent-recovery.md']}
if args.inject_capacity:
    policy.update(codex=str(repo/'scripts/workflow/tests/capacity_fixture.py'),
                  fault_injection='explicit capacity fixture before real Claude; not a service outage')
instructions = '''Implement/review the agent-recovery-scope.md acceptance. For work/repair, create only agent-recovery.md: concise operational documentation based on agent_router.py and tests. Explain defaults, exact prepare/run commands, scope/commit limits, capacity-only fallback, partial-effect reconciliation, journal/receipt binding and injection-vs-real evidence. Use blank lines after Markdown headings to satisfy existing Prettier. Do not assert a live test passed unless its actual receipt exists. No other file changes and no Git commands; orchestrator commits the allowed file and runner executes verification separately.
For review, inspect the recovery implementation and specs independently. Existing RTL work was previously verified, but current CI must match current head. Differentiate explicit injection from real provider service capacity. Return concrete actionable findings, pass with an empty findings list if resolved. No product approval.
'''
policy_path = folder/'policy.json'
with policy_path.open('x') as f:json.dump(policy,f,indent=2)
with (folder/'instructions.md').open('x') as f:f.write(instructions)
ac = ['REC-1','REC-2','REC-3','REC-4']
def command(name):return [sys.executable,str(repo/'scripts/workflow'/name)]
def agent(mode):return command('agent_router.py')+[mode,'--policy',str(policy_path),'--instructions',str(folder/'instructions.md')]
plan={'schema':1,'repo':str(repo),'base_ref':'41f33a9581330d7eee664ad083274b1fe4576dea',
      'spec_files':['docs/bugs/13-rtl-opacity/verification.md','docs/bugs/13-rtl-opacity/agent-recovery-scope.md'],
      'acceptance':ac,'max_repairs':1,'repair':{'argv':agent('repair'),'timeout':2500},'steps':[
      {'id':'document-recovery','kind':'work','deps':[],'ac':ac,'argv':agent('work'),'timeout':2500},
      {'id':'recovery-tests','kind':'check','deps':['document-recovery'],'ac':ac,'argv':[sys.executable,'-m','unittest','discover','-s','scripts/workflow/tests','-v'],'timeout':120},
      {'id':'production-browser','kind':'check','deps':['document-recovery'],'ac':['REC-4'],'argv':[sys.executable,'scripts/browser/check-rtl-production.py'],'timeout':1200},
      {'id':'publish','kind':'work','deps':['recovery-tests','production-browser'],'ac':['REC-4'],'argv':command('publish_rtl.py'),'timeout':120},
      {'id':'github-ci','kind':'check','deps':['publish'],'ac':['REC-4'],'argv':command('github_gate.py')+['--repo','yangliang2/excalidraw','--pr','14']+sum([['--required',x] for x in ['agent-recovery','browser','coverage','lint','size','semantic','label-scope']],[]),'timeout':120},
      {'id':'review','kind':'review','deps':['github-ci'],'ac':ac,'argv':agent('review'),'timeout':2500},
      {'id':'product','kind':'human','deps':['review'],'ac':ac}]}
with (folder/'plan.json').open('x') as f:json.dump(plan,f,indent=2)
print(folder/'plan.json')
