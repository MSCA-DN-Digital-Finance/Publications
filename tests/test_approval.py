import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import approve_publication as approval

REPOSITORY = 'example/inventory'
RECORD = {'id': 'approval-test', 'irp_numbers': '14', 'researcher_names': 'Test Researcher', 'title': 'Approval test', 'authors': 'Test Researcher', 'year': '2026', 'subjects': 'finance', 'type': 'journal-article', 'venue': 'Test Journal', 'access': 'unknown', 'link': 'https://example.org'}
PROPOSAL = {'kind': 'publication', 'action': 'add', 'record': RECORD}


def event_for(proposal=PROPOSAL):
    return {'action': 'labeled', 'label': {'name': 'publication-approved'}, 'repository': {'full_name': REPOSITORY}, 'sender': {'login': 'maintainer'}, 'issue': {'number': 42, 'state': 'open', 'body': '## Inventory proposal\n\n```json\n' + json.dumps(proposal) + '\n```', 'labels': [{'name': 'publication-approved'}]}}


class ApprovalValidationTests(unittest.TestCase):
    def test_extracts_website_proposal(self):
        self.assertEqual(approval.extract_proposal(event_for()['issue']['body']), PROPOSAL)

    def test_requires_exactly_one_proposal_and_unique_keys(self):
        for body in ['Attachment: https://example.org/proposal.json', event_for()['issue']['body'] * 2, '```json\n{"kind":"source","kind":"dataset","action":"add","record":{}}\n```']:
            with self.subTest(body=body), self.assertRaises(ValueError):
                approval.extract_proposal(body)

    def test_rejects_pull_requests_wrong_repository_and_actor(self):
        for mutate in [lambda e: e['issue'].update(pull_request={}), lambda e: e['repository'].update(full_name='other/repo'), lambda e: e['sender'].update(login='other'), lambda e: e['issue'].update(number=True)]:
            event = event_for(); mutate(event)
            with self.assertRaises(ValueError):
                approval.validate_event(event, REPOSITORY, 'maintainer')

    def test_requires_write_permission_not_triage(self):
        for role in ['admin', 'write', 'maintain']:
            self.assertTrue(approval.can_approve({'permission': role}))
        for role in ['read', 'triage', 'none']:
            self.assertFalse(approval.can_approve({'permission': role}))

    def test_rejects_edited_or_unapproved_issue(self):
        snapshot = event_for()['issue']
        for changes in [{'body': 'changed'}, {'labels': []}, {'state': 'closed'}]:
            with self.assertRaises(ValueError):
                approval.assert_unchanged(snapshot, {**snapshot, **changes})


