#!/usr/bin/env python3
"""Sync public DIGITAL community publication metadata; dry-run unless --write."""
import argparse
import csv
from datetime import date
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from build_site import ROOT, inventory, normalized_doi

COMMUNITY = 'digitalfinance'
API = 'https://zenodo.org/api/records'
CACHE = 'zenodo-publications.csv'
USER_AGENT = 'DigitalFinancePublications/1.0 (+https://github.com/MSCA-DN-Digital-Finance/Publications)'
PAGE_SIZE = 25  # Anonymous search limit; no Zenodo credentials needed.


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.hidden += 1
        if tag in {'p', 'div', 'br', 'li'}:
            self.parts.append(' ')

    def handle_endtag(self, tag):
        if tag in {'script', 'style'}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {'p', 'div', 'li'}:
            self.parts.append(' ')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def text(value):
    parser = PlainText()
    parser.feed(str(value or ''))
    return ' '.join(''.join(parser.parts).split())


def request_json(url):
    request = Request(url, headers={'Accept': 'application/json', 'User-Agent': USER_AGENT})
    for attempt in range(4):
        try:
            with urlopen(request, timeout=45) as response:
                return json.load(response)
        except HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 3:
                raise
            retry_after = exc.headers.get('Retry-After', '')
            delay = float(retry_after) if retry_after.isdigit() else 3 * 2 ** attempt
            time.sleep(min(max(delay, 2.1), 60))
        except (URLError, TimeoutError):
            if attempt == 3:
                raise
            time.sleep(3 * 2 ** attempt)


def fetch_records():
    records, ids = [], set()
    expected = None
    for page in range(1, 1001):
        params = {'communities': COMMUNITY, 'type': 'publication', 'status': 'published',
                  'all_versions': 'false', 'sort': 'mostrecent', 'size': PAGE_SIZE, 'page': page}
        payload = request_json(API + '?' + urlencode(params))
        hits = payload['hits']
        total = hits['total']
        if isinstance(total, dict):
            if total.get('relation', 'eq') != 'eq':
                raise ValueError('Zenodo returned an inexact total; refusing a partial sync')
            total = total['value']
        if type(total) is not int or total < 0 or not isinstance(hits['hits'], list):
            raise ValueError('Invalid Zenodo search response')
        if expected is not None and total != expected:
            raise ValueError('Community changed during pagination; rerun the sync')
        expected = total
        for record in hits['hits']:
            rid = str(record['id'])
            if rid in ids:
                raise ValueError('Duplicate record across pages; rerun the sync')
            ids.add(rid)
            metadata = record['metadata']
            if (COMMUNITY not in {c['id'] for c in metadata.get('communities', [])} or
                    metadata.get('resource_type', {}).get('type') != 'publication' or
                    record.get('status') != 'published'):
                raise ValueError('Zenodo returned a record outside the requested publication scope')
            records.append(record)
        if len(records) == expected:
            return records
        if not hits['hits'] or len(records) > expected:
            raise ValueError('Incomplete Zenodo search response; refusing a partial sync')
        time.sleep(2.1)  # Stay below the documented 30 search requests/minute.
    raise ValueError('Community exceeds the sync pagination limit')


def publication(record, fields):
    metadata = record['metadata']
    rid = str(record['id'])
    concept = str(record.get('conceptrecid') or rid)
    if not rid.isdigit() or not concept.isdigit():
        raise ValueError('Invalid Zenodo record/concept ID')
    resource = metadata['resource_type']
    if resource.get('type') != 'publication':
        raise ValueError('Only publication records can enter the publication catalogue')
    subtype = resource.get('subtype', '')
    kind = {'article': 'journal-article', 'conferencepaper': 'conference-paper',
            'preprint': 'preprint', 'section': 'book-chapter'}.get(subtype, 'other')
    published = str(metadata['publication_date'])
    if not re.fullmatch(r'\d{4}(?:-\d{2}(?:-\d{2})?)?', published):
        raise ValueError(f'{rid}: invalid publication date')
    journal = metadata.get('journal') or {}
    venue = journal.get('title') or (metadata.get('part_of') or {}).get('title') or ''
    if kind == 'conference-paper':
        venue = (metadata.get('meeting') or {}).get('title') or venue
    elif kind == 'book-chapter':
        venue = venue or (metadata.get('imprint') or {}).get('book_title', '')
    modified = str(record.get('modified') or record.get('updated') or '')
    updated = modified[:10] if modified else published if len(published) == 10 else ''
    if updated:
        date.fromisoformat(updated)
    url = f'https://zenodo.org/records/{rid}'
    row = {field: '' for field in fields}
    row.update(
        id='zenodo-' + concept, title=text(metadata['title']),
        authors=';'.join(text(c['name']).replace(';', ',') for c in metadata['creators']),
        year=published[:4], subjects=';'.join(text(k).replace(';', ',') for k in metadata.get('keywords', [])),
        summary=text(metadata.get('description')), link=url, last_updated=updated,
        provenance=f'Zenodo community {COMMUNITY}: {url}. Source metadata modified: {modified or "not supplied"}.',
        type=kind, venue=text(venue), doi=normalized_doi(metadata.get('doi') or record.get('doi') or ''),
        preprint_url=url if kind == 'preprint' else '',
        publication_date=published if len(published) > 4 else '',
        volume=text(journal.get('volume')), issue=text(journal.get('issue')), pages=text(journal.get('pages')),
        access='open-access' if metadata.get('access_right') == 'open' else 'unknown',
        license=text((metadata.get('license') or {}).get('id')),
    )
    # Candidate identities and IRPs require editorial knowledge; authors are not all candidates.
    return row


def sync_records(records, *, root=None, write=False):
    root = root or ROOT
    target = root / 'data' / CACHE
    with (root / 'data/publications.csv').open(encoding='utf-8', newline='') as source:
        fields = csv.DictReader(source).fieldnames
    rows, concepts, dois = [], set(), set()
    # A DOI may have been deposited separately more than once. Prefer its newest metadata.
    ordered = sorted(records, key=lambda r: (str(r.get('modified') or r.get('updated') or ''), str(r['id'])), reverse=True)
    for record in ordered:
        row = publication(record, fields)
        if row['id'] in concepts:
            raise ValueError('Multiple versions of one concept returned; refusing ambiguous sync')
        concepts.add(row['id'])
        if row['doi'] and row['doi'] in dois:
            continue
        if row['doi']:
            dois.add(row['doi'])
        rows.append(row)
    rows.sort(key=lambda r: r['id'])
    with tempfile.TemporaryDirectory() as staging:
        staging_root = Path(staging)
        shutil.copytree(root / 'data', staging_root / 'data')
        staged = staging_root / 'data' / CACHE
        with staged.open('w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fields, lineterminator='\n')
            writer.writeheader()
            writer.writerows(rows)
        combined = inventory(staging_root)
        content = staged.read_bytes()
    changed = not target.exists() or target.read_bytes() != content
    if write and changed:
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as f:
            temporary = Path(f.name)
            f.write(content)
        try:
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    print(f'{"Synced" if write else "Dry run:"} {len(rows)} Zenodo publication(s); '
          f'{len(combined["publications"])} catalogue record(s); '
          f'{"changes found" if changed else "unchanged"}.')
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true', help='Replace the validated Zenodo metadata cache')
    args = parser.parse_args()
    try:
        sync_records(fetch_records(), write=args.write)
    except (ValueError, KeyError, TypeError, HTTPError, URLError, TimeoutError) as exc:
        raise SystemExit(f'Zenodo sync failed; existing data was preserved: {exc}') from exc


if __name__ == '__main__':
    main()
