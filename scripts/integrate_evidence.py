"""Integrate authored evidence notes by preserved source keys; never overwrite private notes."""
from common import *
from collections import Counter
from bs4 import BeautifulSoup
from page_parser import _title_matches

def run():
 records=read(ROOT/'data/records.json');checks=read(WORK/'page_checks.json',{});lookup={k:r for r in records for k in r.get('source_keys',[])};conflicts=[];scores={};note_merges=[]
 for p in sorted(WORK.glob('notes_*.json')):
  notes=read(p,[])
  if not isinstance(notes,list):continue
  for entry in notes:
   ids={lookup[k]['id'] for k in entry.get('source_keys',[]) if k in lookup}
   for rid in ids:
    r=next(r for r in records if r['id']==rid);ident=entry.get('identity',{});n=entry.get('note')
    if not n:continue
    score=({'fulltext':4,'partial':3,'official_page':3,'abstract':2,'metadata':1}.get(n.get('scope'),0),len(json.dumps(n,ensure_ascii=False)),p.name)
    if rid in scores:
     note_merges.append({'id':rid,'candidate':p.name,'reason':'同一资源的多份笔记，按阅读范围、信息量及确定性文件名选择规范版本；原笔记仍保留在来源审计中'})
     if score<scores[rid]:continue
    scores[rid]=score
    r['note']=n;r['identity']=ident
    for k in ['doi','pmid','pmcid','authors','year']:
     if ident.get(k):r[k]=ident[k]
    if ident.get('journal'):r['source']=ident['journal']
    if isinstance(r['year'],str) and r['year'].isdigit():r['year']=int(r['year'])
    if isinstance(r.get('authors'),str):r['authors']=[r['authors']]
    if ident.get('status')=='verified':r['publication_status']='verified-index'
    v=entry.get('verification',{});r['verification_details']=v
    fragment_only=(v.get('web_index_body_read') is True and v.get('fulltext_fetched') is False) or ('索引' in ' '.join(s.get('locator','') for s in n.get('sources',[])) and n.get('scope')=='fulltext' and not v.get('fulltext_fetched'))
    if fragment_only:
     n['scope']='partial';n['scope_description']='核读官方页面在检索索引中可见的正文段落；本轮未成功取得完整正文文件。'
     r['fulltext']={'status':'matched','url':next((s['url'] for s in n.get('sources',[]) if 'pmc.' in s.get('url','')),None),'read_scope':'indexed_body_passages','retrieved':False}
    elif v.get('fulltext_retrieved') is True or v.get('fulltext_fetched') is True or v.get('fulltext_correspondence')=='checked_for_cited_version' and n.get('scope') in ['fulltext','partial','official_page']:
     candidates=[s['url'] for s in n.get('sources',[]) if 'pubmed.ncbi' not in s.get('url','')]
     url=candidates[0] if candidates else ('https://pmc.ncbi.nlm.nih.gov/articles/'+r['pmcid']+'/' if r.get('pmcid') else None)
     if url:r['fulltext']={'status':'retrieved','url':url,'read_scope':n.get('scope'),'retrieved':True}
    if ident.get('conflicts'):conflicts.append({'id':rid,'conflicts':ident['conflicts']})
    if r.get('pmcid') and r.get('fulltext',{}).get('status')=='unknown':
     r['fulltext']={'status':'matched','url':'https://pmc.ncbi.nlm.nih.gov/articles/'+r['pmcid']+'/','retrieved':False,'read_scope':n.get('scope'),'basis':'PMID/PMCID身份对应；入口已匹配不表示本轮取得全部正文。'}
    for c in v.get('source_fetch_log',[])+v.get('evidence_sources',[]):
     if isinstance(c,dict) and (c.get('requested_url') or c.get('url')):
      check={**c,'requested_url':c.get('requested_url') or c.get('url')}
      if check not in r.setdefault('page_checks',[]):r['page_checks'].append(check)
 for r in records:
  existing=r.get('page_checks',[]);r['page_checks']=[checks[digest(u['url'])] for u in r['urls'] if digest(u['url']) in checks]
  signatures={(c.get('requested_url'),c.get('checked_at')) for c in r['page_checks']}
  r['page_checks'] += [c for c in existing if (c.get('requested_url'),c.get('checked_at')) not in signatures]
  if r['kind']!='video':continue
  if any(a['id'].startswith('CN-') for a in r['aliases']):r['language']='zh'
  if not r['page_checks']:continue
  c=r['page_checks'][0];host=urllib.parse.urlsplit(c['requested_url']).hostname;raw=WORK/'page_cache'/(digest(c['requested_url'])+'.bin')
  if host=='morancore.utah.edu' and raw.exists() and c.get('status')==200:
   soup=BeautifulSoup(raw.read_bytes(),'html.parser');heads=soup.select('h2');expected=r['title'];actual=heads[0].get_text(' ',strip=True) if len(heads)==1 else ''
   if actual and _title_matches(expected,actual,'h1'):
    c.update(title_present=True,title_match_source='Moran CORE unique article h2 (site h1 excluded)',page_state='具体视频页题名已匹配',page_title=actual)
  directory=any(re.search('仅.*目录|仅.*索引|目录核实|索引核实',p) for h in r['seed_history'] for p in h['paragraphs'])
  if c.get('title_present') and not directory:
   r['identity']={'status':'verified','source_url':c['requested_url'],'checked_at':c['checked_at'],'scope':'具体页面题名；不是播放验证','conflicts':[]};r['publication_status']='verified-index'
  else:r['identity']={'status':'restricted' if c.get('status')!=200 else 'pending','source_url':c['requested_url'],'checked_at':c['checked_at'],'scope':'仅目录核实' if directory else c.get('page_state'),'conflicts':[]}
  # A fetched iframe, transcript, page update year or player URL proves no playback.
  r['video']['summary_basis']='种子文档中的内容概括；本轮页面核验范围见下方记录，尚未根据播放核对'
 for evidence in read(WORK/'video_manual_audit.json',[]):
  r=next((r for r in records if r['id']==evidence.get('id')),None)
  if not r:continue
  r['identity']={'status':evidence['status'],'source_url':evidence.get('source_url'),'checked_at':evidence.get('checked_at') or now(),'scope':evidence.get('evidence'),'conflicts':evidence.get('conflicts',[])}
  if evidence.get('summary_zh'):r['video']['summary']=evidence['summary_zh']
  r['video']['summary_basis']=evidence.get('summary_locator') or evidence.get('evidence')
  r['video']['official_title']=evidence.get('official_title')
  if evidence['status']=='verified':r['publication_status']='verified-index'
 for evidence in read(WORK/'playback_checks.json',[]):
  r=next((r for r in records if r['id']==evidence.get('id')),None)
  if r and r['kind']=='video':r['video'].update(evidence['video'])
 write(ROOT/'data/records.json',records);write(ROOT/'reports/note-conflicts.json',conflicts);write(ROOT/'reports/note-merge-audit.json',note_merges)
 write(ROOT/'reports/link-verification.json',{'at':now(),'checked_urls':len(checks),'status_counts':dict(Counter(str(c.get('status')) for c in checks.values())),'records':[{'id':r['id'],'identity':r['identity'],'links':r['page_checks'],'reading_scope':r.get('note',{}).get('scope') if r.get('note') else None,'playback':r['video']['playback'] if r['kind']=='video' else None} for r in records]})
 print('integrated notes',sum(bool(r.get('note')) for r in records),flush=True)
if __name__=='__main__':run()
