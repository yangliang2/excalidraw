"""Simulated GitHub responses for candidate-bound CI failure classification."""
import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    'github_gate', Path(__file__).resolve().parents[1] / 'github_gate.py',
)
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)

REPO = 'fixture/project'
PR = 16
HEAD, BASE, MERGE = 'a' * 40, 'b' * 40, 'c' * 40
WORKFLOW = 'Empty text history acceptance'
CHECK = 'empty-text-history'
PRODUCT = 'Classify production browser product failure'
ENVIRONMENT = 'Classify production browser environment failure'
PROTOCOL = 'Verify browser check exit protocol'
PROTOCOL_FAILURE = 'Classify browser check protocol failure'
RUN_PATH = f'repos/{REPO}/actions/runs/101'
JOBS_PATH = RUN_PATH + '/attempts/2/jobs?per_page=100'
CHECK_PATH = f'repos/{REPO}/check-runs/501'
COMMIT_PATH = f'repos/{REPO}/git/commits/{MERGE}'
DETAILS = f'https://github.com/{REPO}/actions/runs/101/job/201'


def step(name, conclusion):
    return {'name': name, 'status': 'completed', 'conclusion': conclusion}


class GitHubClassificationTests(unittest.TestCase):
    def setUp(self):
        self.item = {
            'name': CHECK, 'workflowName': WORKFLOW, 'status': 'COMPLETED',
            'conclusion': 'FAILURE', 'detailsUrl': DETAILS,
        }
        self.info = {
            'state': 'OPEN', 'url': f'https://github.com/{REPO}/pull/{PR}',
            'headRefOid': HEAD, 'baseRefOid': BASE,
            'statusCheckRollup': [self.item],
        }
        self.run = {
            'id': 101, 'run_attempt': 2, 'check_suite_id': 301, 'head_sha': HEAD,
            'path': '.github/workflows/empty-text-history.yml',
            'event': 'pull_request', 'status': 'completed', 'conclusion': 'failure',
            'repository': {'full_name': REPO},
        }
        self.steps = [
            step(f'Verify checkout {MERGE} for PR {PR} at {HEAD} into {BASE}', 'success'),
            step('Verify production empty text history', 'failure'),
            step(PRODUCT, 'success'),
            step(ENVIRONMENT, 'skipped'),
            step(PROTOCOL, 'success'),
            step(PROTOCOL_FAILURE, 'skipped'),
        ]
        self.job = {
            'id': 201, 'name': CHECK, 'run_id': 101, 'run_attempt': 2,
            'html_url': DETAILS, 'head_sha': HEAD,
            'check_run_url': 'https://api.github.com/' + CHECK_PATH,
            'status': 'completed', 'conclusion': 'failure', 'steps': self.steps,
        }
        self.check = {
            'id': 501, 'app': {'slug': 'github-actions'}, 'name': CHECK,
            'details_url': DETAILS, 'head_sha': HEAD, 'check_suite': {'id': 301},
            'status': 'completed', 'conclusion': 'failure',
        }
        self.responses = {
            RUN_PATH: self.run,
            JOBS_PATH: {'total_count': 1, 'jobs': [self.job]},
            CHECK_PATH: self.check,
            COMMIT_PATH: {'sha': MERGE, 'parents': [{'sha': BASE}, {'sha': HEAD}]},
        }

    def verdict(self, *required, api=None):
        return gate.evaluate(
            self.info, HEAD, BASE, list(required or (CHECK,)),
            repo=REPO, pr=PR, api=api or self.responses.__getitem__,
        )

    def test_latest_product_failure_is_not_hidden_by_old_success(self):
        self.info['statusCheckRollup'].insert(0, {
            **self.item, 'conclusion': 'SUCCESS',
            'detailsUrl': f'https://github.com/{REPO}/actions/runs/100/job/200',
        })
        self.assertEqual(self.verdict()['status'], 'rework')

    def test_environment_classifier_does_not_spend_a_repair(self):
        self.steps[2]['conclusion'] = 'skipped'
        self.steps[3]['conclusion'] = 'success'
        result = self.verdict()
        self.assertEqual(result['status'], 'environment-error')
        self.assertFalse(result['retryable'])

    def test_protocol_failure_is_rework_when_production_is_skipped(self):
        self.steps[1:] = [
            step(PROTOCOL, 'failure'),
            step('Verify production empty text history', 'skipped'),
            step(PROTOCOL_FAILURE, 'success'),
            step(PRODUCT, 'skipped'),
            step(ENVIRONMENT, 'skipped'),
        ]
        result = self.verdict()
        self.assertEqual(result['status'], 'rework')
        self.assertEqual(
            result['not_successful'][0]['reason'],
            'browser check exit protocol tests failed',
        )

        self.steps[2]['conclusion'] = 'failure'
        self.assertEqual(self.verdict()['status'], 'environment-error')
        self.steps[2]['conclusion'] = 'skipped'
        self.steps[3]['conclusion'] = 'skipped'
        self.assertEqual(self.verdict()['status'], 'environment-error')

    def test_skipped_protocol_cannot_pass(self):
        self.item['conclusion'] = 'SUCCESS'
        for record in (self.run, self.job, self.check):
            record['conclusion'] = 'success'
        self.steps[1]['conclusion'] = 'success'
        self.steps[2]['conclusion'] = 'skipped'
        self.steps[4]['conclusion'] = 'skipped'
        self.assertEqual(self.verdict()['status'], 'environment-error')

    def test_missing_or_conflicting_classifier_is_environment_error(self):
        self.steps[3]['conclusion'] = 'success'
        self.assertEqual(self.verdict()['status'], 'environment-error')
        del self.steps[2:4]
        self.assertEqual(self.verdict()['status'], 'environment-error')

    def test_unbound_metadata_is_environment_error(self):
        for payload, field, wrong in (
            (self.item, 'detailsUrl', DETAILS.replace('github.com', 'github.com.example')),
            (self.item, 'detailsUrl', DETAILS.replace(REPO, 'fixture/other')),
            (self.item, 'workflowName', 'Different workflow'),
            (self.run, 'path', '.github/workflows/other.yml'),
            (self.run, 'event', 'workflow_dispatch'),
            (self.run, 'head_sha', 'd' * 40),
            (self.run, 'run_attempt', 3),
            (self.job, 'run_attempt', 1),
            (self.job, 'run_id', 100),
            (self.job, 'id', 999),
            (self.check, 'check_suite', {'id': 302}),
            (self.check, 'app', {'slug': 'other-app'}),
            (self.steps[0], 'name', self.steps[0]['name'].replace('PR 16', 'PR 17')),
            (self.steps[0], 'name', self.steps[0]['name'].replace(BASE, HEAD)),
            (self.responses[COMMIT_PATH], 'parents', [{'sha': HEAD}, {'sha': BASE}]),
        ):
            with self.subTest(field=field, wrong=wrong), patch.dict(payload, {field: wrong}):
                self.assertEqual(self.verdict()['status'], 'environment-error')

    def test_duplicate_sources_are_ambiguous(self):
        self.info['statusCheckRollup'].append(dict(self.item))
        self.assertEqual(self.verdict()['status'], 'environment-error')
        self.info['statusCheckRollup'].pop()
        self.steps.append(dict(self.steps[2]))
        self.assertEqual(self.verdict()['status'], 'environment-error')

    def test_timeout_cancel_and_pending(self):
        for conclusion in ('TIMED_OUT', 'CANCELLED'):
            with self.subTest(conclusion=conclusion), patch.dict(self.item, {'conclusion': conclusion}):
                result = self.verdict()
                self.assertEqual(result['status'], 'environment-error')
                self.assertFalse(result['retryable'])
        self.item.update(status='IN_PROGRESS', conclusion='')
        self.assertEqual(self.verdict()['status'], 'waiting')

    def test_bound_success_still_requires_other_checks(self):
        self.item['conclusion'] = 'SUCCESS'
        for record in (self.run, self.job, self.check):
            record['conclusion'] = 'success'
        self.steps[1]['conclusion'] = 'success'
        self.steps[2]['conclusion'] = 'skipped'
        self.assertEqual(self.verdict()['status'], 'passed')
        self.assertEqual(self.verdict(CHECK, 'lint')['missing'], ['lint'])
        self.info['statusCheckRollup'].append({'name': 'lint', 'state': 'FAILURE'})
        self.assertEqual(self.verdict(CHECK, 'lint')['status'], 'rework')
        self.run['run_attempt'] += 1
        self.assertEqual(self.verdict()['status'], 'environment-error')

    def test_only_transient_query_errors_are_retryable(self):
        for transient in (False, True):
            def fail(endpoint):
                raise gate.GitHubQueryError(
                    'simulated query failure', retryable=transient,
                )
            with self.subTest(transient=transient):
                result = self.verdict(api=fail)
                self.assertEqual(result['status'], 'environment-error')
                self.assertEqual(result['retryable'], transient)

    def test_github_auth_and_permission_errors_do_not_retry(self):
        for status, retryable in ((401, False), (403, False), (429, True), (502, True)):
            response = subprocess.CompletedProcess(
                ['gh', 'api'], 1, stdout='', stderr=f'fixture: HTTP {status}',
            )
            with self.subTest(status=status), patch.object(
                gate.subprocess, 'run', return_value=response,
            ):
                with self.assertRaises(gate.GitHubQueryError) as error:
                    gate.gh_json(['api', RUN_PATH])
                self.assertEqual(error.exception.retryable, retryable)