class ApprovalIntegrationTests(unittest.TestCase):
    """Exercise real CSV imports, builds and Git pushes against a disposable local remote."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'checkout'
        self.root.mkdir()
        source = approval.ROOT
        for name in ['scripts', 'site', 'data']:
            shutil.copytree(source / name, self.root / name, ignore=shutil.ignore_patterns('__pycache__'))
        for name in ['README.md', 'update_README.py', '.gitignore']:
            shutil.copy2(source / name, self.root / name)
        self.remote = Path(self.temp.name) / 'remote.git'
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Test'); self.git('config', 'user.email', 'test@example.org')
        self.git('add', '.'); self.git('commit', '-m', 'Initial')
        subprocess.run(['git', 'init', '--bare', str(self.remote)], check=True, capture_output=True)
        self.git('remote', 'add', 'origin', str(self.remote)); self.git('push', '-u', 'origin', 'main')
        self.calls = []
        self.current = copy.deepcopy(event_for()['issue'])
        self.root_patch = patch.object(approval, 'ROOT', self.root); self.root_patch.start(); self.addCleanup(self.root_patch.stop)
        self.api_patch = patch.object(approval, 'api', side_effect=self.api); self.api_patch.start(); self.addCleanup(self.api_patch.stop)

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.root, check=True, text=True, capture_output=True).stdout.strip()

    def api(self, endpoint, *, method='GET', payload=None):
        self.calls.append((endpoint, method, payload))
        if endpoint.endswith('/permission'):
            return {'permission': 'write'}
        if method == 'GET':
            return copy.deepcopy(self.current)
        if endpoint.endswith('/labels'):
            self.current['labels'].append({'name': 'publication-applied'})
        if method == 'PATCH':
            self.current['state'] = payload['state']
        return {}

    def test_applies_and_retries_without_duplicate_import(self):
        commit = approval.approve(event_for(), REPOSITORY, 'maintainer')
        self.assertEqual(self.git('rev-parse', 'origin/main'), commit)
        with (self.root / 'data/publications.csv').open() as f:
            import csv
            self.assertEqual(sum(r['id'] == 'approval-test' for r in csv.DictReader(f)), 1)
        self.assertIn('Approval test', (self.root / 'README.md').read_text())
        self.assertIn('approval-test', (self.root / '_site/index.html').read_text())
        self.assertEqual(self.current['state'], 'closed')
        dispatch = [c for c in self.calls if '/dispatches' in c[0]]
        self.assertEqual(dispatch[0][2], {'ref': 'main'})
        count = self.git('rev-list', '--count', 'main')
        self.assertEqual(approval.approve(event_for(), REPOSITORY, 'maintainer'), commit)
        self.assertEqual(self.git('rev-list', '--count', 'main'), count)

    def test_invalid_proposal_does_not_push_or_close(self):
        proposal = copy.deepcopy(PROPOSAL); proposal['record']['link'] = 'javascript:alert(1)'
        event = event_for(proposal); self.current = copy.deepcopy(event['issue'])
        before = self.git('rev-parse', 'origin/main')
        with self.assertRaises(subprocess.CalledProcessError):
            approval.approve(event, REPOSITORY, 'maintainer')
        self.assertEqual(self.git('rev-parse', 'origin/main'), before)
        self.assertEqual(self.current['state'], 'open')
        self.assertFalse(any('/dispatches' in c[0] for c in self.calls))

    def test_push_conflict_reapplies_on_latest_main(self):
        original = approval.run
        pushes = []
        def conflict_once(args, **kwargs):
            if args[:2] == ['git', 'push']:
                pushes.append(args)
                if len(pushes) == 1:
                    return subprocess.CompletedProcess(args, 1, '', 'Simulated concurrent push')
            return original(args, **kwargs)
        with patch.object(approval, 'run', side_effect=conflict_once):
            commit = approval.approve(event_for(), REPOSITORY, 'maintainer')
        self.assertEqual(len(pushes), 2)
        self.assertEqual(self.git('rev-parse', 'origin/main'), commit)
        self.assertEqual(self.git('rev-list', '--count', 'origin/main'), '2')

    def test_dispatch_failure_can_retry_without_duplicate_commit(self):
        original = self.api
        def fail_dispatch(endpoint, **kwargs):
            if '/dispatches' in endpoint:
                raise subprocess.CalledProcessError(1, ['gh', 'api'], stderr='Dispatch unavailable')
            return original(endpoint, **kwargs)
        with patch.object(approval, 'api', side_effect=fail_dispatch):
            with self.assertRaises(subprocess.CalledProcessError):
                approval.approve(event_for(), REPOSITORY, 'maintainer')
        count = self.git('rev-list', '--count', 'origin/main')
        self.assertEqual(self.current['state'], 'open')
        approval.approve(event_for(), REPOSITORY, 'maintainer')
        self.assertEqual(self.git('rev-list', '--count', 'origin/main'), count)
        self.assertEqual(self.current['state'], 'closed')

    def test_untrusted_approver_cannot_write(self):
        with patch.object(approval, 'api', return_value={'permission': 'triage'}):
            with self.assertRaises(ValueError):
                approval.approve(event_for(), REPOSITORY, 'maintainer')
        self.assertEqual(self.git('rev-list', '--count', 'main'), '1')
