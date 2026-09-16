"""Deterministic incremental discovery, verification, staging and atomic persistence.

No LLM, no video download, no private-note access. All source results carry a
pagination ledger. Watermarks only advance after complete source traversal.
"""
from common import *
from import_seeds import classify,identities
from page_parser import parse_page_content,_title_matches
from build import build,public_record
from bs4 import BeautifulSoup
from copy import deepcopy
from collections import Counter
import xml.etree.ElementTree as ET,fcntl,shutil,email.utils

def paginate(query,*,fetcher=fetch,page_size=500,max_pages=100):
 cursor='*';seen=set();rows=[];logs=[];expected=None
 for i in range(max_pages):
  if cursor in seen:raise ValueError('pagination cursor repeated')
  seen.add(cursor)
  resp,log=fetcher('https://www.ebi.ac.uk/europepmc/webservices/rest/search',{'query':query,'format':'json','resultType':'core','pageSize':page_size,'cursorMark':cursor})
  if resp is None or resp.status_code!=200:raise RuntimeError('source request failed: '+json.dumps(log))
  data=resp.json()
  if not isinstance(data.get('hitCount'),int) or not isinstance(data.get('resultList',{}).get('result'),list):raise ValueError('invalid source schema')
  expected=data['hitCount'];batch=data['resultList']['result'];rows.extend(batch);nxt=data.get('nextCursorMark');logs.append({'page':i+1,'cursor':cursor,'returned':len(batch),'hits':expected,'url':log['requested_url'],'at':log['checked_at']})
  if len(rows)>=expected:return rows,logs
  if not batch or not nxt or nxt==cursor:raise ValueError('pagination stopped before hitCount')
  cursor=nxt
 raise ValueError('page budget exceeded; incomplete source; watermark not advanced')

def pubmed_records(rows):
 ids=list(dict.fromkeys(x['id'] for x in rows if x.get('source')=='MED' and str(x.get('id','')).isdigit()));out={};logs=[]
 for i in range(0,len(ids),100):
  resp,log=fetch('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi',{'db':'pubmed','retmode':'xml','id':','.join(ids[i:i+100]),'tool':'OphthalmicSurgeryLibrary'})
  logs.append(log)
  if resp is None or resp.status_code!=200:continue
  try:
   root=ET.fromstring(resp.content)
   for a in root.findall('.//PubmedArticle'):
    pid=a.findtext('./MedlineCitation/PMID');art=a.find('./MedlineCitation/Article');title=''.join(art.find('ArticleTitle').itertext()) if art is not None and art.find('ArticleTitle') is not None else ''
    ids2={x.get('IdType'):''.join(x.itertext()) for x in a.findall('./PubmedData/ArticleIdList/ArticleId')}
    corrections=[{'type':x.get('RefType'),'pmid':x.findtext('PMID')} for x in a.findall('./MedlineCitation/CommentsCorrectionsList/CommentsCorrections')]
    out[pid]={'title':title,'ids':ids2,'corrections':corrections,'source_url':'https://pubmed.ncbi.nlm.nih.gov/'+pid+'/','checked_at':log['checked_at']}
  except ET.ParseError:log['parse_error']='invalid PubMed XML'
 return out,logs

