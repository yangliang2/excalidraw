"""Simulated preview services exercising the Node guard without Chromium."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest


CHECKER = Path(__file__).with_name('empty-text-history.mjs')
MARKER = 'preview-marker.txt'
TOKEN = 'fixture-preview-token'


class PreviewOwnershipTests(unittest.TestCase):
    def run_checker(self, response, *, pid=None):
        paths = []

        class Preview(BaseHTTPRequestHandler):
            def do_GET(self):
                paths.append(self.path)
                response(self)

            def log_message(self, *args):
                pass

        with tempfile.TemporaryDirectory() as output, \
                ThreadingHTTPServer(('127.0.0.1', 0), Preview) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            loader = Path(output, 'loader.mjs')
            loader.write_text("""
import { writeFileSync } from 'node:fs';
export function resolve(specifier, context, nextResolve) {
  if (specifier === 'playwright') {
    writeFileSync(process.env.IMPORT_SENTINEL, '');
    throw new Error('fixture stopped before Chromium startup');
  }
  return nextResolve(specifier, context);
}
""")
            sentinel = Path(output, 'playwright-imported')
            try:
                result = subprocess.run(
                    ['node', '--experimental-loader', str(loader), str(CHECKER)],
                    env={
                        **os.environ,
                        'ARTIFACT_DIR': output,
                        'BASE_URL': f'http://127.0.0.1:{server.server_port}',
                        'PREVIEW_PID': str(os.getpid() if pid is None else pid),
                        'PREVIEW_MARKER_NAME': MARKER,
                        'PREVIEW_MARKER_TOKEN': TOKEN,
                        'IMPORT_SENTINEL': str(sentinel),
                    },
                    capture_output=True, text=True, timeout=10,
                )
                return result, sentinel.exists(), paths
            finally:
                server.shutdown()
                thread.join()

    @staticmethod
    def reply(body, *, status=200, location=None):
        def respond(request):
            request.send_response(status)
            if location is not None:
                request.send_header('Location', location)
            request.end_headers()
            request.wfile.write(body.encode())
        return respond

    def test_foreign_http_200_never_imports_playwright(self):
        for body in ('foreign service', TOKEN + ' extra bytes'):
            with self.subTest(body=body):
                result, imported, paths = self.run_checker(self.reply(body))
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertFalse(imported)
                self.assertEqual(paths, ['/' + MARKER])

    def test_redirect_to_matching_body_is_rejected(self):
        result, imported, paths = self.run_checker(
            self.reply(TOKEN, status=302, location='/redirect-target'),
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(imported)
        self.assertEqual(paths, ['/' + MARKER])

    def test_matching_body_allows_playwright_import_for_live_process(self):
        result, imported, paths = self.run_checker(self.reply(TOKEN))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertTrue(imported)
        self.assertEqual(paths, ['/' + MARKER])

    def test_absent_preview_process_does_not_probe_or_import_playwright(self):
        with subprocess.Popen([sys.executable, '-c', 'pass']) as preview:
            preview.wait(timeout=5)
            result, imported, paths = self.run_checker(
                self.reply(TOKEN), pid=preview.pid,
            )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(imported)
        self.assertEqual(paths, [])

    def test_unresponsive_http_service_does_not_import_playwright(self):
        release = threading.Event()
        try:
            result, imported, paths = self.run_checker(
                lambda request: release.wait(5),
            )
        finally:
            release.set()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(imported)
        self.assertEqual(paths, ['/' + MARKER])
