import csv
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_site
import import_proposal
import sync_zenodo as zenodo


def record(rid=101, concept=100, doi='10.1234/example'):
    return {'id': rid, 'conceptrecid': str(concept), 'doi': doi, 'status': 'published',
            'modified': '2026-11-12T10:00:00Z', 'metadata': {
                'title': 'Example research', 'doi': doi, 'publication_date': '2026-11-01',
                'resource_type': {'type': 'publication', 'subtype': 'article'},
                'communities': [{'id': 'digitalfinance'}],
                'creators': [{'name': 'Mollá, Researcher'}, {'name': 'Other, Author'}],
                'description': '<p>A résumé &amp; <em>abstract</em>.</p><p>Next paragraph.</p>',
                'journal': {'title': 'Test Journal', 'volume': '2', 'issue': '1', 'pages': '10–20'},
                'access_right': 'open', 'license': {'id': 'cc-by-4.0'}}}


def page(records, total):
    return {'hits': {'hits': records, 'total': total}}


class FetchTests(unittest.TestCase):
    def test_anonymous_request_identifies_client(self):
        with patch.object(zenodo, 'urlopen', return_value=io.StringIO('{"ok": true}')) as open_url:
            self.assertEqual(zenodo.request_json(zenodo.API), {'ok': True})
        request = open_url.call_args.args[0]
        self.assertIsNone(request.get_header('Authorization'))
        self.assertEqual(request.get_header('User-agent'), zenodo.USER_AGENT)

    def test_paginates_and_requests_only_latest_community_publications(self):
        records = [record(), record(201, 200, '10.1234/second')]
        with patch.object(zenodo, 'request_json', side_effect=[page(records[:1], 2), page(records[1:], {'value': 2, 'relation': 'eq'})]) as request, patch.object(zenodo.time, 'sleep'):
            self.assertEqual(zenodo.fetch_records(), records)
        from urllib.parse import parse_qs, urlsplit
        queries = [parse_qs(urlsplit(call.args[0]).query) for call in request.call_args_list]
        self.assertEqual([q['page'] for q in queries], [['1'], ['2']])
        self.assertEqual(queries[0]['communities'], ['digitalfinance'])
        self.assertEqual(queries[0]['all_versions'], ['false'])
        self.assertEqual(queries[0]['type'], ['publication'])
        self.assertEqual(queries[0]['size'], ['25'])

    def test_incomplete_duplicate_and_changing_responses_fail(self):
        for responses in [[page([record()], 2), page([], 2)],
                          [page([record()], 2), page([record()], 2)],
                          [page([record()], 2), page([], 3)]]:
            with self.subTest(responses=responses), patch.object(zenodo, 'request_json', side_effect=responses), patch.object(zenodo.time, 'sleep'), self.assertRaises(ValueError):
                zenodo.fetch_records()

    def test_rejects_records_outside_community_or_publication_scope(self):
        for key, value in [('communities', []), ('resource_type', {'type': 'dataset'})]:
            item = record(); item['metadata'][key] = value
            with self.subTest(key=key), patch.object(zenodo, 'request_json', return_value=page([item], 1)), self.assertRaises(ValueError):
                zenodo.fetch_records()

    def test_retries_rate_limits_but_not_authentication_errors(self):
        throttled = HTTPError(zenodo.API, 429, 'Rate limited', {'Retry-After': '7'}, None)
        with patch.object(zenodo, 'urlopen', side_effect=[throttled, io.StringIO('{}')]), patch.object(zenodo.time, 'sleep') as sleep:
            self.assertEqual(zenodo.request_json(zenodo.API), {})
            sleep.assert_called_once_with(7)
        with patch.object(zenodo, 'urlopen', side_effect=HTTPError(zenodo.API, 403, 'Forbidden', {}, None)) as request, self.assertRaises(HTTPError):
            zenodo.request_json(zenodo.API)
        self.assertEqual(request.call_count, 1)


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(build_site.ROOT / 'data', self.root / 'data')
        shutil.copytree(build_site.ROOT / 'site', self.root / 'site')
        with (self.root / 'data/publications.csv').open() as source:
            self.fields = next(csv.reader(source))
        for path in (self.root / 'data').glob('*.csv'):
            path.write_text(path.read_text().splitlines()[0] + '\n')
        for module in [build_site, import_proposal]:
            patcher = patch.object(module, 'ROOT', self.root)
            patcher.start(); self.addCleanup(patcher.stop)
        self.target = self.root / 'data' / zenodo.CACHE

    def sync(self, records, write=True):
        return zenodo.sync_records(records, root=self.root, write=write)

    def test_dry_run_preserves_files_and_repeated_sync_is_byte_identical(self):
        before = {p.name: p.read_bytes() for p in (self.root / 'data').glob('*')}
        self.sync([record()], write=False)
        self.assertEqual(before, {p.name: p.read_bytes() for p in (self.root / 'data').glob('*')})
        self.assertTrue(self.sync([record()]))
        cached = self.target.read_bytes()
        self.assertFalse(self.sync([record()]))
        self.assertEqual(self.target.read_bytes(), cached)
        row = build_site.inventory()['publications'][0]
        self.assertEqual(row['authors'], 'Mollá, Researcher;Other, Author')
        self.assertEqual(row['summary'], 'A résumé & abstract. Next paragraph.')
        self.assertEqual(row['irp_numbers'], '')
        self.assertEqual(row['researcher_names'], '')
        self.assertEqual(row['subjects'], '')
        self.assertEqual(row['last_updated'], '2026-11-12')

    def test_curated_doi_takes_precedence_and_is_never_modified(self):
        curated = zenodo.publication(record(), self.fields)
        curated.update(id='curated-paper', irp_numbers='14', researcher_names='Researcher One', subjects='finance', title='Curated title', doi='https://doi.org/10.1234/EXAMPLE')
        path = self.root / 'data/publications.csv'
        with path.open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=self.fields); writer.writeheader(); writer.writerow(curated)
        before = path.read_bytes()
        self.sync([record()])
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual([r['title'] for r in build_site.inventory()['publications']], ['Curated title'])

    def test_new_versions_keep_id_and_removed_feed_records_disappear(self):
        self.sync([record()])
        self.sync([record(102)])
        row = build_site.inventory()['publications'][0]
        self.assertEqual(row['id'], 'zenodo-100')
        self.assertEqual(row['link'], 'https://zenodo.org/records/102')
        self.sync([])
        self.assertEqual(build_site.inventory()['publications'], [])

    def test_invalid_metadata_does_not_replace_cache(self):
        self.sync([record()]); before = self.target.read_bytes()
        for changes in [{'publication_date': '2026-13-01'}, {'doi': 'invalid'}, {'title': ''}]:
            invalid = record(); invalid['metadata'].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.sync([invalid])
            self.assertEqual(self.target.read_bytes(), before)

    def test_deduplicates_doi_and_rejects_ambiguous_versions(self):
        self.sync([record(), record(201, 200)])
        self.assertEqual(len(build_site.inventory()['publications']), 1)
        with self.assertRaises(ValueError):
            self.sync([record(), record(102)])

    def test_preprint_and_unknown_venue_are_not_invented(self):
        item = record(); item['metadata'].pop('journal')
        self.sync([item])
        self.assertEqual(build_site.inventory()['publications'][0]['venue'], '')
        item['metadata']['resource_type']['subtype'] = 'preprint'
        self.sync([item])
        row = build_site.inventory()['publications'][0]
        self.assertEqual(row['type'], 'preprint')
        self.assertEqual(row['preprint_url'], row['link'])

    def test_build_exports_combined_catalogue_and_approved_update_survives_sync(self):
        self.sync([record()])
        build_site.build()
        self.assertIn('IRP not assigned', (self.root / '_site/index.html').read_text())
        self.assertIn('zenodo-100', (self.root / '_site/data/publications.csv').read_text())
        self.assertIn('10.1234/example', (self.root / '_site/data/publications.bib').read_text())
        proposal = self.root / 'proposal.json'
        proposal.write_text(json.dumps({'kind': 'publication', 'action': 'update', 'record': {
            'id': 'zenodo-100', 'irp_numbers': '14', 'researcher_names': 'Researcher One',
            'subjects': 'finance', 'title': 'Editorial correction'}}))
        import_proposal.apply_proposal(proposal, True)
        self.sync([record(102)])
        rows = build_site.inventory()['publications']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['title'], 'Editorial correction')


if __name__ == '__main__':
    unittest.main()
