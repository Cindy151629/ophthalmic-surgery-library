import unittest,sys,socket,json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from common import safe_url,fetch
from page_parser import parse_page_content
from import_seeds import identities,classify
from update import paginate,validate_transition,candidate_article
from build import public_record

class Response:
 def __init__(self,status=200,data=None):self.status_code=status;self.data=data
 def json(self):return self.data
def log():return {'requested_url':'https://example.org/test','checked_at':'2026-09-16T00:00:00+00:00'}
class PipelineTests(unittest.TestCase):
 def test_paginate_all_results(self):
  responses=iter([Response(data={'hitCount':3,'resultList':{'result':[{'id':'1'},{'id':'2'}]},'nextCursorMark':'B'}),Response(data={'hitCount':3,'resultList':{'result':[{'id':'3'}]}})])
  rows,pages=paginate('test',fetcher=lambda *a:(next(responses),log()),page_size=2);self.assertEqual(len(rows),3);self.assertEqual(len(pages),2)
 def test_empty_midstream_rejected(self):
  with self.assertRaises(ValueError):paginate('q',fetcher=lambda *a:(Response(data={'hitCount':9,'resultList':{'result':[]}}),log()))
 def test_empty_valid_query_not_database_clear(self):
  self.assertEqual(paginate('q',fetcher=lambda *a:(Response(data={'hitCount':0,'resultList':{'result':[]}}),log()))[0],[])
  with self.assertRaises(ValueError):validate_transition([{'id':'old','note':None}],[])
 def test_source_403_429_and_timeout_raise(self):
  for response in [Response(403),Response(429),None]:
   with self.subTest(response=response),self.assertRaises(RuntimeError):paginate('q',fetcher=lambda *a:(response,log()))
 def test_schema_failure(self):
  with self.assertRaises(ValueError):paginate('q',fetcher=lambda *a:(Response(data={}),log()))
 def test_truncated_pagination_does_not_succeed(self):
  with self.assertRaises(ValueError):paginate('q',fetcher=lambda *a:(Response(data={'hitCount':2,'resultList':{'result':[{}]},'nextCursorMark':'B'}),log()),max_pages=1)
 def test_note_overwrite_rejected(self):
  with self.assertRaises(ValueError):validate_transition([{'id':'old','note':{'results':['manual']}}],[{'id':'old','note':None}])
 def test_private_and_protocol_urls_rejected(self):
  for url in ['file:///etc/passwd','javascript:alert(1)','https://u:p@example.org','http://127.0.0.1','http://[::1]']:
   with self.subTest(url=url),self.assertRaises(ValueError):safe_url(url)
 def test_dns_private_redirect_target_rejected(self):
  with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('10.0.0.4',80))]),self.assertRaises(ValueError):safe_url('https://external-looking.example/test')
 def test_soft404_and_challenge_not_title_verified(self):
  for html in ['<title>Not Found</title><h1>404</h1>','<title>Just a moment</title><h1>Wanted paper</h1>']:
   c,_=parse_page_content(html.encode(),'Wanted paper',{'status':200,'content_type':'text/html'});self.assertFalse(c['title_present'])
 def test_sidebar_title_does_not_confirm_wrong_fulltext(self):
  html=b'<head><meta name="citation_title" content="Wrong paper"></head><main><h1>Wrong paper</h1></main><aside><h2>Wanted paper</h2></aside>'
  c,_=parse_page_content(html,'Wanted paper',{'status':200,'content_type':'text/html'});self.assertFalse(c['title_present'])
 def test_xml_wrong_main_title_rejected(self):
  xml=b'<article><front><article-meta><title-group><article-title>Wrong</article-title></title-group></article-meta></front><body><p>Wanted paper</p></body></article>'
  c,_=parse_page_content(xml,'Wanted paper',{'status':200,'content_type':'application/xml'});self.assertFalse(c['title_present'])
 def test_iframe_is_not_video_identity_or_playback(self):
  html=b'<title>Login</title><h1>Sign in</h1><iframe src="https://player.vimeo.com/video/738969098"></iframe>'
  c,_=parse_page_content(html,'Corneal wounds Video 1',{'status':200,'content_type':'text/html'});self.assertFalse(c['title_present']);self.assertNotIn('playback',c)
 def test_correction_link_not_second_primary_pmid(self):
  r={'kind':'literature','links':[{'url':'https://pubmed.ncbi.nlm.nih.gov/38504932/'},{'url':'https://pubmed.ncbi.nlm.nih.gov/38544501/'}]};self.assertEqual(identities(r),['pmid:38504932'])
 def test_alias_different_identity_not_same_key(self):
  a={'kind':'video','links':[{'url':'https://a.example/first'}]};b={'kind':'video','links':[{'url':'https://a.example/second'}]};self.assertNotEqual(identities(a),identities(b))
 def test_no_false_rop_in_blepharoplasty(self):
  tax=json.loads((Path(__file__).resolve().parents[1]/'config/taxonomy.json').read_text());r={'aliases':[{'id':'OCP-A010'}],'title':'Blepharoplasty: An Overview','seed_description':''};self.assertNotIn('rop',classify(r,tax)['procedures'])
 def test_nonocular_new_articles_are_staged(self):
  tax=json.loads((Path(__file__).resolve().parents[1]/'config/taxonomy.json').read_text())
  for title in ['AI-powered industrial quality assurance system for fancy yarn using computer vision and 3D visualization.','Esketamine-led opioid-free anaesthesia reduces postoperative pulmonary complications in bariatric surgery patients: a prospective randomized controlled trial.','A study of virtual reality for prostate biopsy: a randomized trial.']:
   m={'title':title,'id':'1','source':'MED'};p={'title':title,'ids':{}};r,why=candidate_article(m,p,'GEN',tax);self.assertIsNone(r);self.assertIn('眼科',why)
 def test_private_fields_are_not_published(self):
  r={'id':'x','kind':'literature','authors':[],'private_notes':'secret','cache_path':'/Users/private/file','note':None,'page_checks':[],'urls':[]};self.assertNotIn('private_notes',public_record(r));self.assertNotIn('cache_path',public_record(r))
 def test_private_paths_in_allowed_field_fail(self):
  r={'id':'x','authors':[],'note':{'sources':[{'url':'/Users/private/file'}]},'page_checks':[],'urls':[]}
  with self.assertRaises(ValueError):public_record(r)
if __name__=='__main__':unittest.main()
