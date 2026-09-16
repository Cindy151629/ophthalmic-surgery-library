"""Offline recovery tests: every Git repository and remote lives in TemporaryDirectory."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import cloud_recovery as recovery
import deploy_check


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / 'repo'
        self.remote = self.base / 'remote.git'
        self.root.mkdir()
        self.remote.mkdir()
        recovery.git(self.root, 'init', '-b', 'main')
        recovery.git(self.root, 'config', 'core.hooksPath', '/dev/null')
        recovery.git(self.remote, 'init', '--bare')
        recovery.git(self.remote, 'config', 'core.hooksPath', '/dev/null')
        recovery.git(self.root, 'remote', 'add', 'origin', str(self.remote))
        self.put('README.md', 'base\n')
        recovery.write(self.root / 'data/records.json', [{'id': 'retained', 'note': 'curated'}])
        recovery.write(self.root / 'data/update-state.json', {'watermark': 'previous'})
        recovery.git(self.root, 'add', 'README.md', 'data/records.json', 'data/update-state.json')
        recovery.git(self.root, 'commit', '-m', 'fixture')
        recovery.git(self.root, 'push', 'origin', 'HEAD:refs/heads/main')
        self.site = self.base / 'site'
        self.site.mkdir()
        self.files = {
            'index.html': b'<!doctype html><main data-version="version-1">reader</main>',
            'records.json': b'[{"id":"retained","note":"curated"}]',
            'manifest.json': b'{"version":"version-1","records":1}',
            '.nojekyll': b'',
        }
        for name, body in self.files.items():
            (self.site / name).write_bytes(body)
        self.receipt = {
            'domain_id': 'ophthalmic-surgery', 'deployed': True,
            'verified_at': '2026-09-16T00:00:00+00:00', 'data_version': 'version-1',
            'file_hashes': {name: recovery.digest(body) for name, body in self.files.items()},
            'run_id': 'fixture-run', 'rollback': False,
            'https_url': 'https://owner.github.io/library/',
        }
        recovery.write(self.root / 'data/publication-status.json', self.receipt)
        self.env = patch.dict(os.environ, {'GITHUB_RUN_ID': 'fixture-run',
                                          'GITHUB_REPOSITORY': 'owner/library',
                                          'GITHUB_EVENT_NAME': 'workflow_dispatch'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def put(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def release_commit(self, files):
        """Publish a fixture corruption only to the temporary bare remote."""
        old = recovery.remote_good(self.root)
        rows = []
        for name, body in sorted(files.items()):
            blob = recovery.git(self.root, 'hash-object', '-w', '--stdin', content=body).decode().strip()
            rows.append('100644 blob ' + blob + '\t' + name + '\n')
        tree = recovery.git(self.root, 'mktree', content=''.join(rows).encode()).decode().strip()
        commit = recovery.git(self.root, 'commit-tree', tree, '-p', old,
                              content=b'fixture artifact mutation\n').decode().strip()
        recovery.git(self.root, 'push', 'origin', commit + ':' + recovery.GOOD_REF)

    def pinned_files(self):
        commit = recovery.remote_good(self.root)
        names = recovery.git(self.root, 'ls-tree', '--name-only', commit).decode().splitlines()
        return {name: recovery.git(self.root, 'show', commit + ':' + name) for name in names}

    def test_pin_and_restore_exact_four_hashes(self):
        commit = recovery.pin_good(self.root, self.site)
        target = self.base / 'restored'
        result = recovery.restore_good(self.root, target)
        self.assertTrue(result['available'])
        self.assertEqual(result['commit'], commit)
        self.assertEqual(set(self.pinned_files()), set(recovery.SITE_FILES) | {'release.json'})
        for name, body in self.files.items():
            self.assertEqual((target / name).read_bytes(), body)

    def test_pin_rejects_hash_mismatch_for_each_required_file(self):
        for name, original in self.files.items():
            with self.subTest(name=name):
                changed = (b'{"version":"version-2","records":1}' if name == 'manifest.json'
                           else b'[{"id":"changed"}]' if name == 'records.json' else original + b'x')
                (self.site / name).write_bytes(changed)
                with self.assertRaises(ValueError):
                    recovery.pin_good(self.root, self.site)
                (self.site / name).write_bytes(original)
        self.assertIsNone(recovery.remote_good(self.root))

    def test_pin_rejects_missing_nojekyll(self):
        (self.site / '.nojekyll').unlink()
        with self.assertRaises(ValueError):
            recovery.pin_good(self.root, self.site)

    def test_pin_rejects_stale_run_and_rollback_receipts(self):
        for change in [{'run_id': 'old-run'}, {'rollback': True}]:
            with self.subTest(change=change):
                recovery.write(self.root / 'data/publication-status.json', {**self.receipt, **change})
                with self.assertRaises(ValueError):
                    recovery.pin_good(self.root, self.site)
        self.assertIsNone(recovery.remote_good(self.root))

    def test_pin_ignores_non_site_files_in_artifact_branch(self):
        (self.site / 'private-cache.txt').write_text('fixture must not be pinned')
        recovery.pin_good(self.root, self.site)
        self.assertNotIn('private-cache.txt', self.pinned_files())

    def test_restore_rejects_changed_payload_before_creating_destination(self):
        recovery.pin_good(self.root, self.site)
        files = self.pinned_files()
        files['records.json'] = b'[{"id":"corrupt"}]'
        self.release_commit(files)
        target = self.base / 'recovery'
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            recovery.restore_good(self.root, target)
        self.assertFalse(target.exists())

    def test_restore_checks_receipt_hashes_as_well_as_release_manifest(self):
        recovery.pin_good(self.root, self.site)
        files = self.pinned_files()
        files['index.html'] += b'changed'
        manifest = json.loads(files['release.json'])
        manifest['files']['index.html'] = recovery.digest(files['index.html'])
        files['release.json'] = json.dumps(manifest).encode()
        self.release_commit(files)
        with self.assertRaisesRegex(ValueError, 'artifact hash mismatch'):
            recovery.restore_good(self.root, self.base / 'recovery')

    def test_restore_rejects_unapproved_extra_file(self):
        recovery.pin_good(self.root, self.site)
        files = self.pinned_files()
        files['secret.txt'] = b'fixture private text'
        self.release_commit(files)
        with self.assertRaisesRegex(ValueError, 'unexpected files'):
            recovery.restore_good(self.root, self.base / 'recovery')

    def test_restore_never_reuses_existing_directory(self):
        recovery.pin_good(self.root, self.site)
        target = self.base / 'recovery'
        target.mkdir()
        (target / 'stale.txt').write_text('keep fixture')
        with self.assertRaises(FileExistsError):
            recovery.restore_good(self.root, target)
        self.assertEqual((target / 'stale.txt').read_text(), 'keep fixture')

    def test_absent_release_preserves_source_records(self):
        original = (self.root / 'data/records.json').read_bytes()
        result = recovery.restore_good(self.root, self.base / 'recovery')
        self.assertFalse(result['available'])
        self.assertEqual(original, (self.root / 'data/records.json').read_bytes())

    def test_persist_only_whitelisted_json_even_with_staged_private_file(self):
        self.put('README.md', 'unrelated edit\n')
        self.put('private.txt', 'fixture private data')
        recovery.git(self.root, 'add', 'private.txt')
        recovery.write(self.root / 'data/records.json', [{'id': 'retained'}, {'id': 'new'}])
        recovery.write(self.root / 'reports/runs/run-1.json', {'outcome': 'partial'})
        recovery.write(self.root / 'reports/runs/nested/private.json', {'private': True})
        commit = recovery.persist(self.root, 'main')
        names = recovery.git(self.root, 'ls-tree', '-r', '--name-only', commit).decode().splitlines()
        self.assertIn('reports/runs/run-1.json', names)
        self.assertNotIn('private.txt', names)
        self.assertNotIn('reports/runs/nested/private.json', names)
        self.assertEqual(recovery.git(self.root, 'show', commit + ':README.md'), b'base\n')
        self.assertEqual(len(json.loads(recovery.git(self.root, 'show', commit + ':data/records.json'))), 2)

    def test_state_paths_rejects_symlink(self):
        outside = self.base / 'outside.json'
        outside.write_text('{"private":true}')
        (self.root / 'data/status.json').symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            recovery.persist(self.root, 'main')

    def test_failed_run_keeps_records_and_source_watermark(self):
        before = (self.root / 'data/records.json').read_bytes()
        recovery.write(self.root / 'data/status.json', {'last_success': 'earlier', 'sources': {'source': {'watermark': 'earlier'}}})
        recovery.start_runtime(self.root)
        result = recovery.finish_runtime(self.root, {'update': {'outcome': 'failure', 'conclusion': 'failure'}})
        self.assertEqual(result['status'], 'failed')
        self.assertEqual((self.root / 'data/records.json').read_bytes(), before)
        self.assertEqual(recovery.read(self.root / 'data/update-state.json')['watermark'], 'previous')
        status = recovery.read(self.root / 'data/status.json')
        self.assertEqual(status['last_success'], 'earlier')
        self.assertEqual(status['sources']['source']['watermark'], 'earlier')

    def test_partial_update_must_not_be_reported_as_success(self):
        recovery.start_runtime(self.root)
        state = recovery.read(self.root / 'data/status.json')
        state['last_outcome'] = 'partial'  # The field currently written by update.py.
        recovery.write(self.root / 'data/status.json', state)
        steps = {name: {'outcome': 'success', 'conclusion': 'success'}
                 for name in ('started', 'start_saved', 'dependencies', 'recovery', 'update', 'publication_guard', 'tests',
                              'pages_config', 'upload', 'deployment', 'verification', 'pin')}
        result = recovery.finish_runtime(self.root, steps)
        self.assertEqual(result['status'], 'partial')

    def test_skipped_required_update_must_not_report_success(self):
        recovery.start_runtime(self.root)
        # GitHub's steps context omits failed steps without an explicit id.
        steps = {'started': {'outcome': 'success', 'conclusion': 'success'},
                 **{name: {'outcome': 'skipped', 'conclusion': 'skipped'}
                    for name in ('recovery', 'update', 'publication_guard', 'tests', 'deployment', 'verification', 'pin')}}
        result = recovery.finish_runtime(self.root, steps)
        self.assertEqual(result['status'], 'failed')

    def test_deploy_check_hash_mismatch_preserves_last_receipt(self):
        class Response:
            status_code = 200
            content = b'wrong bytes'
        prior = (self.root / 'data/publication-status.json').read_bytes()
        with patch.object(deploy_check, 'ROOT', self.root), \
             patch.object(deploy_check, 'fetch', return_value=(Response(), {'status': 200})), \
             patch.object(deploy_check.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'deployed bytes differ'):
                deploy_check.verify('https://owner.github.io/library/', self.site)
        self.assertEqual((self.root / 'data/publication-status.json').read_bytes(), prior)

    def test_deploy_check_success_receipt_compatible_with_pin(self):
        class Response:
            status_code = 200
            def __init__(self, body):
                self.content = body
        def fetch(url, *args, **kwargs):
            filename = url.rsplit('/', 1)[-1]
            return Response(self.files[filename]), {'status': 200, 'final_url': url}
        with patch.object(deploy_check, 'ROOT', self.root), patch.object(deploy_check, 'fetch', side_effect=fetch):
            deploy_check.verify('https://owner.github.io/library/', self.site)
        receipt = recovery.read(self.root / 'data/publication-status.json')
        self.assertEqual(set(receipt['file_hashes']), set(recovery.SITE_FILES))
        self.assertFalse(receipt['rollback'])
        recovery.pin_good(self.root, self.site)


if __name__ == '__main__':
    unittest.main()
