"""Persist public progress and pin/restore an externally verified Pages artifact.

Only the explicit JSON state paths and four standalone site files may be copied.
The release-good branch is an artifact branch, never the cumulative data branch.
"""
from pathlib import Path
import json
import os
import re
import subprocess
import tempfile
import datetime
import hashlib
from urllib.parse import urlsplit, unquote

ROOT = Path(__file__).resolve().parents[1]

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def read(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default

def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temporary.replace(path)

def digest(value):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()

SITE_FILES = ('index.html', 'records.json', 'manifest.json', '.nojekyll')
STATE_FILES = ('data/records.json', 'data/update-state.json', 'data/review-queue.json', 'data/status.json', 'data/publication-status.json', 'data/runtime-status.json')
STATE_DIRS = ('reports/runs',)
GOOD_REF = 'refs/heads/release-good'
BOT_ENV = {
    'GIT_AUTHOR_NAME': 'ophthalmic-library-bot', 'GIT_AUTHOR_EMAIL': 'ophthalmic-library-bot@users.noreply.github.com',
    'GIT_COMMITTER_NAME': 'ophthalmic-library-bot', 'GIT_COMMITTER_EMAIL': 'ophthalmic-library-bot@users.noreply.github.com',
}


def git(root, *args, content=None, env=None):
    result = subprocess.run(['git', *args], cwd=root, input=content, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env={**os.environ, **BOT_ENV, **(env or {})}, timeout=90)
    if result.returncode:
        # Do not echo remote URLs or credentials from Git diagnostics into public JSON.
        raise RuntimeError('git ' + args[0] + ' failed (exit ' + str(result.returncode) + ')')
    return result.stdout


def authorize(root, environment=None):
    environment = os.environ if environment is None else environment
    config = read(root / 'config/deployment.json', {})
    repository = environment.get('GITHUB_REPOSITORY', '')
    branch = environment.get('GITHUB_REF_NAME', '')
    if config.get('public_scope_approved') is not True:
        raise ValueError('Publication scope has not been approved')
    if not repository or config.get('repository') != repository:
        raise ValueError('Wrong target repository')
    if not branch or branch == 'release-good' or environment.get('GITHUB_REF_TYPE', 'branch') != 'branch':
        raise ValueError('A source branch is required')
    base = urlsplit(config.get('https_base_url', ''))
    if base.scheme != 'https' or not base.netloc or base.username or base.password or base.query or base.fragment:
        raise ValueError('Approved HTTPS endpoint not configured')
    for field, filename in [('status_url', 'publication-status.json'), ('runtime_status_url', 'runtime-status.json')]:
        url = urlsplit(config.get(field, ''))
        expected = '/' + repository + '/' + branch + '/data/' + filename
        if (url.scheme != 'https' or url.netloc != 'raw.githubusercontent.com' or url.username
                or url.password or url.query or url.fragment or unquote(url.path) != expected):
            raise ValueError(field + ' must be the exact target repository/source branch raw receipt URL')
    return {'repository': repository, 'branch': branch, 'approved': True}


def state_allowed(name):
    return name in STATE_FILES or any(re.fullmatch(re.escape(folder) + r'/[^/]+\.json', name)
                                     for folder in STATE_DIRS)


def regular_file(root, relative):
    root = root.resolve()
    relative_path = Path(relative)
    if relative_path.is_absolute() or '..' in relative_path.parts:
        raise ValueError('path is outside the approved directory')
    path = root / relative_path
    for item in (path, *path.parents):
        if item == root:
            break
        if item.is_symlink():
            raise ValueError('symlink is not an approved public file: ' + relative)
    if not path.is_file():
        raise ValueError('required public file missing: ' + relative)
    return path


def state_paths(root):
    tracked = git(root, 'ls-files', '-z').decode().split('\0')
    names = {p for p in tracked if p and state_allowed(p)}
    names.update(p for p in STATE_FILES if (root / p).exists())
    for folder in STATE_DIRS:
        names.update(str(p.relative_to(root)) for p in (root / folder).glob('*.json'))
    for name in names:
        if (root / name).exists() or (root / name).is_symlink():
            json.loads(regular_file(root, name).read_text())
    return sorted(names)


def persist(root, branch, remote='origin'):
    """Commit only approved cumulative state, including deleted checkpoints."""
    if branch == 'release-good':
        raise ValueError('the artifact branch cannot hold cumulative source state')
    git(root, 'check-ref-format', 'refs/heads/' + branch)
    head = git(root, 'rev-parse', 'HEAD').decode().strip()
    paths = state_paths(root)
    if not paths:
        return head
    with tempfile.TemporaryDirectory() as directory:
        env = {'GIT_INDEX_FILE': str(Path(directory) / 'index')}
        git(root, 'read-tree', head, env=env)
        git(root, 'add', '-A', '--', *paths, env=env)
        tree = git(root, 'write-tree', env=env).decode().strip()
    old_tree = git(root, 'rev-parse', head + '^{tree}').decode().strip()
    if tree == old_tree:
        return head
    commit = git(root, 'commit-tree', tree, '-p', head,
                 content=b'Persist Ophthalmic cumulative progress and runtime outcome [skip ci]\n').decode().strip()
    git(root, 'push', remote, commit + ':refs/heads/' + branch)
    git(root, 'update-ref', 'HEAD', commit, head)
    return commit


def remote_good(root, remote='origin'):
    refs = git(root, 'ls-remote', '--heads', remote, GOOD_REF).decode().strip()
    if not refs:
        return None
    commit = refs.split()[0]
    if not re.fullmatch(r'[0-9a-f]{40,64}', commit):
        raise ValueError('invalid release commit')
    git(root, 'fetch', '--no-tags', remote, commit)
    return commit


def validate_site(files, receipt):
    if set(files) != set(SITE_FILES):
        raise ValueError('unexpected artifact files')
    manifest = json.loads(files['manifest.json'])
    records = json.loads(files['records.json'])
    if not records or not isinstance(records, list):
        raise ValueError('empty public records')
    if not receipt.get('deployed') or not receipt.get('verified_at') or receipt.get('domain_id') != 'ophthalmic-surgery':
        raise ValueError('no external verification receipt')
    if manifest.get('version') != receipt.get('data_version'):
        raise ValueError('manifest version mismatch')
    for name in SITE_FILES:
        if digest(files[name]) != receipt.get('file_hashes', {}).get(name):
            raise ValueError('artifact hash mismatch: ' + name)
    if receipt['data_version'].encode() not in files['index.html']:
        raise ValueError('HTML version mismatch')


def pin_good(root, site, remote='origin'):
    receipt = read(root / 'data/publication-status.json', {})
    if receipt.get('rollback'):
        raise ValueError('a rollback must not replace the last-good release')
    if os.environ.get('GITHUB_RUN_ID') and receipt.get('run_id') != os.environ['GITHUB_RUN_ID']:
        raise ValueError('external receipt belongs to a different run')
    files = {name: regular_file(site, name).read_bytes() for name in SITE_FILES}
    validate_site(files, receipt)
    previous = remote_good(root, remote)
    manifest = {'schema_version': 1, 'domain_id': 'ophthalmic-surgery', 'receipt': receipt,
                'files': {name: digest(body) for name, body in files.items()}}
    files['release.json'] = json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode()
    entries = []
    for name, body in sorted(files.items()):
        blob = git(root, 'hash-object', '-w', '--stdin', content=body).decode().strip()
        entries.append('100644 blob ' + blob + '\t' + name + '\n')
    tree = git(root, 'mktree', content=''.join(entries).encode()).decode().strip()
    parent = ['-p', previous] if previous else []
    commit = git(root, 'commit-tree', tree, *parent,
                 content=('Externally verified Ophthalmic release ' + receipt['data_version'] + '\n').encode()).decode().strip()
    # A normal fast-forward push protects a concurrently advanced last-good pointer.
    git(root, 'push', remote, commit + ':' + GOOD_REF)
    return commit


def restore_good(root, destination, remote='origin'):
    commit = remote_good(root, remote)
    if commit is None:
        return {'available': False, 'status': 'unavailable', 'reason': 'No externally verified previous release exists'}
    names = git(root, 'ls-tree', '--name-only', commit).decode().splitlines()
    if set(names) != set(SITE_FILES) | {'release.json'}:
        raise ValueError('unexpected files in the release-good artifact')
    manifest = json.loads(git(root, 'show', commit + ':release.json'))
    if set(manifest.get('files', {})) != set(SITE_FILES):
        raise ValueError('release manifest is incomplete')
    files = {name: git(root, 'show', commit + ':' + name) for name in SITE_FILES}
    if any(digest(body) != manifest['files'][name] for name, body in files.items()):
        raise ValueError('release manifest checksum mismatch')
    validate_site(files, manifest['receipt'])
    # Fresh destination prevents stale workspace files from entering the recovery upload.
    destination.mkdir(parents=True, exist_ok=False)
    for name, body in files.items():
        (destination / name).write_bytes(body)
    write(destination / 'release.json', {**manifest, 'commit': commit})
    return {'available': True, 'status': 'ready', 'commit': commit,
            'data_version': manifest['receipt']['data_version']}


def start_runtime(root):
    old = read(root / 'data/runtime-status.json', {})
    receipt = read(root / 'data/publication-status.json', {})
    stamp = now()
    event = os.environ.get('GITHUB_EVENT_NAME')
    result = {
        'domain_id': 'ophthalmic-surgery', 'schema_version': 1, 'status': 'running',
        'started_at': stamp, 'finished_at': None, 'event': event,
        'run_id': os.environ.get('GITHUB_RUN_ID'),
        'run_url': 'https://github.com/' + os.environ.get('GITHUB_REPOSITORY', '')
                   + '/actions/runs/' + os.environ.get('GITHUB_RUN_ID', ''),
        'observed_scheduled_run': (stamp if event == 'schedule' else
                                   old.get('observed_scheduled_run') or receipt.get('observed_scheduled_run')),
        'steps': {}, 'rollback': {'status': 'not_checked'}, 'last_errors': [], 'last_counts': {},
    }
    state = read(root / 'data/status.json', {})
    state.update(last_attempt=stamp, last_attempt_status='running', last_counts={}, last_errors=[])
    write(root / 'data/status.json', state)
    write(root / 'data/runtime-status.json', result)
    return result


def finish_runtime(root, step_results):
    runtime = read(root / 'data/runtime-status.json', {})
    state = read(root / 'data/status.json', {})
    steps = {name: {'outcome': value.get('outcome'), 'conclusion': value.get('conclusion')}
             for name, value in step_results.items()}
    failed = [name for name, value in steps.items() if value['outcome'] in ('failure', 'cancelled')]
    for name in ('dependencies','update','tests','pages_config','upload','deployment','verification','pin'):
        if steps.get(name,{}).get('outcome') != 'success' and name not in failed:
            failed.append(name)
            steps.setdefault(name, {'outcome':'not_successful','conclusion':'failure'})
    runtime.update(finished_at=now(), steps=steps,
                   last_counts=state.get('last_counts', {}),
                   status='failed' if failed else ('partial' if state.get('last_outcome') == 'partial' else 'success'),
                   last_errors=list(state.get('last_errors', [])) +
                   [{'source': name, 'reason': 'Workflow step ' + steps[name]['outcome']} for name in failed])
    rollback = runtime.setdefault('rollback', {})
    if steps.get('rollback_check', {}).get('outcome') == 'success':
        rollback.update(status='verified', verified_at=read(root / 'data/publication-status.json', {}).get('verified_at'))
    elif any(steps.get(name, {}).get('outcome') in ('failure', 'cancelled') for name in ('rollback', 'rollback_check')):
        rollback['status'] = 'failed'
    if failed:
        # Retain successful source watermarks; only the attempt outcome changes.
        state.update(last_attempt=runtime.get('started_at', now()), last_attempt_status='failed',
                     last_errors=runtime['last_errors'])
        write(root / 'data/status.json', state)
    write(root / 'data/runtime-status.json', runtime)
    return runtime


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('authorize', 'start', 'finish', 'persist', 'restore', 'pin'))
    parser.add_argument('--branch', default=os.environ.get('GITHUB_REF_NAME', ''))
    parser.add_argument('--directory', type=Path)
    args = parser.parse_args()
    if args.action == 'authorize':
        result = authorize(ROOT)
    elif args.action == 'start':
        result = start_runtime(ROOT)
    elif args.action == 'finish':
        result = finish_runtime(ROOT, json.loads(os.environ.get('OPHTH_STEP_RESULTS', '{}')))
    elif args.action == 'persist':
        result = {'commit': persist(ROOT, args.branch)}
    elif args.action == 'pin':
        result = {'commit': pin_good(ROOT, args.directory or ROOT / 'site')}
    else:
        result = restore_good(ROOT, args.directory or ROOT / 'previous-site')
        runtime = read(ROOT / 'data/runtime-status.json', {})
        runtime['rollback'] = result
        write(ROOT / 'data/runtime-status.json', runtime)
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a') as out:
                out.write('available=' + str(result['available']).lower() + '\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
