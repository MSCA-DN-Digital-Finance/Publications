import copy
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


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        shutil.copytree(build_site.ROOT / 'data', self.root / 'data')
        for module in [build_site, import_proposal]:
            patcher = patch.object(module, 'ROOT', self.root); patcher.start(); self.addCleanup(patcher.stop)
        self.original = build_site.inventory()['publications'][0]

    def proposal(self, record=None, action='update', kind='publication'):
        path = self.root / 'proposal.json'
        path.write_text(json.dumps({'kind': kind, 'action': action, 'record': record or self.original}))
        return path

    def test_dry_run_leaves_bytes_unchanged(self):
        target = self.root / 'data/publications.csv'; before = target.read_bytes()
        changed = {**self.original, 'summary': 'A new summary, with commas\nand a newline'}
        import_proposal.apply_proposal(self.proposal(changed))
        self.assertEqual(target.read_bytes(), before)

    def test_update_preserves_unicode_and_multiline(self):
        changed = {**self.original, 'summary': 'Résumé, with commas\nand a newline'}
        import_proposal.apply_proposal(self.proposal(changed), True)
        self.assertEqual(build_site.inventory()['publications'][0]['summary'], changed['summary'])
        self.assertIn('Mollá', build_site.inventory()['publications'][0]['authors'])

    def test_duplicate_doi_rejected_and_files_unchanged(self):
        target = self.root / 'data/publications.csv'; before = target.read_bytes()
        changed = {**self.original, 'id': 'second-copy', 'doi': 'https://doi.org/' + self.original['doi'].upper()}
        with self.assertRaises(ValueError):
            import_proposal.apply_proposal(self.proposal(changed, 'add'), True)
        self.assertEqual(target.read_bytes(), before)

    def test_unknown_fields_and_unsafe_urls_rejected(self):
        for change in [{'private_field':'x'}, {'link':'javascript:alert(1)'}, {'year':'unknown'}, {'publication_date':'2025-13'}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                import_proposal.apply_proposal(self.proposal({**self.original, **change}), True)

    def test_preprint_without_venue_or_doi_is_valid(self):
        record = {**self.original, 'id':'a-preprint', 'type':'preprint', 'doi':'', 'venue':''}
        import_proposal.apply_proposal(self.proposal(record, 'add'), True)
        self.assertEqual(len(build_site.inventory()['publications']), 2)

    def test_open_collaboration_requires_public_contact_and_needs(self):
        working = {'id':'a-working-paper', 'irp_numbers':'14;15', 'researcher_names':'Researcher One;Researcher Two', 'title':'A collaboration topic', 'authors':'Researcher One;Researcher Two', 'subjects':'forecasting', 'summary':'A research question', 'status':'idea', 'open_to_collaborate':'yes'}
        for fields in [{}, {'contact_url':'https://example.org/profile'}, {'contact_url':'https://example.org/profile','collaboration_needs':'Looking for model evaluation expertise','related_publication_ids':'missing-id'}]:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                import_proposal.apply_proposal(self.proposal({**working, **fields}, 'add', 'working-paper'), True)
        working.update(contact_url='https://example.org/profile',collaboration_needs='Looking for model evaluation expertise',related_publication_ids=self.original['id'])
        import_proposal.apply_proposal(self.proposal(working,'add','working-paper'), True)
        self.assertEqual(len(build_site.inventory()['working_papers']), 1)

    def test_untrusted_html_is_escaped_and_bibtex_has_metadata(self):
        record={**self.original,'title':'<script>alert(1)</script>'}
        rendered=build_site.render_record(record,'publication')
        self.assertNotIn('<script>',rendered)
        self.assertIn('&lt;script&gt;',rendered)
        citation=build_site.bibtex(self.original)
        self.assertIn('Mollá',citation)
        self.assertIn('10.1016/j.knosys.2025.114449',citation)
        self.assertIn('journal = {Knowledge-Based Systems}',citation)

if __name__ == '__main__':
    unittest.main()