def candidate_article(m,p,section,tax):
 if not p or not _title_matches(m.get('title',''),p.get('title',''),'citation_title'):return None,'PubMed primary title not matched'
 if m.get('doi') and doi(m['doi'])!=doi(p['ids'].get('doi')):return None,'DOI identity conflict'
 text=m.get('title','')+' '+BeautifulSoup(m.get('abstractText',''),'html.parser').get_text(' ')
 if not re.search(r'ophthalm|ocular|cataract|cornea|retin|macula|glaucoma|vitrect|trabec|keratoplast|phaco|eyelid|blepharo|entropion|ectropion|lacrimal|dacryo|strabism|intraocular|scleral|uveal|conjunctiv|lens.{0,20}implant|lens.{0,20}sublux|LASIK|lenticule|optic nerve|orbital|endophthalmitis|pterygium|\bDMEK\b|\bDALK\b|\bICL\b|\bPreser[Ff]lo\b|\bXEN\b',m.get('title',''),re.I):return None,'题名无特异眼科背景，不能自动收录'
 if not re.search(r'surg|vitrectom|trabec|keratoplast|phaco|resection|repair|implant|laser|cross.link|simulation|suture|biopsy|decompression|dilation|brachytherapy|手术|共识',text,re.I):return None,'surgical relevance requires review'
 types=m.get('pubTypeList',{}).get('pubType',[])
 if not re.search(r'random|trial|meta.analysis|systematic|guideline|consensus|comparative|follow.up|technique|technical',m.get('title','')+' '+' '.join(types),re.I):return None,'自动收录优先比较研究、指南、系统综述或明确技术文章；其余进入价值复核'
 if re.search(r'^\[?(?:retraction(?:\s+notice)?|withdrawn|withdrawal)\b',m.get('title',''),re.I) or any(x.get('type') in ['RetractionIn','RetractionOf'] for x in p['corrections']):return None,'retraction or notice requires review'
 key='doi:'+doi(m['doi']) if m.get('doi') else 'pmid:'+m['id'];pid=m['id'];urls=[{'label':'PubMed','url':p['source_url']}]
 if m.get('doi'):urls.append({'label':'DOI','url':'https://doi.org/'+m['doi']})
 r={'id':'eye-a-'+digest(key)[:12],'kind':'literature','title':p['title'],'aliases':[],'source_keys':[],'identity_keys':[key,'pmid:'+pid],'seed_history':[],
 'seed_description':'新发现题录，尚待详细阅读。','source':m.get('journalInfo',{}).get('journal',{}).get('title') or 'PubMed','resource_type':'; '.join(types) or '期刊文献','year':int(m['pubYear']) if str(m.get('pubYear','')).isdigit() else None,'language':'zh' if m.get('language')=='chi' else 'en','urls':urls,'doi':m.get('doi'),'pmid':pid,'pmcid':m.get('pmcid'),'authors':[x.get('fullName','') for x in m.get('authorList',{}).get('author',[])],
 'first_added_at':now(),'last_changed_at':now(),'identity':{'status':'verified','source_url':p['source_url'],'checked_at':p['checked_at'],'scope':'PubMed题名与DOI对应；尚未阅读全文','conflicts':[]},'note':None,'page_checks':[],'fulltext':{'status':'unknown','url':None,'read_scope':None},'publication_status':'verified-index-pending-reading','video':{'playback':'unknown','embedding':'unknown','embed_test':'not_attempted','relations':[]}}
 classify(r,tax)
 if r['procedures'] and not all(x.endswith('-general') for x in r['procedures']):
  sections=[next(p['section'] for p in tax['procedures'] if p['id']==pid) for pid in r['procedures']]
  r['section']=sections[0];r['cross_sections']=list(dict.fromkeys(sections))
 if all(x.endswith('-general') for x in r['procedures']):return None,'procedure classification requires review'
 if r.get('pmcid'):r['identity_keys'].append('pmcid:'+r['pmcid'])
 r['corrections']=p['corrections'];return r,None

