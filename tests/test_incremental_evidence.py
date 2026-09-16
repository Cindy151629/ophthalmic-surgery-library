"""Regression cases from the first real cloud run: book records and conditional links."""
import unittest,sys,tempfile,json,os
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import update,verify,cloud_recovery
class IncrementalEvidence(unittest.TestCase):
 def test_nihr_book_record_is_a_primary_pubmed_record(self):
  xml=b'<PubmedArticleSet><PubmedBookArticle><BookDocument><PMID>34644043</PMID><Book><BookTitle>KERALINK RCT</BookTitle></Book><ArticleIdList><ArticleId IdType="doi">10.3310/eme08150</ArticleId></ArticleIdList></BookDocument></PubmedBookArticle></PubmedArticleSet>'
  with patch.object(update,'fetch',return_value=(SimpleNamespace(status_code=200,content=xml),{'checked_at':'2026-09-17'})):
   records,logs=update.pubmed_records([{'id':'34644043','source':'MED'}])
  self.assertEqual(records['34644043']['ids']['doi'],'10.3310/eme08150')
  self.assertEqual(records['34644043']['title'],'KERALINK RCT')
 def test_conditional_304_preserves_previous_identity_and_hash(self):
  previous={'requested_url':'https://example.org/video','sha256':'prior-body-hash','etag':'"abc"','title_present':True,'page_title':'Example'}
  with patch.object(verify,'fetch',return_value=(SimpleNamespace(status_code=304),{'status':304,'sha256':'empty-body','checked_at':'new'})) as fetch:
   _,_,result=verify.one(('video-id',previous['requested_url'],'Example',previous))
  self.assertEqual(result['sha256'],'prior-body-hash');self.assertTrue(result['title_present']);self.assertEqual(result['status'],304)
  self.assertEqual(fetch.call_args.kwargs['conditional'],{'If-None-Match':'"abc"'})
 def test_incomplete_304_cannot_create_identity_proof(self):
  with patch.object(verify,'fetch',return_value=(SimpleNamespace(status_code=304),{'status':304,'sha256':'empty-body'})):
   _,_,result=verify.one(('video-id','https://example.org/video','Example'))
  self.assertFalse(result.get('title_present'));self.assertIn('待复核',result['page_state'])
 def test_failed_publication_does_not_update_complete_success(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);cloud_recovery.write(root/'data/status.json',{'last_success':'previous-complete','last_discovery_success':'new-discovery','last_outcome':'success'})
   cloud_recovery.start_runtime(root)
   steps={k:{'outcome':'success','conclusion':'success'} for k in ('dependencies','update','publication_guard','tests','pages_config','upload','deployment','verification','pin')}
   steps['deployment']={'outcome':'failure','conclusion':'failure'}
   cloud_recovery.finish_runtime(root,steps)
   self.assertEqual(cloud_recovery.read(root/'data/status.json')['last_success'],'previous-complete')
 def test_pseudophakic_is_not_phakic_icl(self):
  from import_seeds import classify
  tax=json.loads((Path(__file__).resolve().parents[1]/'config/taxonomy.json').read_text())
  r={'aliases':[{'id':'CAT-A28'}],'title':'Pseudophakic cystoid macular edema: update 2016'}
  self.assertNotIn('icl',classify(r,tax)['procedures'])
 def test_proptosis_is_not_blepharoptosis(self):
  from import_seeds import classify
  tax=json.loads((Path(__file__).resolve().parents[1]/'config/taxonomy.json').read_text())
  r={'aliases':[{'id':'OCP-A01'}],'title':'Orbital decompression for proptosis'}
  self.assertNotIn('ptosis',classify(r,tax)['procedures'])
 def test_adult_aphakia_is_not_infant_cataract(self):
  from import_seeds import classify
  tax=json.loads((Path(__file__).resolve().parents[1]/'config/taxonomy.json').read_text())
  r={'aliases':[{'id':'CAT-A01'}],'title':'Intraocular lens fixation in adult aphakia'}
  self.assertNotIn('pediatric-cataract',classify(r,tax)['procedures'])
 def test_publication_only_does_not_advance_discovery_attempt(self):
  with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'OPHTH_REFRESH_SOURCES':'false'}):
   root=Path(tmp);cloud_recovery.write(root/'data/status.json',{'last_attempt':'prior-real-discovery'})
   runtime=cloud_recovery.start_runtime(root)
   self.assertEqual(runtime['run_scope'],'publish-reviewed')
   self.assertEqual(cloud_recovery.read(root/'data/status.json')['last_attempt'],'prior-real-discovery')
 def test_scleral_fixated_is_found_under_iol_fixation(self):
  from import_seeds import classify
  tax=json.loads((Path(__file__).resolve().parents[1]/'config/taxonomy.json').read_text())
  r={'aliases':[{'id':'CAT-A21'}],'title':'Scleral-Fixated Intraocular Lenses: Past and Present'}
  self.assertIn('iol-fixation',classify(r,tax)['procedures'])
if __name__=='__main__':unittest.main()
