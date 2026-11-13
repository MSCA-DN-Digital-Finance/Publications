#!/usr/bin/env python3
"""Validate research CSVs and build a static GitHub Pages publication catalogue."""
import csv
from datetime import date
import html
import json
from pathlib import Path
import re
import shutil
from urllib.parse import quote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
FILES = {'publication': 'publications.csv', 'working-paper': 'working-papers.csv'}
TYPES = {'journal-article': 'Journal article', 'conference-paper': 'Conference paper', 'preprint': 'Preprint', 'book-chapter': 'Book chapter', 'other': 'Other'}
STAGES = {'idea': 'Research idea', 'in-progress': 'In progress', 'draft': 'Draft available', 'under-review': 'Under review', 'paused': 'Paused', 'completed': 'Completed'}


def split(value):
    return [part.strip() for part in (value or '').split(';') if part.strip()]


def normalized_doi(value):
    return re.sub(r'^https?://(?:dx\.)?doi\.org/', '', value.strip(), flags=re.I).lower()


def validate_url(value):
    if not value:
        return True
    parsed = urlsplit(value)
    return parsed.scheme in {'http', 'https'} and bool(parsed.netloc) and not any(c.isspace() for c in value)


def read_records(kind, root=None, *, zenodo=False):
    path = (root or ROOT) / 'data' / ('zenodo-publications.csv' if zenodo else FILES[kind])
    with path.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError(f'{path}: missing or duplicate columns')
        rows = list(reader)
    seen = set()
    for line, row in enumerate(rows, 2):
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f'{path}:{line}: malformed CSV row')
        row.update({key: value.strip() for key, value in row.items()})
        required = ['id', 'title', 'authors'] if zenodo else ['id', 'irp_numbers', 'researcher_names', 'title', 'authors', 'subjects']
        for key in required:
            if not row.get(key):
                raise ValueError(f'{path}:{line}: {key} is required')
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', row['id']) or row['id'] in seen:
            raise ValueError(f'{path}:{line}: invalid or duplicate ID')
        seen.add(row['id'])
        invalid_subjects = not zenodo and not split(row['subjects'])
        invalid_irps = (row['irp_numbers'] or not zenodo) and not re.fullmatch(r'[1-9]\d*(?:;[1-9]\d*)*', row['irp_numbers'])
        if invalid_subjects or invalid_irps:
            raise ValueError(f'{path}:{line}: subjects and semicolon-separated IRP numbers are required')
        if row.get('year') and not re.fullmatch(r'(18|19|20|21)\d{2}', row['year']):
            raise ValueError(f'{path}:{line}: year must contain four digits')
        for key, value in row.items():
            if key.endswith('_url') or key == 'link':
                if not validate_url(value):
                    raise ValueError(f'{path}:{line}: {key} must be a public HTTP(S) URL')
        if row.get('last_updated'):
            date.fromisoformat(row['last_updated'])
        if kind == 'publication':
            if row.get('type') not in TYPES or not row.get('year') or not row.get('link'):
                raise ValueError(f'{path}:{line}: publication type, year and link are required')
            if not zenodo and row['type'] in {'journal-article', 'conference-paper', 'book-chapter'} and not row.get('venue'):
                raise ValueError(f'{path}:{line}: journal, conference or book title is required')
            if row.get('access') not in {'open-access', 'subscription', 'unknown'}:
                raise ValueError(f'{path}:{line}: invalid access status')
            if row.get('doi') and not re.fullmatch(r'10\.\d{4,9}/\S+', normalized_doi(row['doi'])):
                raise ValueError(f'{path}:{line}: invalid DOI')
            if row.get('publication_date'):
                value = row['publication_date']
                if not re.fullmatch(r'\d{4}-\d{2}(?:-\d{2})?', value):
                    raise ValueError(f'{path}:{line}: date must be YYYY-MM or YYYY-MM-DD')
                date.fromisoformat(value + '-01' if len(value) == 7 else value)
        else:
            if row.get('status') not in STAGES or row.get('open_to_collaborate') not in {'yes', 'no'} or not row.get('summary'):
                raise ValueError(f'{path}:{line}: working paper stage, summary and collaboration status are required')
            if row['open_to_collaborate'] == 'yes' and not (row.get('collaboration_needs') and row.get('contact_url')):
                raise ValueError(f'{path}:{line}: open collaboration needs a description and public contact/profile URL')
    return rows


