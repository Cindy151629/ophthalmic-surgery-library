import unittest,sys,pathlib
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'scripts'))
from audit_notes import audit,completion
class NoteCoverageTests(unittest.TestCase):
 def note(self,**change):
  n={'scope':'abstract','completion':'substantive','question':'What was compared?','design':'Randomized study','methods':'Defined sample and follow-up','results':['Actual outcome'],'interpretation':'Evidence interpretation','limitations':['Scope limitation'],'sources':[{'url':'https://pubmed.ncbi.nlm.nih.gov/123/'}]};n.update(change);return n
 def test_index_or_restricted_source_not_counted_as_detailed(self):
  for n in [None,self.note(scope='metadata',completion='pending'),self.note(scope='restricted',completion='limited')]:self.assertEqual(completion({'note':n}),'pending')
 def test_abstract_can_have_complete_detailed_note(self):self.assertEqual(completion({'note':self.note()}),'substantive')
 def test_partial_evidence_stays_in_gap_list(self):
  r=audit([{'id':'a','kind':'literature','section':'CAT','title':'Article','note':self.note(completion='limited')}]);self.assertEqual(len(r['gaps']),1);self.assertFalse(r['errors'])
 def test_false_completion_and_missing_content_rejected(self):
  r=audit([{'id':'a','kind':'literature','section':'CAT','title':'A','note':self.note(scope='metadata')},{'id':'b','kind':'literature','section':'CAT','title':'B','note':self.note(results=[])}]);self.assertEqual(len(r['errors']),2)
 def test_reused_substantive_body_is_flagged(self):
  r=audit([{'id':i,'kind':'literature','section':'CAT','title':i,'note':self.note()} for i in ['a','b']]);self.assertTrue(any('duplicate' in e for e in r['errors']))
 def test_public_sources_cannot_be_private_or_credentialed(self):
  for u in ['/Users/a/paper.pdf','https://secret:password@example.org/a']:
   r=audit([{'id':'a','kind':'literature','section':'CAT','title':'A','note':self.note(sources=[{'url':u}])}]);self.assertTrue(r['errors'])
if __name__=='__main__':unittest.main()
