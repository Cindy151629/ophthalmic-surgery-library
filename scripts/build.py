"""Build the local/offline reader and a whitelist-only publishable site."""
from common import *
from collections import Counter
from copy import deepcopy
import shutil

PUBLIC_KEYS=['id','kind','title','aliases','seed_description','source','resource_type','year','language','section','procedures','cross_sections','doi','pmid','pmcid','authors','first_added_at','last_changed_at','identity','note','page_checks','fulltext','publication_status','video','corrections','scientific_status_checked_at','source_changed_since_note']
CHECK_KEYS=['requested_url','final_url','checked_at','status','sha256','page_state','page_title','title_present','title_match_source','content_format','body_present']
def public_record(r):
 d={k:deepcopy(r.get(k)) for k in PUBLIC_KEYS}
 d['page_checks']=[{k:c.get(k) for k in CHECK_KEYS if k in c} for c in r.get('page_checks',[])]
 if isinstance(d['authors'],str):d['authors']=[d['authors']]
 if not d['authors']:d['authors']=[]
 for x in d['urls'] if 'urls' in d else []:assert urllib.parse.urlsplit(x['url']).scheme in ['https','http']
 d['urls']=[{'url':u['url'],'label':u['label']} for u in r.get('urls',[]) if urllib.parse.urlsplit(u.get('url','')).scheme in ['https','http']]
 # Never publish runtime/cache paths or private manual-note storage.
 raw=json.dumps(d,ensure_ascii=False)
 if re.search(r'/Users/|/home/|ghp_[A-Za-z0-9]{15}|sk-[A-Za-z0-9]{20}|BEGIN .*PRIVATE KEY',raw):raise ValueError('private content in public record '+r['id'])
 return d
def coverage(records,tax):
 out=[]
 patterns={'guideline':r'guideline|consensus|practice pattern|recommendation|指南|共识|建议', 'comparative':r'random|trial|compar|meta.analysis|follow.up|比较|随机|荟萃|随访','technical':r'technique|technical|curriculum|review|技术|手术方法|综述','complication':r'complication|adverse|endophthalmitis|并发症|不良|眼内炎'}
 for p in tax['procedures']:
  rs=[r for r in records if p['id'] in r['procedures']];row={'id':p['id'],'zh':sum(r['language']=='zh' for r in rs),'en':sum(r['language']=='en' for r in rs)}
  for key,pat in patterns.items():
   n=sum(r['kind']=='literature' and bool(re.search(pat,r['title']+' '+r['resource_type'],re.I)) for r in rs);row[key]={'count':n,'status':'已有资源' if n else '尚未检索','basis':'当前导入资源的题录分类，非完整检索结论'}
  n=sum(r['kind']=='video' for r in rs);row['video']={'count':n,'status':'已有资源' if n else '尚未检索'};out.append(row)
 return out
def build():
 records=read(ROOT/'data/records.json',[])
 if not records:raise ValueError('empty database: refusing build')
 public=[public_record(r) for r in records];tax=read(ROOT/'config/taxonomy.json');status=read(ROOT/'data/status.json',{})
 version=digest(json.dumps(public,ensure_ascii=False,sort_keys=True));cov=coverage(public,tax);data={'records':public,'taxonomy':tax,'coverage':cov,'status':status,'deployment':read(ROOT/'config/deployment.json',{}),'version':version,'built_at':now(),'audit_summary':f"当前 {len(public)} 条去重资源；身份核验、详细阅读与播放测试分别计数。"}
 site=ROOT/'site';site.mkdir(exist_ok=True)
 raw=json.dumps(data,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
 html=(ROOT/'src/index.html').read_text().replace('/*STYLE*/',(ROOT/'src/style.css').read_text()).replace('/*SCRIPT*/',(ROOT/'src/app.js').read_text()).replace('/*DATA*/',raw)
 tmp=site/'index.html.tmp';tmp.write_text(html);tmp.replace(site/'index.html');shutil.copy2(site/'index.html',ROOT/'眼科手术阅读库.html');(site/'.nojekyll').write_text('')
 write(site/'records.json',public);write(site/'manifest.json',{'version':version,'built_at':data['built_at'],'records':len(records),'status':status});write(ROOT/'reports/coverage.json',cov)
 write(ROOT/'reports/build.json',{'at':now(),'version':version,'records':len(records),'kinds':dict(Counter(r['kind'] for r in records)),'note_scopes':dict(Counter(r.get('note',{}).get('scope') if r.get('note') else 'pending' for r in records if r['kind']=='literature')),'note_completion':dict(Counter(r.get('note',{}).get('completion') if r.get('note') else 'pending' for r in records if r['kind']=='literature')),'identities':dict(Counter(r['identity']['status'] for r in records)),'videos':dict(Counter(r['video']['playback'] for r in records if r['kind']=='video'))})
 print('built',len(records),version,flush=True)
if __name__=='__main__':build()
