#!/usr/bin/env python3
"""Apply the immutable proposal snapshot from a maintainer's approval-label event."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from build_site import ROOT, FILES

APPROVAL_LABEL = 'publication-approved'
APPLIED_LABEL = 'publication-applied'


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate JSON key: {key}')
        result[key] = value
    return result


def extract_proposal(body):
    # Exactly one fenced JSON block; never execute issue text or fetch attachments.
    blocks = re.findall(r'^```json[ \t]*\r?\n(.*?)^```[ \t]*\r?$', body or '', re.MULTILINE | re.DOTALL)
    if len(blocks) != 1:
        raise ValueError('The issue body must contain exactly one ```json proposal block. Paste attachment-only proposals into the issue before approval.')
    proposal = json.loads(blocks[0], object_pairs_hook=unique_object)
    if not isinstance(proposal, dict) or set(proposal) != {'kind', 'action', 'record'}:
        raise ValueError('Expected one proposal with kind, action and record')
    if proposal['kind'] not in FILES or proposal['action'] not in ('add', 'update') or not isinstance(proposal['record'], dict):
        raise ValueError('Invalid proposal kind, action or record')
    return proposal


def validate_event(event, repository, actor):
    issue = event.get('issue', {})
    number = issue.get('number')
    if (event.get('action') != 'labeled' or event.get('label', {}).get('name') != APPROVAL_LABEL
            or event.get('repository', {}).get('full_name') != repository
            or event.get('sender', {}).get('login') != actor
            or 'pull_request' in issue or type(number) is not int or number < 1):
        raise ValueError('Expected an approval-label event on an issue in this repository')
    if issue.get('state') != 'open':
        raise ValueError('Only open proposals can be approved')
    return issue


def assert_unchanged(snapshot, current):
    if current.get('body') != snapshot.get('body'):
        raise ValueError('Issue content changed after approval. Review it, then remove and re-add publication-approved.')
    if APPROVAL_LABEL not in {label['name'] for label in current.get('labels', [])}:
        raise ValueError('Approval was removed; no change will be applied')
    if current.get('state') != 'open' and APPLIED_LABEL not in {label['name'] for label in current.get('labels', [])}:
        raise ValueError('The issue was closed without being applied')


def can_approve(permission):
    return permission.get('permission') in {'admin', 'write', 'maintain'}


def run(args, *, check=True, input_text=None):
    return subprocess.run(args, cwd=ROOT, input=input_text, text=True, capture_output=True, check=check)


def api(endpoint, *, method='GET', payload=None):
    args = ['gh', 'api', '--method', method, endpoint]
    if payload is not None:
        args += ['--input', '-']
    response = run(args, input_text=json.dumps(payload) if payload is not None else None)
    return json.loads(response.stdout) if response.stdout.strip() else None


def approve(event, repository, actor):
    snapshot = validate_event(event, repository, actor)
    if not can_approve(api(f'repos/{repository}/collaborators/{actor}/permission')):
        raise ValueError('Approval requires repository write, maintain or admin permission; triage is insufficient')
    number = snapshot['number']
    endpoint = f'repos/{repository}/issues/{number}'
    assert_unchanged(snapshot, api(endpoint))
    proposal = extract_proposal(snapshot.get('body'))
    encoded = json.dumps(proposal, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    marker = f'Research-Proposal: {repository}#{number}:{digest}'
    commit = None
    # Separate issues can run concurrently. Reapply to the latest main after a rejected push.
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'proposal.json'
        path.write_text(encoded, encoding='utf-8')
        for attempt in range(5):
            run(['git', 'fetch', 'origin', 'main'])
            previous = run(['git', 'log', 'origin/main', '--format=%H', '--fixed-strings', f'--grep={marker}']).stdout.splitlines()
            if previous:
                commit = previous[0]
                break
            # This script runs only in a disposable Actions checkout, never in a user's working tree.
            run(['git', 'reset', '--hard', 'origin/main'])
            assert_unchanged(snapshot, api(endpoint))
            run([sys.executable, 'scripts/import_proposal.py', str(path), '--write'])
            run([sys.executable, 'update_README.py'])
            run([sys.executable, 'scripts/build_site.py'])
            changed = set(run(['git', 'diff', '--name-only']).stdout.splitlines())
            allowed = {f"data/{FILES[proposal['kind']]}", 'README.md'}
            if changed - allowed:
                raise ValueError('Proposal modified an unexpected path')
            run(['git', 'add', '--', *sorted(allowed)])
            # An empty audit commit records a valid no-op proposal and makes reruns idempotent.
            run(['git', 'commit', '--allow-empty', '-m', f'chore: apply research proposal #{number}', '-m', marker])
            assert_unchanged(snapshot, api(endpoint))
            pushed = run(['git', 'push', 'origin', 'HEAD:main'], check=False)
            if pushed.returncode == 0:
                commit = run(['git', 'rev-parse', 'HEAD']).stdout.strip()
                break
            if attempt == 4:
                raise ValueError('Could not push the approved change. Check branch protection and workflow permissions, then rerun this workflow.')
    # Bot commits do not trigger push workflows. Explicit dispatch works with GITHUB_TOKEN.
    api(f'repos/{repository}/actions/workflows/pages.yml/dispatches', method='POST', payload={'ref': 'main'})
    api(endpoint + '/labels', method='POST', payload={'labels': [APPLIED_LABEL]})
    api(endpoint, method='PATCH', payload={'state': 'closed', 'state_reason': 'completed'})
    summary = f'Applied approved proposal #{number}: https://github.com/{repository}/commit/{commit}\n\nPages deployment requested. See the Validate and deploy publications workflow for publication status.\n'
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write(summary)
    print(summary)
    return commit


if __name__ == '__main__':
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_EVENT_NAME') != 'issues':
        raise SystemExit('Run this script only through the research approval workflow; use import_proposal.py for local changes.')
    try:
        approve(json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text()), os.environ['GITHUB_REPOSITORY'], os.environ['GITHUB_ACTOR'])
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc))
    except subprocess.CalledProcessError as exc:
        # Avoid interpolating issue content into workflow commands or shell source.
        print(exc.stderr, file=sys.stderr)
        raise SystemExit('Approval failed. Check the failed step; fix the proposal and reapprove, or rerun after resolving a repository configuration problem.')