def inventory(root=None):
    publications = read_records('publication', root)
    working = read_records('working-paper', root)
    cache = (root or ROOT) / 'data' / 'zenodo-publications.csv'
    if cache.exists():
        imported = read_records('publication', root, zenodo=True)
        # Curated rows override the feed by stable concept ID or normalized DOI.
        curated_ids = {row['id'] for row in publications}
        curated_dois = {normalized_doi(row['doi']) for row in publications if row.get('doi')}
        publications += [row for row in imported if row['id'] not in curated_ids and
                         (not row.get('doi') or normalized_doi(row['doi']) not in curated_dois)]
    if len({row['id'] for row in publications}) != len(publications):
        raise ValueError('Duplicate publication ID')
    dois = [normalized_doi(row['doi']) for row in publications if row.get('doi')]
    if len(dois) != len(set(dois)):
        raise ValueError('Duplicate DOI: update the existing publication instead of adding it again')
    ids = {r['id'] for r in publications}
    for row in working:
        unknown = set(split(row.get('related_publication_ids'))) - ids
        if unknown:
            raise ValueError(f"{row['id']}: unknown related publication IDs: {unknown}")
    return {'publications': publications, 'working_papers': working}


def bibtex(row):
    def escape(value):
        return str(value).replace('\\', '\\textbackslash{}').replace('{', '\\{').replace('}', '\\}').replace('\n', ' ')
    entry_type = {'journal-article': 'article', 'conference-paper': 'inproceedings', 'book-chapter': 'incollection'}.get(row['type'], 'misc')
    fields = {'title': row['title'], 'author': ' and '.join(split(row['authors'])), 'year': row['year'], 'url': row['link']}
    if row.get('venue'):
        fields['journal' if entry_type == 'article' else 'booktitle' if entry_type in {'inproceedings', 'incollection'} else 'howpublished'] = row['venue']
    for key in ['volume', 'issue', 'pages', 'doi']:
        if row.get(key):
            fields['number' if key == 'issue' else key] = normalized_doi(row[key]) if key == 'doi' else row[key]
    if row['type'] == 'preprint':
        fields['note'] = 'Preprint'
    return '@' + entry_type + '{' + row['id'] + ',\n' + ',\n'.join(f'  {key} = {{{escape(value)}}}' for key, value in fields.items()) + '\n}\n'


