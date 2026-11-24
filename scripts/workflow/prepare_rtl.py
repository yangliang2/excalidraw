#!/usr/bin/env python3
"""Prepare the real PR14 verification/handoff plan after implementation is committed."""
import argparse
import json
import shutil
from pathlib import Path
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('run_directory', type=Path)
args = parser.parse_args()
repo = Path(__file__).resolve().parents[2]
folder = args.run_directory.resolve()
if folder.is_relative_to(repo) or repo.is_relative_to(folder):
    parser.error('run_directory must be outside the repository')
folder.mkdir(parents=True, exist_ok=True)
with (folder/'agent-policy.json').open('x') as f:
    json.dump({'codex_attempts':2,'backoff_seconds':2,'attempt_timeout':900,'total_timeout':2400,
               'codex':shutil.which('codex'),'claude':shutil.which('claude')},f,indent=2)
with (folder/'agent-instructions.md').open('x') as f:
    f.write('Read-only independent review against both fixed specs and real runner evidence. Verify actual behavior and review sufficiency; no product approval. Report only actionable blockers; pass has empty findings.')
ac = ['AC-RTL', 'AC-SCENE', 'AC-CI', 'AC-HANDOFF']
def command(path):
    return [sys.executable, str(repo / path)]
plan = {'schema': 1, 'repo': str(repo), 'base_ref': '41f33a9581330d7eee664ad083274b1fe4576dea',
        'spec_files': ['docs/bugs/13-rtl-opacity/verification.md', 'docs/bugs/13-rtl-opacity/workflow-scope.md'],
        'acceptance': ac, 'max_repairs': 0, 'steps': [
        {'id': 'production-browser', 'kind': 'check', 'deps': [], 'ac': ac[:2], 'argv': command('scripts/browser/check-rtl-production.py'), 'timeout': 1200},
        {'id': 'size-gate-smoke', 'kind': 'check', 'deps': [], 'ac': ['AC-CI'], 'argv': ['node', '--test', 'scripts/check-package-size-smoke.mjs'], 'timeout': 60},
        {'id': 'publish', 'kind': 'work', 'deps': ['production-browser', 'size-gate-smoke'], 'ac': ['AC-HANDOFF'], 'argv': command('scripts/workflow/publish_rtl.py'), 'timeout': 120},
        {'id': 'github-ci', 'kind': 'check', 'deps': ['publish'], 'ac': ['AC-CI', 'AC-HANDOFF'], 'argv': command('scripts/workflow/github_gate.py') + ['--repo', 'yangliang2/excalidraw', '--pr', '14'] + sum([['--required', name] for name in ['browser', 'size', 'lint', 'coverage', 'semantic', 'label-scope']], []), 'timeout': 120},
        {'id': 'review', 'kind': 'review', 'deps': ['github-ci'], 'ac': ac, 'argv': command('scripts/workflow/claude_review.py'), 'timeout': 660},
        {'id': 'product', 'kind': 'human', 'deps': ['review'], 'ac': ac}]}
with (folder / 'plan.json').open('x') as output:
    json.dump(plan, output, indent=2)
print(folder / 'plan.json')