def discover_videos(source,known,*,max_pages=50):
 if source.get('mode')=='wordpress':
  candidates={};ledger=[];page=1
  since=source.get('modified_after') or (datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%S')
  while page<=max_pages:
   resp,log=fetch(source['api'],{'per_page':100,'page':page,'orderby':'modified','order':'asc','modified_after':since,'_fields':'id,link,title,date_gmt,modified_gmt,type'})
   if resp is None or resp.status_code!=200:raise RuntimeError('video CMS request failed')
   data=resp.json()
   if not isinstance(data,list):raise ValueError('invalid video CMS schema')
   total=resp.headers.get('X-WP-TotalPages')
   if total is None:raise ValueError('video CMS pagination header missing')
   for item in data:
    u=item.get('link','');title=BeautifulSoup(item.get('title',{}).get('rendered',''),'html.parser').get_text(' ',strip=True)
    if urllib.parse.urlsplit(u).hostname==source['host'] and re.search(source['allowed_path'],urllib.parse.urlsplit(u).path):candidates[u]=title
   ledger.append({'url':log['requested_url'],'at':log['checked_at'],'page':page,'total_pages':int(total),'returned':len(data),'modified_after':since,'sha256':log['sha256']})
   if page>=max(1,int(total)):return candidates,ledger
   page+=1
  raise ValueError('video CMS pagination budget exceeded')
 queue=[source['url']];visited=set();candidates={};ledger=[]
 while queue:
  if len(visited)>=max_pages:raise ValueError('video directory pagination budget exceeded')
  url=queue.pop(0)
  if url in visited:continue
  visited.add(url);resp,log=fetch(url)
  if resp is None or resp.status_code!=200:raise RuntimeError('video directory unavailable '+str(log.get('status')))
  soup=BeautifulSoup(resp.content,'html.parser');title=soup.title.get_text(' ',strip=True) if soup.title else ''
  if re.search('access denied|just a moment|404|not found',title,re.I):raise ValueError('video directory challenge or soft404')
  got=0
  for a in soup.select(source['article_selector']):
   u=urllib.parse.urljoin(url,a.get('href',''));p=urllib.parse.urlsplit(u);t=a.get_text(' ',strip=True)
   if p.hostname!=source['host'] or not re.search(source['allowed_path'],p.path) or not t or len(t)<8 or u==url:continue
   if re.search(r'\.(mp4|m3u8|webm|mov|mp3)(?:$|\?)',u,re.I):continue
   u=urllib.parse.urlunsplit((p.scheme,p.netloc,p.path,p.query,''));candidates[u]=t;got+=1
  for a in soup.select('a[rel=next],a.next,a.next.page-numbers'):
   u=urllib.parse.urljoin(url,a.get('href',''))
   if urllib.parse.urlsplit(u).hostname==source['host'] and u not in visited:queue.append(u)
  ledger.append({'url':url,'at':log['checked_at'],'page':len(visited),'candidate_links':got,'sha256':log['sha256']})
 if not candidates:raise ValueError('empty directory extraction; preserve previous source watermark')
 return candidates,ledger

def candidate_video(url,title,source,tax):
 resp,log=fetch(url,retries=1)
 if resp is None or resp.status_code!=200:return None,'具体视频页面访问失败'
 from video_parser import parse_video_candidate
 check,description,reason=parse_video_candidate(resp.content,title,source,log)
 if reason:return None,reason
 actual=check['official_title']
 r={'id':'eye-v-'+digest('url:'+urlnorm(url))[:12],'kind':'video','title':actual,'aliases':[],'source_keys':[],'identity_keys':['url:'+urlnorm(url)],'seed_history':[],
 'seed_description':'新核验视频页；播放待测试。','source':source['id'],'resource_type':'讲座/教学资料' if re.search('lecture|webinar|讲座',actual,re.I) else '手术教学（完整性未核实）','year':None,'language':'zh' if re.search('[\u4e00-\u9fff]',actual) else 'en','urls':[{'label':'原站视频页','url':url}],'doi':None,'pmid':None,'pmcid':None,'authors':[],'first_added_at':now(),'last_changed_at':now(),'identity':{'status':'verified','source_url':url,'checked_at':log['checked_at'],'scope':'官方目录与具体页面题名及正文说明对应；播放未测试','conflicts':[]},'note':None,'page_checks':[check],'fulltext':{'status':'not_applicable','url':None,'read_scope':None},'publication_status':'verified-index','video':{'playback':'unknown','embedding':'unknown','embed_test':'not_attempted','duration':None,'audio_language':None,'subtitle_language':None,'summary':'原站内容说明（短摘录）：“'+' '.join(description.split()[:24])+'…”','summary_basis':'官方具体页面正文的内容介绍，未用转录或播放推断；'+url,'relations':[]}}
 classify(r,tax)
 if all(p.endswith('-general') for p in r['procedures']):return None,'视频术式尚不能可靠分类'
 secs=[next(p['section'] for p in tax['procedures'] if p['id']==pid) for pid in r['procedures']];r['section']=secs[0];r['cross_sections']=list(dict.fromkeys(secs));return r,None

def validate_transition(old,new):
 old_ids={r['id'] for r in old};new_ids=[r['id'] for r in new]
 if not old_ids.issubset(new_ids):raise ValueError('unexpected record deletion')
 if len(new_ids)!=len(set(new_ids)):raise ValueError('duplicate stable IDs')
 by={r['id']:r for r in new}
 for r in old:
  if r.get('note')!=by[r['id']].get('note'):raise ValueError('updater attempted to replace reading notes')
 for r in new:public_record(r)

def run(skip_links=False):
 cfg=read(ROOT/'config/update.json');tax=read(ROOT/'config/taxonomy.json');old=read(ROOT/'data/records.json',[])
 if not old:raise ValueError('missing baseline; abort')
 state=read(ROOT/'data/update-state.json',{'sources':{},'rotation':0});status=read(ROOT/'data/status.json',{});start=now();today=datetime.date.today();candidate_records=deepcopy(old);known={k for r in old for k in r.get('identity_keys',[])};staged=read(ROOT/'data/review-queue.json',[]);staged_keys={x['key'] for x in staged};runlog={'started_at':start,'mode':'local' if not os.environ.get('GITHUB_ACTIONS') else 'github-actions','sources':{},'pubmed_checks':[],'primary_link_checks':[],'link_check_mode':'separate baseline audit' if skip_links else 'primary links','added':0,'staged':0,'errors':[],'finished_at':None};status['last_attempt']=start
 def stage(key,title,reason,source,url=None):
  if key not in staged_keys:staged.append({'key':key,'title':title,'reason':reason,'source':source,'url':url,'discovered_at':now()});staged_keys.add(key);runlog['staged']+=1
 sections=list(cfg['article_queries']);rot=state.get('rotation',0)%len(sections)
 for section,base in cfg['article_queries'].items():
  name='EuropePMC-'+section;prev=deepcopy(state['sources'].get(name,{}));last=prev.get('last_success',start);begin=(datetime.date.fromisoformat(last[:10])-datetime.timedelta(days=cfg['overlap_days'])).isoformat();end=today.isoformat();q=f'({base}) AND (FIRST_IDATE:[{begin} TO {end}] OR UPDATE_DATE:[{begin} TO {end}])'
  entry={'query':q,'date_fields':['FIRST_IDATE','UPDATE_DATE'],'from':begin,'to':end,'status':'running','added':0,'last_success':prev.get('last_success')}
  try:
   rows,ledger=paginate(q,page_size=cfg['page_size'],max_pages=cfg['max_pages_per_source']);entry.update(pages=ledger,hits=len(rows),pagination_complete=True)
   if sections[rot]==section:
    hend=prev.get('historical_end',cfg['historical_initial_end']);hbegin=(datetime.date.fromisoformat(hend)-datetime.timedelta(days=cfg['historical_rotation_days'])).isoformat();hq=f'({base}) AND FIRST_PDATE:[{hbegin} TO {hend}]';hrs,hledger=paginate(hq,page_size=cfg['page_size'],max_pages=cfg['max_pages_per_source']);rows+=hrs;entry['historical']={'query':hq,'pages':hledger,'hits':len(hrs),'complete':True};prev['historical_end']=hbegin
   unmatched=[]
   for m in rows:
    keys={('doi:'+doi(m['doi'])) if m.get('doi') else '',('pmid:'+m['id']) if m.get('source')=='MED' else '',('pmcid:'+m['pmcid']) if m.get('pmcid') else ''}-{''}
    if keys&known:continue
    unmatched.append(m)
   dedup={str(m.get('source'))+':'+str(m.get('id')):m for m in unmatched};unmatched=list(dedup.values());pm,logs=pubmed_records(unmatched);runlog['pubmed_checks']+=logs
   for m in unmatched:
    key=str(m.get('source'))+':'+str(m.get('id'));r,reason=candidate_article(m,pm.get(m.get('id')),section,tax)
    if not r:stage(key,m.get('title'),reason,name);continue
    if set(r['identity_keys'])&known:continue
    candidate_records.append(r);known.update(r['identity_keys']);entry['added']+=1;runlog['added']+=1
   required={m['id'] for m in unmatched if m.get('source')=='MED'};missing=required-set(pm)
   if missing:
    entry.update(status='partial',verification_complete=False,missing_primary_records=len(missing),error='部分PubMed原始题录取得失败；保留上次成功水位');runlog['errors'].append(name)
   else:
    entry.update(status='success',last_success=now(),verification_complete=True);state['sources'][name]={**prev,'last_success':entry['last_success'],'last_query':q}
  except Exception as exc:entry.update(status='failed',error=str(exc)[:1500],pagination_complete=False);runlog['errors'].append(name)
  runlog['sources'][name]=entry;print(name,entry['status'],entry.get('hits'),entry.get('added'),flush=True)
  write(ROOT/'reports/current-run.json',runlog)
 for source in cfg['video_sources']:
  name='Video-'+source['id'];prev=state['sources'].get(name,{});entry={'status':'running','last_success':prev.get('last_success'),'added':0}
  try:
   source={**source,'modified_after':(datetime.datetime.fromisoformat(prev.get('last_success',start))-datetime.timedelta(days=cfg['overlap_days'])).strftime('%Y-%m-%dT%H:%M:%S')}
   videos,ledger=discover_videos(source,known);entry.update(hits=len(videos),pages=ledger,pagination_complete=True,scope='配置官方目录暴露的全部链接；或CMS指定时间窗口完整分页，不代表平台所有历史视频')
   known_urls={urlnorm(u['url']) for r in candidate_records for u in r.get('urls',[])}
   for url,title in videos.items():
    if urlnorm(url) in known_urls:continue
    r,reason=candidate_video(url,title,source,tax)
    if r:
     candidate_records.append(r);known_urls.add(urlnorm(url));known.update(r['identity_keys']);entry['added']+=1;runlog['added']+=1
    else:stage('video:'+digest(url),title,reason,name,url)
   entry.update(status='success',last_success=now());state['sources'][name]={'last_success':entry['last_success'],'last_directory_hashes':[x['sha256'] for x in ledger]}
  except Exception as exc:entry.update(status='failed',error=str(exc)[:1000],pagination_complete=False);runlog['errors'].append(name)
  runlog['sources'][name]=entry;print(name,entry['status'],entry.get('hits'),flush=True);write(ROOT/'reports/current-run.json',runlog)
 # Previously indexed papers must also be checked for later corrections/retractions.
 existing_pm=[{'id':str(r['pmid']),'source':'MED'} for r in old if r.get('pmid')]
 pm_current,pm_logs=pubmed_records(existing_pm);runlog['pubmed_checks']+=pm_logs
 for r in candidate_records:
  p=pm_current.get(str(r.get('pmid','')))
  if not p:continue
  r['corrections']=p['corrections'];r['scientific_status_checked_at']=p['checked_at']
  if p['corrections']:stage('notice:'+r['id']+digest(json.dumps(p['corrections'])),r['title'],'PubMed存在更正/撤稿等关联记录，须按RefType逐项解释','PubMed-status',p['source_url'])
  if not _title_matches(r['title'],p['title'],'citation_title'):stage('changed-title:'+r['id'],r['title'],'原始题录题名出现变化或身份待复核；保留现有笔记','PubMed-status',p['source_url'])
 missing_existing={x['id'] for x in existing_pm}-set(pm_current)
 prev_status=state['sources'].get('PubMed-status',{});scientific={'status':'partial' if missing_existing else 'success','hits':len(pm_current),'missing':len(missing_existing),'added':0,'last_success':prev_status.get('last_success')}
 if not missing_existing:scientific['last_success']=now();state['sources']['PubMed-status']={'last_success':scientific['last_success']}
 else:runlog['errors'].append('PubMed-status')
 runlog['sources']['PubMed-status']=scientific
 if not skip_links:
  from verify import one
  from concurrent.futures import ThreadPoolExecutor,as_completed
  hosts={}
  for r in candidate_records:
   if r.get('urls'):hosts.setdefault(urllib.parse.urlsplit(r['urls'][0]['url']).hostname,[]).append(r)
  def check_host(items):
   failures=0;results=[]
   for r in items:
    if failures>=3:
     results.append((r['id'],r['urls'][0]['url'],{'requested_url':r['urls'][0]['url'],'checked_at':now(),'status':None,'check_scope':'deferred-source-outage','page_state':'来源连续失败，暂停本轮该源请求；保留上一记录'}));continue
    rid,url,c=one((r['id'],r['urls'][0]['url'],r['title']));results.append((rid,url,c))
    if c.get('status')!=200:failures+=1
   return results
  with ThreadPoolExecutor(max_workers=6) as pool:
   for f in as_completed([pool.submit(check_host,items) for items in hosts.values()]):
    for rid,url,check in f.result():
     runlog['primary_link_checks'].append({'id':rid,**check});r=next(x for x in candidate_records if x['id']==rid)
     previous=next((x for x in reversed(r.get('page_checks',[])) if x.get('status')==200 and x.get('sha256')),None)
     if previous and check.get('status')==200 and check.get('sha256')!=previous['sha256']:
      r['source_changed_since_note']=True;stage('page-change:'+rid+check['sha256'],r['title'],'主来源页面内容哈希变化，正文笔记保持原值，等待复核','link-audit',url)
     r.setdefault('page_checks',[]).append(check)
    print('primary links',len(runlog['primary_link_checks']),flush=True)
  runlog['link_audit_scope']={'attempted':sum(x.get('check_scope')!='deferred-source-outage' for x in runlog['primary_link_checks']),'deferred':sum(x.get('check_scope')=='deferred-source-outage' for x in runlog['primary_link_checks'])}
 validate_transition(old,candidate_records)
 snapshot=ROOT/'data/versions'/digest(json.dumps(old,ensure_ascii=False,sort_keys=True));snapshot.mkdir(parents=True,exist_ok=True)
 if not (snapshot/'records.json').exists():write(snapshot/'records.json',old)
 state['rotation']=(rot+1)%len(sections);write(ROOT/'data/records.json',candidate_records);write(ROOT/'data/review-queue.json',staged);write(ROOT/'data/update-state.json',state)
 runlog['finished_at']=now();runlog['outcome']='partial' if runlog['errors'] else 'success';status['sources']=runlog['sources'];status['last_attempt']=start;status['last_local_run']=runlog['finished_at'];status['last_outcome']=runlog['outcome'];status['last_attempt_status']=runlog['outcome'];status['last_counts']={'added':runlog['added'],'staged':runlog['staged'],'records':len(candidate_records)};status['last_errors']=[{'source':name,'reason':runlog['sources'].get(name,{}).get('error','来源复核未完成')} for name in runlog['errors']]
 if not runlog['errors']:status['last_success']=runlog['finished_at']
 status.setdefault('deployed',False);status.setdefault('schedule_state','配置已生成，远程未验证');status['schedule_description']='每周一09:17 · Asia/Shanghai；复用既有维护时段'
 from zoneinfo import ZoneInfo
 t=datetime.datetime.now(ZoneInfo(cfg['timezone']));n=(t+datetime.timedelta(days=(7-t.weekday())%7)).replace(hour=9,minute=17,second=0,microsecond=0)
 if n<=t:n+=datetime.timedelta(days=7)
 status['next_run']=n.isoformat();write(ROOT/'data/status.json',status);write(ROOT/'reports/current-run.json',runlog);write(ROOT/'reports/runs'/(start.replace(':','-')+'.json'),runlog);build();print(json.dumps({'outcome':runlog['outcome'],'added':runlog['added'],'staged':runlog['staged'],'records':len(candidate_records)},ensure_ascii=False))

def urlnorm(u):
 p=urllib.parse.urlsplit(u);return urllib.parse.urlunsplit((p.scheme,p.netloc.lower(),p.path.rstrip('/'),p.query,''))
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--skip-links',action='store_true',help='For baseline runs that have a separate full-library audit; recorded in log.');a=p.parse_args()
 lockpath=ROOT/'data/.update.lock';lockpath.parent.mkdir(exist_ok=True)
 with open(lockpath,'w') as f:
  fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);run(skip_links=a.skip_links)