def render_record(row, kind, publications=None):
    e = lambda v: html.escape(str(v or ''), quote=True)
    def link(url, text):
        return f'<a href="{e(url)}" target="_blank" rel="noopener noreferrer">{e(text)} ↗</a>' if url else ''
    def fact(label, value):
        return f'<div><dt>{e(label)}</dt><dd>{e(value) if value else "Not provided"}</dd></div>'
    irps = '; '.join('IRP ' + n for n in split(row['irp_numbers'])) or 'IRP not assigned'
    is_pub = kind == 'publication'
    status = TYPES[row['type']] if is_pub else STAGES[row['status']]
    collaboration = not is_pub and row['open_to_collaborate'] == 'yes'
    badge = '<span class="badge collaborate">Open to collaborate</span>' if collaboration else '<span class="badge">Open access</span>' if is_pub and row.get('access') == 'open-access' else ''
    tags = ''.join(f'<span class="tag">{e(tag)}</span>' for tag in split(row['subjects']))
    title = link(row.get('link'), row['title']) if row.get('link') else e(row['title'])
    venue = ' · '.join(filter(None, [row.get('venue'), row.get('year')])) if is_pub else ' · '.join(filter(None, [status, row.get('year')]))
    facts = fact('Doctoral candidate(s)', row['researcher_names']) + fact('IRP', irps) + fact('Authors', '; '.join(split(row['authors'])))
    if is_pub:
        facts += fact('Publication type', status) + fact('Journal / conference / repository', row.get('venue')) + fact('Year / publication date', ' / '.join(filter(None, [row.get('year'), row.get('publication_date')])))
        facts += fact('Volume / issue', ' / '.join(filter(None, [row.get('volume'), row.get('issue')]))) + fact('Pages / article number', row.get('pages')) + fact('DOI', row.get('doi')) + fact('Access', {'open-access': 'Open access', 'subscription': 'Subscription / institutional', 'unknown': 'Not documented'}[row['access']]) + fact('Licence', row.get('license'))
    else:
        facts += fact('Stage', status) + fact('Collaboration', 'Open to collaborate' if collaboration else 'Not currently seeking collaborators')
        related = {r['id']: r for r in (publications or [])}
        related_links = [link('index.html#publication/' + rid, related[rid]['title']) for rid in split(row.get('related_publication_ids')) if rid in related]
        if related_links:
            facts += '<div><dt>Related publications</dt><dd>' + '<br>'.join(related_links) + '</dd></div>'
    facts += fact('Last metadata update', row.get('last_updated'))
    links = link(row.get('preprint_url'), 'Preprint') + link(row.get('code_url'), 'Code') + link(row.get('data_url'), 'Data') + link(row.get('researcher_url'), 'Researcher profile')
    if row.get('doi'):
        links += link('https://doi.org/' + quote(normalized_doi(row['doi']), safe='/'), 'DOI')
    if is_pub:
        links += f'<a href="citations/{e(row["id"])}.bib" download>Download BibTeX ↓</a>'
    collab = f'<div class="collaboration-note"><h3>Collaboration request</h3><p>{e(row.get("collaboration_needs"))}</p>{link(row.get("contact_url"), "Contact via public profile / discussion")}</div>' if collaboration else ''
    citation = f'<p class="citation">{e("; ".join(split(row["authors"])))} ({e(row.get("year"))}). {e(row["title"])}. {e(row.get("venue"))}{", " + e(row["volume"]) if row.get("volume") else ""}{", " + e(row["pages"]) if row.get("pages") else ""}.</p>' if is_pub else ''
    return f'''<article class="entry paper" id="paper-{e(row['id'])}" data-record-id="{e(row['id'])}"><div class="entry-top"><span class="entry-type">{e(status)} · {e(irps)}</span>{badge}</div><h2>{title}</h2><p class="authors">{e('; '.join(split(row['authors'])))}</p><div class="venue">{e(venue)}</div><div class="tags">{tags}</div>{'<p class="paper-summary">'+e(row['summary'])+'</p>' if row.get('summary') else ''}{collab}<details><summary>{'Details & citation' if is_pub else 'Working paper details'}</summary><dl class="detail-grid">{facts}</dl>{citation}<div class="paper-links">{links}</div><div class="details-actions"><a class="text-link" href="contribute.html?kind={kind}&amp;id={e(row['id'])}">Suggest an update ↗</a><button class="text-button" data-copy="{kind}/{e(row['id'])}">Copy record link</button></div><p class="provenance">{e(row.get('provenance'))}</p></details></article>'''


def build():
    data = inventory()
    out = ROOT / '_site'
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / 'site', out, ignore=shutil.ignore_patterns('config.json'))
    config = json.loads((ROOT / 'site/config.json').read_text())
    payload = json.dumps({**data, 'config': config}, ensure_ascii=False).replace('<', '\\u003c')
    for page in out.glob('*.html'):
        template = page.read_text()
        is_working = 'data-collection="working-paper"' in template
        kind = 'working-paper' if is_working else 'publication'
        records = data['working_papers' if is_working else 'publications']
        cards = ''.join(render_record(row, kind, data['publications']) for row in records)
        template = template.replace('<!-- RECORDS -->', cards).replace('<!-- RESEARCH_DATA -->', '<script type="application/json" id="research-data">' + payload + '</script>')
        if not records and 'id="records"' in template:
            template = template.replace('id="empty" class="empty" hidden', 'id="empty" class="empty"')
        page.write_text(template, encoding='utf-8')
    shutil.copytree(ROOT / 'data', out / 'data')
    # Publish the complete catalogue in the downloadable CSV as well as the page.
    with (out / 'data/publications.csv').open('w', newline='', encoding='utf-8') as f:
        with (ROOT / 'data/publications.csv').open(newline='', encoding='utf-8') as source:
            fields = csv.DictReader(source).fieldnames
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator='\n')
        writer.writeheader()
        writer.writerows(data['publications'])
    (out / 'data/publications.bib').write_text('\n'.join(bibtex(r) for r in data['publications']), encoding='utf-8')
    (out / 'citations').mkdir()
    for row in data['publications']:
        (out / 'citations' / (row['id'] + '.bib')).write_text(bibtex(row), encoding='utf-8')
    (out / '.nojekyll').touch()
    print(f"Built {len(data['publications'])} publications and {len(data['working_papers'])} working papers → {out}")

if __name__ == '__main__':
    build()
