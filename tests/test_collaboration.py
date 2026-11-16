import csv
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_site
import import_proposal

PAPER = {'id': 'research-topic', 'irp_numbers': '14', 'researcher_names': 'Owen Chaffard', 'authors': 'Owen Chaffard',
         'title': 'A research topic', 'subjects': 'forecasting', 'summary': 'A research question', 'status': 'idea',
         'open_to_collaborate': 'yes', 'collaboration_needs': 'Help with empirical evaluation'}
REQUEST = {'id': 'request-evaluation', 'working_paper_id': 'research-topic', 'irp_numbers': '15',
           'message': 'I can help evaluate the model.', 'status': 'requested', 'last_updated': '2026-11-16'}


class CollaborationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(build_site.ROOT / 'data', self.root / 'data')
        shutil.copytree(build_site.ROOT / 'site', self.root / 'site')
        for filename in ['working-papers.csv', 'collaboration-requests.csv']:
            path = self.root / 'data' / filename
            path.write_text(path.read_text().splitlines()[0] + '\n')
        for module in [build_site, import_proposal]:
            patcher = patch.object(module, 'ROOT', self.root); patcher.start(); self.addCleanup(patcher.stop)
        self.apply(PAPER, kind='working-paper')

    def apply(self, record, kind='collaboration-request', action='add', write=True):
        path = self.root / 'proposal.json'
        path.write_text(json.dumps({'kind': kind, 'action': action, 'record': record}))
        import_proposal.apply_proposal(path, write)

    def test_request_without_external_contact_and_canonical_irp_card(self):
        self.apply(REQUEST)
        build_site.build()
        page = (self.root / '_site/working-papers.html').read_text()
        self.assertIn('Request to collaborate', page)
        self.assertIn('Collaboration requests', page)
        self.assertIn('Andrei-Theodor Ginavar', page)
        self.assertIn('/irps/irp-15.html', page)
        self.assertNotIn('Contact via public profile', page)
        self.assertNotIn('name="contact_url"', (self.root / '_site/contribute.html').read_text())
        exported = json.loads((self.root / '_site/data/research.json').read_text())
        self.assertEqual(exported['collaboration_requests'][0]['status'], 'requested')

    def test_request_dry_run_and_invalid_requests_leave_csv_unchanged(self):
        target = self.root / 'data/collaboration-requests.csv'; before = target.read_bytes()
        self.apply(REQUEST, write=False)
        self.assertEqual(target.read_bytes(), before)
        for changes in [{'working_paper_id': 'missing'}, {'irp_numbers': '999'}, {'irp_numbers': '14'},
                        {'irp_numbers': '3'}, {'irp_numbers': '15;15'}, {'message': ''},
                        {'message': 'x' * 3001}, {'status': 'accepted'}, {'status': 'unknown'},
                        {'issue_url': 'https://example.org/issues/1'}, {'requester_login': 'bad/name'}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError): self.apply({**REQUEST, **changes})
            self.assertEqual(target.read_bytes(), before)

    def test_duplicates_and_changing_request_identity_are_rejected(self):
        self.apply(REQUEST)
        with self.assertRaises(ValueError): self.apply({**REQUEST, 'id': 'another-request'})
        for changes in [{'irp_numbers': '16'}, {'working_paper_id': 'different-topic'}, {'requester_login': 'somebody'}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError): self.apply({'id': REQUEST['id'], **changes}, action='update')

    def test_accepted_and_withdrawn_statuses_do_not_change_paper_authors(self):
        self.apply(REQUEST)
        self.apply({'id': REQUEST['id'], 'status': 'accepted'}, action='update')
        build_site.build()
        page = (self.root / '_site/working-papers.html').read_text()
        self.assertIn('Collaborating IRPs', page)
        self.assertEqual(build_site.inventory()['working_papers'][0]['authors'], PAPER['authors'])
        self.apply({'id': REQUEST['id'], 'status': 'withdrawn'}, action='update')
        build_site.build()
        self.assertNotIn('Collaborating IRPs', (self.root / '_site/working-papers.html').read_text())
        self.assertEqual(len(build_site.read_collaborations(self.root)), 1)

    def test_closed_paper_blocks_new_requests_but_retains_previous_requests(self):
        self.apply(REQUEST)
        self.apply({'id': PAPER['id'], 'open_to_collaborate': 'no'}, kind='working-paper', action='update')
        with self.assertRaises(ValueError): self.apply({**REQUEST, 'id': 'new-request', 'irp_numbers': '16'})
        self.assertEqual(len(build_site.read_collaborations(self.root)), 1)

    def test_untrusted_request_text_is_escaped(self):
        self.apply({**REQUEST, 'message': '<img src=x onerror=alert(1)>'})
        build_site.build()
        page = (self.root / '_site/working-papers.html').read_text()
        self.assertIn('&lt;img', page)
        self.assertNotIn('<img src=x', page)
