#!/usr/bin/env python3
"""Build in isolation and verify editor history in Chromium."""
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile


def stop_preview(server):
    server.terminate()
    try:
        server.wait(timeout=5)
    except subprocess.TimeoutExpired:
        server.kill()
        server.wait(timeout=5)


def main():
    repo = Path(__file__).resolve().parents[2]
    app = repo / 'excalidraw-app'
    artifacts = Path(
        os.environ.get('ARTIFACT_DIR')
        or os.environ.get('WORKFLOW_ARTIFACT_DIR')
        or repo / 'test-results/empty-text-history'
    ).resolve()
    env = {
        **os.environ,
        'VITE_APP_ENABLE_ESLINT': 'false',
        'VITE_APP_DISABLE_SENTRY': 'true',
        'ARTIFACT_DIR': str(artifacts),
        'BASE_URL': 'http://127.0.0.1:5176',
    }
    vite = str(repo / 'node_modules/.bin/vite')
    stage = 'build'

    try:
        artifacts.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='empty-text-production-') as build:
            subprocess.run(
                [vite, 'build', '--outDir', build, '--base', '/'],
                cwd=app, env=env, check=True, timeout=600,
            )
            stage = 'preview'
            marker_name = f'preview-marker-{secrets.token_hex(16)}.txt'
            marker_token = secrets.token_hex(32)
            Path(build, marker_name).write_text(marker_token, encoding='ascii')
            with (artifacts / 'server.log').open('w') as log:
                server = subprocess.Popen(
                    [vite, 'preview', '--outDir', build, '--host', '127.0.0.1',
                     '--port', '5176', '--strictPort'],
                    cwd=app, env=env, stdout=log, stderr=log,
                )
                try:
                    if server.poll() is not None:
                        raise OSError('preview exited; inspect server.log')
                    stage = 'browser'
                    subprocess.run(
                        ['node', 'scripts/browser/empty-text-history.mjs'],
                        cwd=repo, env={
                            **env,
                            'PREVIEW_PID': str(server.pid),
                            'PREVIEW_MARKER_NAME': marker_name,
                            'PREVIEW_MARKER_TOKEN': marker_token,
                        }, check=True, timeout=180,
                    )
                finally:
                    check_failed = sys.exc_info()[0] is not None
                    try:
                        stop_preview(server)
                    except (OSError, subprocess.TimeoutExpired) as error:
                        print(f'preview cleanup failed: {error}', file=sys.stderr)
                        if not check_failed:
                            raise
    except subprocess.CalledProcessError as error:
        print(f'{stage} failed: {error}', file=sys.stderr)
        code = error.returncode
        if code < 0 or code in (126, 127) or (stage == 'browser' and code == 2):
            return 2
        return 1
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f'{stage} environment error: {error}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
