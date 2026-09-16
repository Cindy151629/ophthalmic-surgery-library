import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from validate_publication import validate
class PublicationGuard(unittest.TestCase):
 def record(self,id,**extra):return {'id':id,'kind':'literature','authors':[],**extra}
 def test_reviewed_publication_cannot_drop_previously_published_rows(self):
  with self.assertRaisesRegex(ValueError,'lose'):validate([self.record('old'),self.record('new')],[self.record('old')])
 def test_missing_note_is_rejected(self):
  with self.assertRaisesRegex(ValueError,'erase'):validate([self.record('old',note={'question':'authored'})],[self.record('old')])
 def test_recovered_union_is_publishable(self):
  result=validate([self.record('old')],[self.record('old'),self.record('recovered')])
  self.assertEqual(result['current_resources'],2)
 def test_duplicate_doi_is_rejected(self):
  with self.assertRaisesRegex(ValueError,'identifier'):validate([],[self.record('a',doi='10.1/abc'),self.record('b',doi='10.1/ABC')])
if __name__=='__main__':unittest.main()
