# DIGITAL · Publications and working papers

Publication and collaboration catalogue for doctoral candidates in the MSCA Digital Finance network.

- [Publications and preprints](https://msca-dn-digital-finance.github.io/Publications/)
- [Working papers](https://msca-dn-digital-finance.github.io/Publications/working-papers.html)
- [Research resources home](https://msca-dn-digital-finance.github.io/)

## Submit and approve a record

Use **Add paper** on the website, or **Suggest an update** on a record. The form prepares a structured GitHub issue with the same `kind`, `action`, `record` format as the data inventory. Submit the issue after reviewing the JSON. Save draft and JSON download are available.

A maintainer with write, maintain or admin access reviews the issue and adds **`publication-approved`**. The approval workflow validates the proposal, updates its CSV and this generated index, commits to `main`, dispatches a Pages deployment, adds **`publication-applied`**, and closes the issue. No manual CSV editing or personal access token is needed.

The issue body must contain exactly one fenced `json` proposal. Paste attachment-only proposals into the body before approval. If the issue changes after approval, review it and remove/re-add the label. Invalid records leave the inventory unchanged. For a transient failure after the CSV commit, rerun the workflow: proposal hashes prevent duplicate imports. See **Actions → Apply approved research proposal** for failures and commit links. A successful approval requests deployment; the Pages workflow confirms publication.

## Data and metadata

`data/publications.csv` contains journal articles, conference papers, preprints, book chapters and other outputs. `data/working-papers.csv` contains research ideas and work in progress. Both include stable IDs, IRP numbers, doctoral candidate names, all authors, title, year, subjects, a short summary, paper/code/data links, metadata update date and provenance. Multiple IRPs, names, authors and subjects use semicolons.

Publications also include venue, DOI, preprint URL, volume, issue, pages/article number, publication date, access status, licence and an optional public researcher profile. DOIs are normalized and must be unique; update a preprint record when adding its publication details rather than duplicating the same DOI. A separate preprint URL can link the earlier version.

Working papers include stage, `open_to_collaborate` (`yes`/`no`), a description of collaboration needs, a public profile/discussion URL, and optional related publication IDs. Open collaboration requires both a description and public contact route. A public draft is optional. Mark completed work accordingly and link its resulting publication; do not mislabel unpublished work as a published article.

Publication types: `journal-article`, `conference-paper`, `preprint`, `book-chapter`, `other`. Working stages: `idea`, `in-progress`, `draft`, `under-review`, `paused`, `completed`. Access values: `open-access`, `subscription`, `unknown`. Use `YYYY-MM-DD` for `last_updated`, `YYYY-MM` or `YYYY-MM-DD` for publication dates, and four-digit years. A journal/conference/book venue is required for the corresponding publication type. Working papers require a summary. Leave unknown optional metadata blank.

All published metadata is public. Use public profiles instead of private contact details. Do not upload copyrighted full texts, credentials or private manuscripts to an issue; link to a permitted public version instead. The network funding acknowledgement does not assert that every listed paper received the same grant.

## Development and deployment

Python 3.9+ and its standard library are sufficient to build. The site uses no third-party runtime, fonts, analytics or API credentials.

```sh
python3 scripts/build_site.py
python3 -m unittest discover -s tests -v
python3 update_README.py
python3 -m http.server 8000 --directory _site
```

For an optional local import:

```sh
python3 scripts/import_proposal.py /path/to/proposal.json
python3 scripts/import_proposal.py /path/to/proposal.json --write
```

Updates merge provided fields; empty supplied values clear them. Failed validations and dry-runs never touch the live CSV. Approved changes are checked in a disposable workflow checkout, never by running issue-supplied code. Direct pushes to `main` must be permitted for the approval workflow; protections are not bypassed.

Enable **Settings → Pages → Source → GitHub Actions**. `pages.yml` builds/tests pull requests and deploys `main`. Relative asset links work under `/Publications/`. Shared navigation points to the organization landing site and the data inventory, maintained in separate repos. Generated `_site/` is ignored.

The first paper's citation was verified using [Crossref's DOI record](https://api.crossref.org/works/10.1016/j.knosys.2025.114449) and [Elsevier's article metadata](https://api.elsevier.com/content/article/pii/S0950705125014881). The IRP 14 association was supplied by the author; subject tags are editorial. No working papers were invented to populate the empty section.

<!-- BEGIN RESEARCH -->
1 publication/preprint record(s); 0 working paper(s).

| Title | IRP | Year | Type |
| --- | --- | --- | --- |
| [Enhancing large language models for bitcoin time series forecasting](https://www.sciencedirect.com/science/article/pii/S0950705125014881) | 14 | 2025 | journal-article |
<!-- END RESEARCH -->
