"""Simulated preview and Playwright fixtures exercising the Node checker."""
import errno
from contextlib import contextmanager, redirect_stderr
from http.server import BaseHTTPRequestHandler, HTTPServer
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch


CHECKER = Path(__file__).with_name('empty-text-history.mjs')
MARKER = 'preview-marker.txt'
TOKEN = 'fixture-preview-token'
RESOURCE_ERRNOS = {errno.EMFILE, errno.ENFILE, errno.ENOMEM, errno.ENOBUFS, errno.EAGAIN}
PLAYWRIGHT_FIXTURE = """
import { EventEmitter } from 'node:events';
import { writeSync } from 'node:fs';
import { Readable } from 'node:stream';

// Supply a matching readiness response in memory. The ownership tests
// separately exercise the preview probe over a real HTTP connection.
export function resolve(specifier, context, nextResolve) {
  if (specifier === 'playwright') {
    writeSync(1, JSON.stringify({ fixture: 'playwright-import' }) + '\\n');
    return { url: import.meta.url, shortCircuit: true };
  }
  if (specifier === 'node:http' && process.env.FIXTURE_PREVIEW === 'memory') {
    return { url: import.meta.url, shortCircuit: true };
  }
  return nextResolve(specifier, context);
}

export function get(_url, _options, callback) {
  const response = Readable.from([process.env.PREVIEW_MARKER_TOKEN]);
  response.statusCode = 200;
  queueMicrotask(() => callback(response));
  return new EventEmitter();
}

export const chromium = {
  async launch() {
    if (process.env.BROWSER_FAULT === 'EDQUOT' || process.env.BROWSER_FAULT === 'ENOSPC') {
      throw Object.assign(new Error('simulated browser startup resource failure'), {
        code: process.env.BROWSER_FAULT,
      });
    }
    return {
      isConnected: () => true,
      close: async () => {},
      async newContext() {
        const page = new EventEmitter();
        Object.assign(page, {
          goto: async () => {},
          locator: () => ({
            first: () => ({
              async waitFor() {
                if (process.env.BROWSER_FAULT === 'crash') {
                  page.emit('crash');
                  throw new Error('locator.waitFor: Page crashed');
                }
              },
            }),
          }),
          getByTestId: () => ({ click: async () => {} }),
          mouse: { move: async () => {}, down: async () => {}, up: async () => {} },
          waitForTimeout: async () => {},
          evaluate: async () => [{ type: 'unexpected shape' }],
          screenshot: async () => Buffer.alloc(0),
        });
        return { newPage: async () => page, close: async () => {} };
      },
    };
  },
};
"""


class ProtocolEnvironmentError(Exception):
    """The runner could not provide a resource needed by a protocol test."""


class PreviewServer(HTTPServer):
    # Only the preview's service thread handles requests. Report resource
    # failures back to the test thread before it checks the Node result.
    resource_error = None

    def get_request(self):
        try:
            return super().get_request()
        except OSError as error:
            # socketserver suppresses accept errors before dispatching handlers.
            if error.errno in RESOURCE_ERRNOS:
                self.resource_error = error
            raise

    def handle_error(self, request, client_address):
        error = sys.exc_info()[1]
        if isinstance(error, OSError) and error.errno in RESOURCE_ERRNOS:
            self.resource_error = error
        else:
            super().handle_error(request, client_address)

    def run(self):
        try:
            self.serve_forever()
        except OSError as error:
            self.resource_error = error


