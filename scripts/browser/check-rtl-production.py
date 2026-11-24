#!/usr/bin/env python3
"""Build and verify the actual production application; always stop the preview."""
import os
from pathlib import Path
import subprocess
import time
import urllib.request

repo = Path(__file__).resolve().parents[2]
artifacts = Path(os.environ.get('ARTIFACT_DIR', repo / 'test-results/rtl-opacity')).resolve()
artifacts.mkdir(parents=True, exist_ok=True)
env = {**os.environ, 'VITE_APP_ENABLE_ESLINT': 'false', 'VITE_APP_DISABLE_SENTRY': 'true',
       'ARTIFACT_DIR': str(artifacts), 'BASE_URL': 'http://127.0.0.1:5173'}
vite = str(repo / 'node_modules/.bin/vite')
subprocess.run([vite, 'build'], cwd=repo / 'excalidraw-app', env=env, check=True, timeout=600)
with (artifacts / 'preview.log').open('w') as log:
    server = subprocess.Popen([vite, 'preview', '--host', '127.0.0.1', '--port', '5173', '--strictPort'],
                              cwd=repo / 'excalidraw-app', env=env, stdout=log, stderr=log)
    try:
        deadline = time.monotonic() + 30
        while True:
            if server.poll() is not None:
                raise RuntimeError('preview exited; inspect preview.log')
            try:
                with urllib.request.urlopen(env['BASE_URL'], timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError('preview did not start in 30 seconds')
            time.sleep(.2)
        subprocess.run(['node', 'scripts/browser/rtl-opacity.mjs'], cwd=repo, env=env, check=True, timeout=300)
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()
