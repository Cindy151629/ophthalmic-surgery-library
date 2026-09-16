"""Audit real note coverage without equating an index or downloaded body with reading."""
from collections import Counter
from urllib.parse import urlsplit
import hashlib,json

def completion(record):
 n=record.get('note')
 if not n or n.get('scope') in ('metadata','restricted'):return 'pending'
 return 'substantive' if n.get('completion')=='substantive' else 'limited'

def audit(records):
 articles=[r for r in records if r.get('kind')=='literature'];errors=[];gaps=[];fingerprints={}
 for r in articles:
  n=r.get('note');status=completion(r)
  if status!='substantive':
   gaps.append({'id':r['id'],'title':r['title'],'pmid':r.get('pmid'),'status':status,'scope':n.get('scope') if n else None,'reason':n.get('limitations',[]) if n else ['尚未形成逐篇阅读笔记'],'sources':n.get('sources',[]) if n else []})
  if not n:continue
  if n.get('completion')=='substantive' and n.get('scope') in ('metadata','restricted'):errors.append(r['id']+': title-only/restricted note cannot be complete')
  if status=='substantive':
   for k in ('question','design','methods','results','interpretation','limitations','sources'):
    if not n.get(k):errors.append(r['id']+': missing note section '+k)
   if n.get('scope') not in ('abstract','partial','fulltext','official_page'):errors.append(r['id']+': unsupported scope')
   fingerprint=hashlib.sha256(json.dumps([n.get(k) for k in ('question','methods','results')],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
   if fingerprint in fingerprints:errors.append(r['id']+': duplicate substantive body with '+fingerprints[fingerprint])
   fingerprints[fingerprint]=r['id']
  for source in n.get('sources',[]):
   u=urlsplit(source.get('url',''))
   if u.scheme not in ('https','http') or not u.netloc or u.username or u.password:errors.append(r['id']+': invalid source URL')
  if '/Users/' in json.dumps(n,ensure_ascii=False):errors.append(r['id']+': private path')
 sections={s:dict(Counter(completion(r) for r in articles if r.get('section')==s)) for s in sorted({r.get('section') for r in articles})}
 return {'articles':len(articles),'with_note':sum(bool(r.get('note')) for r in articles),'completion':dict(Counter(completion(r) for r in articles)),'reading_scopes':dict(Counter((r.get('note') or {}).get('scope','pending') for r in articles)),'sections':sections,'definition':'substantive表示已读来源范围内有逐篇实质笔记；摘要、部分正文与全文分别标注。limited为待补证据或需复核，pending为未取得实质内容。','errors':errors,'gaps':gaps}

if __name__=='__main__':
 from common import ROOT,read,write
 report=audit(read(ROOT/'data/records.json',[]));write(ROOT/'reports/note-coverage.json',report);print(json.dumps({k:v for k,v in report.items() if k!='gaps'},ensure_ascii=False));raise SystemExit(bool(report['errors']))
