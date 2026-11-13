#!/usr/bin/env python3
"""Validate a publication/working-paper proposal, or apply it with --write."""
import argparse
import csv
import json
import os
from pathlib import Path
import shutil
import tempfile
from build_site import ROOT, FILES, inventory, normalized_doi


def apply_proposal(path, write=False):
    proposal = json.loads(Path(path).read_text())
    kind, action, record = proposal['kind'], proposal['action'], proposal['record']
    if kind not in FILES or action not in {'add', 'update'} or not isinstance(record, dict):
        raise ValueError('Expected kind publication/working-paper, action add/update and a record object')
    target = ROOT / 'data' / FILES[kind]
    with target.open(newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fields, rows = reader.fieldnames, list(reader)
    if set(record) - set(fields):
        raise ValueError(f'Unknown fields: {sorted(set(record) - set(fields))}')
    if not all(isinstance(value, str) for value in record.values()):
        raise ValueError('All record fields must be strings')
    if record.get('doi'):
        record['doi'] = normalized_doi(record['doi'])
    matches = [i for i, r in enumerate(rows) if r['id'] == record.get('id')]
    if action == 'add':
        if matches:
            raise ValueError('ID already exists; update the existing record')
        rows.append({field: record.get(field, '') for field in fields})
    else:
        if not matches and kind == 'publication':
            # An approved update promotes a feed record to a curated override.
            imported = [r for r in inventory()['publications'] if r['id'] == record.get('id')]
            if len(imported) == 1:
                matches = [len(rows)]
                rows.append(imported[0].copy())
        if len(matches) != 1:
            raise ValueError('An update must use an existing stable ID')
        rows[matches[0]].update(record)
    with tempfile.TemporaryDirectory() as staging:
        staging_root = Path(staging)
        shutil.copytree(ROOT / 'data', staging_root / 'data')
        staged = staging_root / 'data' / FILES[kind]
        with staged.open('w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fields, lineterminator='\n')
            writer.writeheader(); writer.writerows(rows)
        inventory(staging_root)
        if write:
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as f:
                tmp = Path(f.name); f.write(staged.read_bytes())
            try:
                os.replace(tmp, target)
            finally:
                tmp.unlink(missing_ok=True)
    print(f"{'Applied' if write else 'Valid dry run for'} {action}: {kind}/{record['id']}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('proposal', type=Path)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    apply_proposal(args.proposal, args.write)
