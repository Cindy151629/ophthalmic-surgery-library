"""Independent regressions from the source/status audit.

Uses temporary directories and mock network responses; never mutates the library.
"""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'scripts'))
import integrate_evidence
import update
from import_seeds import classify


class ReviewRegressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tax = json.loads((PROJECT / 'config/taxonomy.json').read_text())
        cls.baseline = json.loads((PROJECT / 'data/records.json').read_text())

    def test_eyelid_retraction_is_not_a_retraction_notice(self):
        title = 'A technique for lower eyelid retraction repair after blepharoplasty'
        m = {'title': title, 'source': 'MED', 'id': '99999001',
             'pubYear': '2025', 'pubTypeList': {'pubType': ['Journal Article']}}
        p = {'title': title, 'ids': {}, 'corrections': [],
             'source_url': 'https://pubmed.ncbi.nlm.nih.gov/99999001/',
             'checked_at': '2026-09-16T00:00:00+00:00'}
        record, reason = update.candidate_article(m, p, 'OCP', self.tax)
        self.assertIsNotNone(record, reason)

    def test_indexed_body_excerpt_is_not_a_downloaded_fulltext(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, work = Path(tmp) / 'app', Path(tmp) / 'work'
            (root / 'data').mkdir(parents=True)
            work.mkdir()
            r = copy.deepcopy(next(r for r in self.baseline if r['kind'] == 'literature'))
            r.update(id='test-paper', source_keys=['expanded:TEST-A001'], urls=[], note=None,
                     fulltext={'status': 'unknown', 'url': None, 'read_scope': None})
            (root / 'data/records.json').write_text(json.dumps([r]))
            entry = {'source_keys': r['source_keys'],
                     'identity': {'status': 'verified', 'conflicts': []},
                     'note': {'scope': 'fulltext', 'sources': [
                         {'url': 'https://pmc.ncbi.nlm.nih.gov/articles/PMC6486383/',
                          'locator': 'selected indexed sections'}]},
                     'verification': {'fulltext_fetched': False, 'web_index_body_read': True,
                                      'fulltext_read': 'selected_sections'}}
            (work / 'notes_test.json').write_text(json.dumps([entry]))
            with patch.object(integrate_evidence, 'ROOT', root), patch.object(integrate_evidence, 'WORK', work), contextlib.redirect_stdout(io.StringIO()):
                integrate_evidence.run()
            result = json.loads((root / 'data/records.json').read_text())[0]
            self.assertNotEqual(result['fulltext']['status'], 'retrieved')

    def test_pubmed_outage_does_not_advance_success_watermark(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'data').mkdir()
            (root / 'config').mkdir()
            before = '2026-09-01T00:00:00+00:00'
            cfg = {'article_queries': {'CAT': 'cataract surgery'}, 'video_sources': [],
                   'overlap_days': 30, 'page_size': 500, 'max_pages_per_source': 100,
                   'historical_rotation_days': 365, 'historical_initial_end': '2025-01-01',
                   'timezone': 'Asia/Shanghai'}
            data = {'config/update.json': cfg, 'config/taxonomy.json': self.tax,
                    'data/records.json': [self.baseline[0]],
                    'data/status.json': {'last_success': before},
                    'data/update-state.json': {'rotation': 0, 'sources': {
                        'EuropePMC-CAT': {'last_success': before}}}}
            for p, value in data.items():
                (root / p).write_text(json.dumps(value))
            m = {'source': 'MED', 'id': '99999002', 'title': 'Phacoemulsification: a randomized trial'}
            failure = {'requested_url': 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi',
                       'checked_at': '2026-09-16T00:00:00+00:00', 'status': 503}
            with patch.object(update, 'ROOT', root), patch.object(update, 'paginate', side_effect=[([m], []), ([], [])]), patch.object(update, 'fetch', return_value=(None, failure)), patch.object(update, 'build'), contextlib.redirect_stdout(io.StringIO()):
                update.run(skip_links=True)
            state = json.loads((root / 'data/update-state.json').read_text())
            status = json.loads((root / 'data/status.json').read_text())
            self.assertEqual(state['sources']['EuropePMC-CAT']['last_success'], before)
            self.assertNotEqual(status['last_outcome'], 'success')

    def test_jones_tube_is_not_a_glaucoma_drainage_device(self):
        r = {'aliases': [{'id': 'OCP-V022'}], 'title': 'Jones tube placement #1',
             'seed_description': '泪道重建，结膜泪囊鼻腔吻合后的 Jones 管置入'}
        self.assertNotIn('tube', classify(r, self.tax)['procedures'])

    def test_buckle_fixation_is_not_intraocular_lens_fixation(self):
        r = {'aliases': [{'id': 'RET-V11'}],
             'title': 'Simulated Surgery: Retinal Buckling: Placing the Buckle',
             'seed_description': 'Scleral buckle placement and fixation training'}
        self.assertNotIn('iol-fixation', classify(r, self.tax)['procedures'])

    def test_chinese_page_resources_are_in_chinese_filter(self):
        chinese = [r for r in self.baseline if any(s.startswith('expanded:CN-V') for s in r.get('source_keys', []))]
        self.assertEqual(len(chinese), 12)
        self.assertTrue(all(r['language'] == 'zh' for r in chinese),
                        [(r['source_keys'], r['language']) for r in chinese if r['language'] != 'zh'])

    def video_candidate(self, html):
        url = 'https://cybersight.org/library/surgery-phacoemulsification/'
        title = 'Surgery: Phacoemulsification'
        source = {'id': 'Cybersight', 'host': 'cybersight.org', 'title_selector': 'h1'}
        log = {'status': 200, 'content_type': 'text/html', 'requested_url': url,
               'final_url': url, 'checked_at': '2026-09-16T00:00:00+00:00'}
        with patch.object(update, 'fetch', return_value=(SimpleNamespace(status_code=200, content=html.encode()), log)):
            return update.candidate_video(url, title, source, self.tax)

    def test_sidebar_player_cannot_make_article_a_video(self):
        html = '<title>Surgery: Phacoemulsification</title><main><h1>Surgery: Phacoemulsification</h1><p>This is a text-only article about cataract surgery and phacoemulsification.</p></main><aside><iframe src="https://www.youtube.com/embed/sidebar1234"></iframe></aside>'
        record, reason = self.video_candidate(html)
        self.assertIsNone(record, 'A sidebar player does not belong to this article.')

    def test_empty_video_element_is_not_a_resource(self):
        html = '<title>Surgery: Phacoemulsification</title><main><h1>Surgery: Phacoemulsification</h1><p>This page explains cataract surgery and phacoemulsification as educational text.</p><video></video></main>'
        record, reason = self.video_candidate(html)
        self.assertIsNone(record, 'An empty video element supplies no identifiable media.')

    def test_body_challenge_is_not_an_accepted_video(self):
        html = '<title>Surgery: Phacoemulsification</title><main><h1>Surgery: Phacoemulsification</h1><p>Verify you are human before accessing the requested cataract surgery teaching resource.</p><iframe src="https://fast.wistia.net/embed/iframe/abcdefghij"></iframe></main>'
        record, reason = self.video_candidate(html)
        self.assertIsNone(record, 'The page parser already detects this access challenge.')

    def test_official_lazy_player_can_confirm_identity_without_playback(self):
        html = '<title>Surgery: Phacoemulsification</title><main><h1>Surgery: Phacoemulsification</h1><p>This video demonstrates phacoemulsification for a patient with a dense cataract.</p><iframe data-src="https://fast.wistia.net/embed/iframe/abcdefghij" title="Phacoemulsification"></iframe></main>'
        record, reason = self.video_candidate(html)
        self.assertIsNotNone(record, reason)
        self.assertEqual(record['video']['playback'], 'unknown')
        self.assertEqual(record['video']['embedding'], 'unknown')


if __name__ == '__main__':
    unittest.main()
