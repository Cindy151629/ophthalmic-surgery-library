"""Minimal structures derived from cached Moran/Cybersight/DJO source pages."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from video_parser import parse_video_candidate

TITLE = 'Surgery: Phacoemulsification'
DESCRIPTION = 'This video demonstrates phacoemulsification in a patient with a dense cataract.'
SOURCE = {'id': 'Cybersight', 'host': 'cybersight.org', 'title_selector': 'h1'}
URL = 'https://cybersight.org/library/surgery-phacoemulsification/'


def document(media, *, extra='', description=DESCRIPTION):
    # Real Cybersight: hero title outside main, one type-library article,
    # comments are separate articles, and body has the no-sidebar layout class.
    return f'<html><head><title>{TITLE} | Cybersight</title></head><body class="single-library no-sidebar"><div class="page-hero"><h1 class="page-hero-title">{TITLE}</h1></div><main id="main"><article id="post-20897" class="type-library"><p>{description}</p>{media}</article><div class="comments-area"><article class="comment-body">Comment</article></div>{extra}</main></body></html>'.encode()


class VideoParserTests(unittest.TestCase):
    def parse(self, html, title=TITLE, source=None, **overrides):
        log = {'status': 200, 'content_type': 'text/html', 'requested_url': URL,
               'final_url': URL, 'checked_at': '2026-09-16T00:00:00+00:00'}
        log.update(overrides)
        return parse_video_candidate(html, title, source or SOURCE, log)

    def test_cybersight_lazy_iframe_with_external_hero(self):
        c, d, reason = self.parse(document('<iframe data-src="https://fast.wistia.net/embed/iframe/78x24kej8r"></iframe>'))
        self.assertIsNone(reason)
        self.assertEqual(d, DESCRIPTION)
        self.assertEqual(c['video_entrypoints'][0]['media_id'], '78x24kej8r')
        self.assertTrue(c['title_present'])
        self.assertNotIn('playback', c)
        self.assertNotIn('embedding', c)

    def test_wistia_async_container(self):
        c, d, reason = self.parse(document('<script src="https://fast.wistia.com/embed/medias/q51nk4y4py.jsonp"></script><div class="wistia_embed wistia_async_q51nk4y4py seo=false videoFoam=true"></div>'))
        self.assertIsNone(reason)
        self.assertEqual(c['video_entrypoints'][0]['media_id'], 'q51nk4y4py')

    def test_modern_wistia_web_component(self):
        c, d, reason = self.parse(document('<wistia-player media-id="q51nk4y4py"></wistia-player>'))
        self.assertIsNone(reason)

    def test_preloaded_media_without_container_is_not_video(self):
        c, d, reason = self.parse(document('<script src="https://fast.wistia.com/embed/medias/q51nk4y4py.jsonp"></script>'))
        self.assertIsNotNone(reason)
        self.assertEqual(c['video_entrypoints'], [])

    def test_sidebar_and_related_players_do_not_qualify(self):
        for tag in ['aside', 'div class="related-videos"', 'div class="comments-area"']:
            end = tag.split()[0]
            with self.subTest(tag=tag):
                html = document(f'<{tag}><iframe src="https://player.vimeo.com/video/738969098"></iframe></{end}>')
                self.assertIsNotNone(self.parse(html)[2])

    def test_unknown_host_and_nonmedia_paths_rejected(self):
        for url in ['https://ads.example/embed/78x24kej8r', 'https://www.youtube.com/privacy',
                    'https://www.youtube.com.evil.example/embed/abcdefghi',
                    'https://user:pass@www.youtube.com/embed/abcdefghi']:
            with self.subTest(url=url):
                self.assertIsNotNone(self.parse(document(f'<iframe src="{url}"></iframe>'))[2])

    def test_empty_html5_and_untrusted_html5_sources_rejected(self):
        for html in ['<video></video>', '<video src="https://ads.example/film.mp4"></video>']:
            with self.subTest(html=html):
                self.assertIsNotNone(self.parse(document(html))[2])

    def test_official_html5_source_is_dom_evidence_only(self):
        c, d, reason = self.parse(document('<video><source src="https://cybersight.org/official.mp4"></video>'))
        self.assertIsNone(reason)
        self.assertEqual(c['video_entrypoints'][0]['kind'], 'html5')
        self.assertNotIn('playback', c)

    def test_challenge_body_with_retained_title_rejected(self):
        html = document('<iframe src="https://fast.wistia.net/embed/iframe/78x24kej8r"></iframe>',
                        description='Verify you are human before accessing this surgical education resource.')
        c, d, reason = self.parse(html)
        self.assertIsNotNone(reason)
        self.assertFalse(c['title_present'])

    def test_login_sidebar_is_not_target_video(self):
        html = b'<title>Login | Digital Journal of Ophthalmology</title><main><form>Username Password</form></main><aside><h1>Surgery: Phacoemulsification</h1><iframe src="https://player.vimeo.com/video/738969098"></iframe></aside>'
        self.assertIsNotNone(self.parse(html)[2])

    def test_transcript_and_comments_do_not_supply_description(self):
        html = document('<iframe src="https://fast.wistia.net/embed/iframe/78x24kej8r"></iframe><div class="video_transcript"><p>This is a long transcript paragraph, not an official overview or resource description.</p></div>', description='')
        self.assertIsNotNone(self.parse(html)[2])

    def test_moran_h2_overrides_site_h1_after_main_scope_verification(self):
        source = {'id': 'Moran', 'host': 'morancore.utah.edu', 'title_selector': 'h2'}
        title = 'Phacoemulsification: Manual Capsulorrhexis'
        url = 'https://morancore.utah.edu/section-11-lens-and-cataract/phacoemulsification-manual-capsulorrhexis/'
        html = f'<title>Moran CORE | {title}</title><header><h1>Moran CORE</h1></header><main><div id="content"><h2>{title}</h2><iframe src="https://www.youtube.com/embed/urllWFnsJkQ"></iframe><p><strong>Brief Description:</strong> This video covers manual capsulorrhexis during cataract surgery.</p><p><strong>Format:</strong> video</p></div><aside><h2>Related</h2></aside></main>'.encode()
        c, d, reason = self.parse(html, title, source, requested_url=url, final_url=url)
        self.assertIsNone(reason)
        self.assertEqual(c['official_title'], title)
        self.assertTrue(c['title_present'])
        self.assertIn('main #content h2', c['title_match_source'])
        self.assertNotIn('Format:', d)

    def test_wrong_resource_title_and_wrong_final_host_rejected(self):
        html = document('<iframe src="https://fast.wistia.net/embed/iframe/78x24kej8r"></iframe>')
        self.assertIsNotNone(self.parse(html, title='Surgery: Phacoemulsification complications')[2])
        self.assertIsNotNone(self.parse(html, final_url='https://other.example/resource')[2])


if __name__ == '__main__':
    unittest.main()
