"""Guard every publication, including reviewed-only runs, against lost resources."""
from common import *
from build import public_record

def validate(previous,current):
 if not isinstance(current,list) or not current:raise ValueError('empty or invalid current library')
 ids=[r['id'] for r in current]
 if len(ids)!=len(set(ids)):raise ValueError('duplicate stable IDs')
 by={r['id']:r for r in current};missing={r['id'] for r in previous}-set(by)
 if missing:raise ValueError('publication would lose '+str(len(missing))+' previously published resources')
 for old in previous:
  if old.get('note') and not by[old['id']].get('note'):raise ValueError('publication would erase an authored note')
 for r in current:public_record(r)
 for field in ['doi','pmid','pmcid']:
  values=[str(r[field]).lower().rstrip('.') for r in current if r.get('kind')=='literature' and r.get(field)]
  if len(values)!=len(set(values)):raise ValueError('duplicate primary identifier '+field)
 return {'previous_resources':len(previous),'current_resources':len(current),'resources_preserved':True,'authored_notes_present':sum(bool(r.get('note')) for r in current),'checked_at':now()}
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--previous-dir',type=Path,default=ROOT/'previous-site');a=p.parse_args()
 result=validate(read(a.previous_dir/'records.json',[]),read(ROOT/'data/records.json',[]));write(ROOT/'reports/publication-safety.json',result);print(json.dumps(result))
