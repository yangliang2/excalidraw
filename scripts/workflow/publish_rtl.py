#!/usr/bin/env python3
"""Push only the authorized RTL pilot branch; never merge or force-push."""
import json
import os
from pathlib import Path
import subprocess

req = json.loads(Path(os.environ['WORKFLOW_REQUEST']).read_text())
repo = req['repo']
def git(*args):
    return subprocess.check_output(['git', '-C', repo, *args], text=True).strip()
if git('branch', '--show-current') != 'idea/13-rtl-opacity':
    raise SystemExit('expected RTL pilot branch')
if git('rev-parse', 'HEAD') != req['candidate']['head'] or git('status', '--porcelain'):
    raise SystemExit('candidate changed before publishing')
push_urls = git('remote', 'get-url', '--push', '--all', 'origin').splitlines()
if len(push_urls) != 1 or push_urls[0] not in ('https://github.com/yangliang2/excalidraw.git', 'git@github.com:yangliang2/excalidraw.git'):
    raise SystemExit('unexpected publication remote')
subprocess.run(['git', '-C', repo, 'push', push_urls[0], 'HEAD:refs/heads/idea/13-rtl-opacity'], check=True)
remote = git('ls-remote', push_urls[0], 'refs/heads/idea/13-rtl-opacity').split()[0]
if remote != req['candidate']['head']:
    raise SystemExit('remote head differs after push')
print(json.dumps({'head': remote, 'pr': 'https://github.com/yangliang2/excalidraw/pull/14'}))