def environment_call(operation, function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ProtocolEnvironmentError(f'{operation}: {error}') from error


@contextmanager
def fixture_directory(name):
    directory = environment_call(f'create {name} fixture directory', tempfile.TemporaryDirectory)
    try:
        yield directory.name
    finally:
        environment_call(f'clean up {name} fixture directory', directory.cleanup)


def run_node(operation, command, *, expected_environment=None, **kwargs):
    result = environment_call(operation, subprocess.run, command, **kwargs)
    if result.returncode < 0:
        raise ProtocolEnvironmentError(
            f'{operation}: terminated by signal {-result.returncode}',
        )
    try:
        *events, report = (json.loads(line) for line in (result.stdout or '').splitlines())
    except ValueError:
        events, report = [], {}
    if not isinstance(report, dict):
        report = {}
    if result.returncode == 2:
        outcome = (report.get('phase'), report.get('outcome'))
        if outcome != expected_environment:
            raise ProtocolEnvironmentError(f'{operation}: {result.stderr.strip()}')
    return result, report, events


class ProtocolTestResult(unittest.TextTestResult):
    environment_failed = False

    def addError(self, test, err):
        super().addError(test, err)
        self.record_environment_error(err)

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        self.record_environment_error(err)

    def record_environment_error(self, err):
        if err is not None and isinstance(err[1], ProtocolEnvironmentError):
            self.environment_failed = True

    def exit_code(self):
        if self.environment_failed:
            return 2
        return 0 if self.wasSuccessful() else 1


class PreviewOwnershipTests(unittest.TestCase):
    def run_checker(self, response, *, pid=None):
        paths = []

        class Preview(BaseHTTPRequestHandler):
            def do_GET(self):
                paths.append(self.path)
                response(self)

            def log_message(self, *args):
                pass

        with fixture_directory('preview') as output, environment_call(
            'listen for preview fixture', PreviewServer, ('127.0.0.1', 0), Preview,
        ) as server:
            loader = Path(output, 'loader.mjs')
            environment_call('write preview fixture loader', loader.write_text, PLAYWRIGHT_FIXTURE)
            thread = threading.Thread(target=server.run, daemon=True)
            try:
                environment_call('start preview fixture thread', thread.start)
            except RuntimeError as error:
                if str(error) != "can't start new thread":
                    raise
                raise ProtocolEnvironmentError(f'start preview fixture thread: {error}') from error
            try:
                result, _, events = run_node(
                    'run Node preview checker',
                    ['node', '--experimental-loader', str(loader), str(CHECKER)],
                    expected_environment=('preview', 'rejected'),
                    env={
                        **os.environ,
                        'ARTIFACT_DIR': output,
                        'BASE_URL': f'http://127.0.0.1:{server.server_port}',
                        'PREVIEW_PID': str(os.getpid() if pid is None else pid),
                        'PREVIEW_MARKER_NAME': MARKER,
                        'PREVIEW_MARKER_TOKEN': TOKEN,
                        'FIXTURE_PREVIEW': 'http',
                        'BROWSER_FAULT': 'assertion',
                    },
                    capture_output=True, text=True, timeout=10,
                )
            finally:
                server.shutdown()
                thread.join()
            if server.resource_error is not None:
                raise ProtocolEnvironmentError(
                    f'serve preview fixture: {server.resource_error}',
                ) from server.resource_error
            return result, {'fixture': 'playwright-import'} in events, paths

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
        # The fixture reaches the actual history check and fails its assertion.
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertTrue(imported)
        self.assertEqual(paths, ['/' + MARKER])

    def test_absent_preview_process_does_not_probe_or_import_playwright(self):
        with environment_call(
            'start preview fixture process', subprocess.Popen, [sys.executable, '-c', 'pass'],
        ) as preview:
            environment_call('wait for preview fixture process', preview.wait, timeout=5)
            result, imported, paths = self.run_checker(
                self.reply(TOKEN), pid=preview.pid,
            )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(imported)
        self.assertEqual(paths, [])

    def test_unresponsive_http_service_does_not_import_playwright(self):
        def wait_for_disconnect(request):
            request.connection.settimeout(5)
            request.rfile.read(1)

        result, imported, paths = self.run_checker(wait_for_disconnect)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(imported)
        self.assertEqual(paths, ['/' + MARKER])


class BrowserFailureTests(unittest.TestCase):
    def run_browser_fault(self, fault, *, expected_environment=None):
        with fixture_directory('Playwright') as output:
            loader = Path(output, 'playwright-fixture.mjs')
            environment_call('write Playwright fixture', loader.write_text, PLAYWRIGHT_FIXTURE)
            return run_node(
                'run Node with simulated Playwright',
                ['node', '--experimental-loader', str(loader), str(CHECKER)],
                expected_environment=expected_environment,
                env={
                    **os.environ,
                    'ARTIFACT_DIR': output,
                    'BASE_URL': 'http://127.0.0.1:5176',
                    'PREVIEW_PID': str(os.getpid()),
                    'PREVIEW_MARKER_NAME': MARKER,
                    'PREVIEW_MARKER_TOKEN': TOKEN,
                    'FIXTURE_PREVIEW': 'memory',
                    'BROWSER_FAULT': fault,
                },
                capture_output=True, text=True, timeout=10,
            )

    def test_page_crash_with_connected_browser_exits_two(self):
        result, report, _ = self.run_browser_fault(
            'crash', expected_environment=('browser-check', None),
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(report['failures'], [])
        self.assertIn('Page crashed', report['environmentError'])

    def test_browser_behavior_assertion_exits_one(self):
        result, report, _ = self.run_browser_fault('assertion')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn('environmentError', report)
        self.assertEqual(len(report['failures']), 3)
        for failure in report['failures']:
            self.assertIn('AssertionError', failure['error'])

    def test_browser_startup_resource_errors_exit_two(self):
        for fault in ('EDQUOT', 'ENOSPC'):
            with self.subTest(fault=fault):
                with self.assertRaises(ProtocolEnvironmentError):
                    self.run_browser_fault(fault)
                result, report, _ = self.run_browser_fault(
                    fault, expected_environment=('browser-initialization', 'environment'),
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn('simulated browser startup resource failure', report['environmentError'])


class ProtocolClassificationTests(unittest.TestCase):
    def test_frozen_fixture_temp_failures_exit_two_through_discovery(self):
        directory = tempfile.TemporaryDirectory

        def fail_cleanup(instance):
            cleanup(instance)
            raise OSError(errno.EIO, 'simulated frozen fixture cleanup failure')

        cleanup = directory.cleanup
        for fault, expected in (('create', 2), ('cleanup', 2), (None, 0)):
            with self.subTest(fault=fault), patch.object(
                unittest.TestLoader, 'testNamePatterns', ['*.test_success_stops_server'],
            ), redirect_stderr(io.StringIO()) as log:
                if fault == 'create':
                    with patch.object(tempfile, 'TemporaryDirectory', side_effect=OSError(
                        errno.ENOSPC, 'simulated frozen fixture creation failure',
                    )):
                        code = run_protocol_tests()
                elif fault == 'cleanup':
                    with patch.object(directory, 'cleanup', autospec=True, side_effect=fail_cleanup):
                        code = run_protocol_tests()
                else:
                    code = run_protocol_tests()
                self.assertIn('Ran 1 test', log.getvalue())
                self.assertEqual(code, expected, log.getvalue())

    def test_node_signals_exit_two(self):
        for returncode in (-9, -15):
            with self.subTest(returncode=returncode), patch(
                f'{__name__}.subprocess.run',
                return_value=subprocess.CompletedProcess(
                    ['node'], returncode, stdout='', stderr='',
                ),
            ):
                result = unittest.TextTestRunner(
                    stream=io.StringIO(), resultclass=ProtocolTestResult,
                ).run(BrowserFailureTests('test_browser_behavior_assertion_exits_one'))
                self.assertEqual(result.exit_code(), 2)

    def test_preview_request_needs_only_one_thread_and_classifies_resource_errors(self):
        # Simulate a runner with one thread slot and drive socketserver's real
        # request dispatch using an in-memory connection.
        for failure, expected in (
            (None, 0),
            ('accept', 2),
            ('handle', 2),
            ('ENOSPC', 2),
            ('EDQUOT', 2),
            ('unexpected-rejection', 1),
        ):
            with self.subTest(failure=failure):
                error = OSError(errno.EMFILE, 'simulated request resource failure')
                request = MagicMock()
                if failure == 'handle':
                    request.makefile.side_effect = error
                request.makefile.return_value = io.BytesIO(
                    f'GET /{MARKER} HTTP/1.0\r\n\r\n'.encode(),
                )
                stopped = threading.Event()
                server = None
                start_thread = threading.Thread.start
                started = False

                def start(thread):
                    nonlocal started
                    if started:
                        raise RuntimeError("can't start new thread")
                    started = True
                    start_thread(thread)

                def bind(instance):
                    nonlocal server
                    server = instance
                    instance.server_port = 5176
                    instance.server_name = 'localhost'

                def run(command, *, env, **kwargs):
                    server._handle_request_noblock()
                    if failure in ('ENOSPC', 'EDQUOT'):
                        return subprocess.CompletedProcess(
                            command, 2,
                            stdout=json.dumps({
                                'phase': 'browser-initialization',
                                'outcome': 'environment',
                                'environmentError': f'simulated {failure}',
                            }),
                            stderr='',
                        )
                    if failure == 'unexpected-rejection':
                        return subprocess.CompletedProcess(
                            command, 2, stdout=json.dumps({'phase': 'preview', 'outcome': 'rejected'}),
                            stderr='',
                        )
                    if any(call.args == (TOKEN.encode(),) for call in request.sendall.call_args_list):
                        return subprocess.CompletedProcess(
                            command, 1,
                            stdout='\n'.join((
                                json.dumps({'fixture': 'playwright-import'}),
                                json.dumps({'phase': 'browser-check'}),
                            )),
                            stderr='',
                        )
                    return subprocess.CompletedProcess(
                        command, 2, stdout=json.dumps({'phase': 'preview', 'outcome': 'rejected'}),
                        stderr='',
                    )

                def accept(_server):
                    if failure == 'accept':
                        raise error
                    return request, ('127.0.0.1', 1)

                with (
                    patch.object(HTTPServer, 'server_bind', bind),
                    patch.object(HTTPServer, 'server_activate'),
                    patch.object(HTTPServer, 'serve_forever', stopped.wait),
                    patch.object(HTTPServer, 'shutdown', stopped.set),
                    patch.object(HTTPServer, 'get_request', accept),
                    patch.object(threading.Thread, 'start', start),
                    patch(f'{__name__}.subprocess.run', side_effect=run),
                    redirect_stderr(io.StringIO()),
                ):
                    stream = io.StringIO()
                    result = unittest.TextTestRunner(
                        stream=stream, resultclass=ProtocolTestResult,
                    ).run(PreviewOwnershipTests('test_matching_body_allows_playwright_import_for_live_process'))
                self.assertEqual(result.exit_code(), expected, stream.getvalue())

    def test_fixture_resource_errors_in_tests_and_subtests_exit_two(self):
        for name, error, method in (
            ('PreviewServer', OSError(errno.EMFILE, 'simulated socket failure'),
             'test_foreign_http_200_never_imports_playwright'),
            ('tempfile.TemporaryDirectory', PermissionError('simulated temp failure'),
             'test_redirect_to_matching_body_is_rejected'),
            ('subprocess.run', FileNotFoundError('simulated Node startup failure'),
             'test_matching_body_allows_playwright_import_for_live_process'),
        ):
            with self.subTest(resource=name), patch(f'{__name__}.{name}', side_effect=error):
                result = unittest.TextTestRunner(
                    stream=io.StringIO(), resultclass=ProtocolTestResult,
                ).run(PreviewOwnershipTests(method))
                self.assertEqual(result.exit_code(), 2)

    def test_preview_thread_start_failure_exits_two_without_starting_node(self):
        with patch(f'{__name__}.PreviewServer', MagicMock()), patch.object(
            threading.Thread, 'start', side_effect=RuntimeError("can't start new thread"),
        ) as start, patch(f'{__name__}.subprocess.run') as run:
            result = unittest.TextTestRunner(
                stream=io.StringIO(), resultclass=ProtocolTestResult,
            ).run(PreviewOwnershipTests('test_matching_body_allows_playwright_import_for_live_process'))
            start.assert_called_once_with()
            run.assert_not_called()
            self.assertEqual(result.exit_code(), 2)

    def test_fixture_directory_cleanup_io_error_exits_two(self):
        cleanup = tempfile.TemporaryDirectory.cleanup

        def fail_cleanup(directory):
            cleanup(directory)
            raise OSError(errno.EIO, 'simulated fixture cleanup I/O failure')

        with patch.object(
            tempfile.TemporaryDirectory, 'cleanup', autospec=True, side_effect=fail_cleanup,
        ):
            stream = io.StringIO()
            result = unittest.TextTestRunner(
                stream=stream, resultclass=ProtocolTestResult,
            ).run(BrowserFailureTests('test_browser_behavior_assertion_exits_one'))
        self.assertEqual(result.exit_code(), 2, stream.getvalue())

    def test_fixture_assertion_and_programming_errors_exit_one(self):
        for error in (AssertionError('simulated failed assertion'),
                      TypeError('simulated unary plus on fixture server')):
            with self.subTest(error=type(error)), patch(
                f'{__name__}.PreviewServer', side_effect=error,
            ):
                result = unittest.TextTestRunner(
                    stream=io.StringIO(), resultclass=ProtocolTestResult,
                ).run(PreviewOwnershipTests('test_foreign_http_200_never_imports_playwright'))
                self.assertEqual(result.exit_code(), 1)


def run_protocol_tests():
    loader = unittest.TestLoader()
    suite = loader.discover(
        str(Path(__file__).resolve().parent), pattern='test_empty_text_production.py',
    )
    suite.addTests(loader.loadTestsFromModule(sys.modules[__name__]))
    # The frozen fixtures create their own temporary directories. Adapt their
    # resource boundary without changing the fixtures or process-wide tempfile.
    fixture_tempfile = SimpleNamespace(
        TemporaryDirectory=lambda: fixture_directory('production protocol'),
    )
    with patch.object(sys.modules['test_empty_text_production'], 'tempfile', fixture_tempfile):
        result = unittest.TextTestRunner(verbosity=2, resultclass=ProtocolTestResult).run(suite)
    return result.exit_code()


if __name__ == '__main__':
    raise SystemExit(run_protocol_tests())
