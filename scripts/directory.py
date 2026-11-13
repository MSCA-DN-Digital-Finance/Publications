"""Shared IRP dictionary validation, identity matching and catalogue enrichment.

The organization repository owns data/people.json. Consumer repositories keep a
validated snapshot; --sync refreshes it without requiring credentials.
"""
import argparse
import json
import os
from pathlib import Path
import re
import tempfile
import time
import unicodedata
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY_URL = 'https://raw.githubusercontent.com/MSCA-DN-Digital-Finance/MSCA-DN-Digital-Finance.github.io/main/data/people.json'


def public_url(value):
    return isinstance(value, str) and urlsplit(value).scheme in {'http', 'https'} and bool(urlsplit(value).netloc) and not any(c.isspace() for c in value)


def orcid_id(value):
    value = re.sub(r'^https?://orcid\.org/', '', str(value or '').strip(), flags=re.I).upper()
    return value if re.fullmatch(r'\d{4}-\d{4}-\d{4}-\d{3}[\dX]', value) else ''


def name_key(value):
    value = ''.join(c for c in unicodedata.normalize('NFKD', str(value)) if not unicodedata.combining(c))
    # Full names only: order and punctuation may differ, initials are not expanded.
    return tuple(sorted(re.findall(r'[^\W_]+', value.casefold(), re.UNICODE)))


def validate(payload):
    if not isinstance(payload, dict) or payload.get('schema_version') != 1 or not isinstance(payload.get('projects'), list) or not payload['projects']:
        raise ValueError('Invalid people dictionary schema')
    numbers, slugs, orcids = set(), set(), set()
    for project in payload['projects']:
        number = project.get('number')
        if not isinstance(number, str) or not re.fullmatch(r'[1-9]\d*', number) or number in numbers:
            raise ValueError('Invalid or duplicate IRP number')
        numbers.add(number)
        if any(not isinstance(project.get(k), str) or not project[k].strip() for k in ['title', 'short_title', 'host']):
            raise ValueError(f'IRP {number}: title, short title and host required')
        if not public_url(project.get('source_url')):
            raise ValueError('Invalid IRP source URL')
        candidate = project.get('candidate')
        if candidate is None:
            continue
        if not isinstance(candidate, dict) or not isinstance(candidate.get('name'), str) or len(name_key(candidate['name'])) < 2:
            raise ValueError('Invalid candidate name')
        slug = candidate.get('id', '')
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug) or slug in slugs:
            raise ValueError('Invalid or duplicate candidate ID')
        slugs.add(slug)
        if not isinstance(candidate.get('affiliations'), list) or not candidate['affiliations'] or not all(isinstance(a, str) and a.strip() for a in candidate['affiliations']):
            raise ValueError('Candidate affiliations required')
        if not public_url(candidate.get('source_url')) or not isinstance(candidate.get('links'), dict):
            raise ValueError('Candidate source and public links required')
        for label, url in candidate['links'].items():
            if not isinstance(label, str) or not public_url(url):
                raise ValueError('Invalid public profile link')
        value = candidate.get('orcid', '')
        if value:
            if orcid_id(value) != value or value in orcids:
                raise ValueError('Invalid or duplicate candidate ORCID')
            orcids.add(value)
    return payload


def load(root=None):
    path = (root or ROOT) / 'data/people.json'
    return validate(json.loads(path.read_text(encoding='utf-8')))['projects'] if path.exists() else []


def match_creators(creators, projects):
    matches = {}
    assigned = [p for p in projects if p.get('candidate')]
    for creator in creators:
        identifier = orcid_id(creator.get('orcid'))
        exact = [p for p in assigned if identifier and p['candidate'].get('orcid') == identifier]
        if not exact:
            key = name_key(creator.get('name', ''))
            exact = [p for p in assigned if len(key) >= 2 and name_key(p['candidate']['name']) == key and
                     not (identifier and p['candidate'].get('orcid') and p['candidate']['orcid'] != identifier)]
        if len(exact) == 1:
            matches[exact[0]['number']] = exact[0]
    return sorted(matches.values(), key=lambda p: int(p['number']))


def enrich(row, projects, irp_field='irp_numbers'):
    row = dict(row)
    by_number = {p['number']: p for p in projects}
    numbers = list(dict.fromkeys(n.strip() for n in re.split(r'[;,]', row.get(irp_field, '')) if n.strip()))
    row[irp_field] = ';'.join(numbers)
    known = [by_number[n] for n in numbers if n in by_number]
    row['irp_titles'] = ';'.join(p['title'] for p in known)
    if known and len(known) == len(numbers):
        row['researcher_names'] = ';'.join(p['candidate']['name'] for p in known if p.get('candidate'))
    return row


def fetch_json(url):
    for attempt in range(3):
        try:
            request = Request(url, headers={'User-Agent': 'DigitalFinanceDirectory/1.0 (+https://github.com/MSCA-DN-Digital-Finance)', 'Accept': 'application/json'})
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except OSError:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def write_json(path, value):
    content = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    if path.exists() and path.read_bytes() == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        stream.write(content)
        temporary = Path(stream.name)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def sync(root=None):
    root = root or ROOT
    payload = validate(fetch_json(DIRECTORY_URL))
    previous = {p['number'] for p in load(root)}
    if previous - {p['number'] for p in payload['projects']}:
        raise ValueError('Directory unexpectedly removed IRPs; review the canonical source')
    changed = write_json(root / 'data/people.json', payload)
    print(f'People dictionary: {len(payload["projects"])} IRPs; {"updated" if changed else "unchanged"}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sync', action='store_true')
    args = parser.parse_args()
    if args.sync:
        sync()
    else:
        print(f'Validated {len(load())} IRPs')
