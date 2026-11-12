"""Refresh only the generated publication index in README.md."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent / 'scripts'))
from build_site import ROOT, inventory


def main():
    data = inventory()
    start, end = '<!-- BEGIN RESEARCH -->', '<!-- END RESEARCH -->'
    path = ROOT / 'README.md'
    text = path.read_text()
    lines = [f"{len(data['publications'])} publication/preprint record(s); {len(data['working_papers'])} working paper(s).", '', '| Title | IRP | Year | Type |', '| --- | --- | --- | --- |']
    for collection in data.values():
        for row in collection:
            title = row['title'].replace('|', '\\|').replace('\n', ' ')
            label = f"[{title}]({row['link']})" if row.get('link') else title
            lines.append(f"| {label} | {row['irp_numbers']} | {row['year']} | {row.get('type') or row.get('status')} |")
    before, rest = text.split(start, 1)
    _, after = rest.split(end, 1)
    path.write_text(before + start + '\n' + '\n'.join(lines) + '\n' + end + after)

if __name__ == '__main__':
    main()
