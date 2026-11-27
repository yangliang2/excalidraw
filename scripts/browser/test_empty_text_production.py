"""Exit-protocol unit fixtures; these do not claim real browser execution."""
import contextlib
import io
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch


class BrowserCheckProtocol(unittest.TestCase):
    def execute(self, *, build_error=None, browser_error=None, preview_exit=None):
        server = MagicMock()
        server.poll.return_value = preview_exit
        response = MagicMock()
        response.__enter__.return_value.status = 200

        def run(command, **kwargs):
            error = build_error if 'build' in command else browser_error
            if error:
                raise error
            return subprocess.CompletedProcess(command, 0)

        with tempfile.TemporaryDirectory() as artifacts, patch.dict(os.environ, {'ARTIFACT_DIR': artifacts}), \
                patch('subprocess.run', side_effect=run), patch('subprocess.Popen', return_value=server), \
                patch('urllib.request.urlopen', return_value=response), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                runpy.run_path(str(Path(__file__).with_name('check-empty-text-production.py')), run_name='__main__')
            except SystemExit as error:
                code = error.code or 0
            except Exception as error:
                self.fail(f'Unclassified exception: {type(error).__name__}: {error}')
            else:
                code = 0
        return code, server

    def test_build_timeout_is_environment(self):
        code, _ = self.execute(build_error=subprocess.TimeoutExpired('vite build', 600))
        self.assertEqual(code, 2)

    def test_browser_timeout_is_environment_and_server_is_stopped(self):
        code, server = self.execute(browser_error=subprocess.TimeoutExpired('browser', 180))
        self.assertEqual(code, 2)
        server.terminate.assert_called_once()

    def test_unavailable_executable_is_environment(self):
        code, _ = self.execute(build_error=FileNotFoundError('vite'))
        self.assertEqual(code, 2)

    def test_preview_exit_is_environment_and_server_is_stopped(self):
        code, server = self.execute(preview_exit=1)
        self.assertEqual(code, 2)
        server.terminate.assert_called_once()

    def test_product_assertion_stays_failure(self):
        code, _ = self.execute(browser_error=subprocess.CalledProcessError(1, 'browser'))
        self.assertEqual(code, 1)

    def test_child_environment_exit_is_preserved(self):
        code, _ = self.execute(browser_error=subprocess.CalledProcessError(2, 'browser'))
        self.assertEqual(code, 2)

    def test_build_failure_stays_failure(self):
        code, _ = self.execute(build_error=subprocess.CalledProcessError(1, 'build'))
        self.assertEqual(code, 1)

    def test_success_stops_server(self):
        code, server = self.execute()
        self.assertEqual(code, 0)
        server.terminate.assert_called_once()


if __name__ == '__main__':
    unittest.main()
