"""Import relationship URLs from Word, with edition-qualified aliases and an audit."""
from common import *
from collections import Counter
import zipfile,xml.etree.ElementTree as ET

NS={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main','r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
def extract(path):
 with zipfile.ZipFile(path) as z:
  rel={r.get('Id'):r.get('Target') for r in ET.fromstring(z.read('word/_rels/document.xml.rels')) if r.get('TargetMode')=='External'}
  root=ET.fromstring(z.read('word/document.xml'));records=[];current=None
  for p in root.findall('.//w:body//w:p',NS):
   t=''.join(p.itertext()) if False else ''.join(x.text or '' for x in p.findall('.//w:t',NS))
   m=re.match(r'^([A-Z][A-Z0-9]*-(?:[APV]\d+|AAO))\s+(?:\|\s*)?(.+)',t)
   if m:
    current={'id':m[1],'title':m[2].strip(),'kind':'video' if '-V' in m[1] else 'literature','paragraphs':[],'links':[]};records.append(current)
   elif re.match(r'^\d{2}\s+',t):current=None
   elif current and t:current['paragraphs'].append(t)
   if current:
    for h in p.findall('.//w:hyperlink',NS):
     rid=h.get('{'+NS['r']+'}id');u=rel.get(rid)
     if u:current['links'].append({'label':''.join(x.text or '' for x in h.findall('.//w:t',NS)),'url':u})
 return records

def urlnorm(u):
 p=urllib.parse.urlsplit(u);return urllib.parse.urlunsplit((p.scheme.lower(),p.netloc.lower(),p.path.rstrip('/'),p.query,''))
def identities(r):
 ids=[]
 for x in r['links']:
  u=x.get('url') or ''
  if not u:continue
  if r['kind']=='video':
   # Only the entry's primary video URL; official catalog links are evidence, not identity.
   ids.append('url:'+urlnorm(u));break
  if 'doi.org/' in u and not any(k.startswith('doi:') for k in ids):ids.append('doi:'+doi(u))
  if m:=re.search(r'pubmed\.ncbi\.nlm\.nih\.gov/(\d+)',u):
   if not any(k.startswith('pmid:') for k in ids):ids.append('pmid:'+m[1])
  if m:=re.search(r'/articles/(PMC\d+)',u):
   # Correction notices are not an alternative identifier for the original article.
   if not any(k.startswith('pmcid:') for k in ids):ids.append('pmcid:'+m[1])
 if not ids:
  ids=['url:'+urlnorm(x['url']) for x in r['links'][:1] if x.get('url')]
 return ids

PREFIX={'CAT':'CAT','RET':'RET','GL':'GL','GLA':'GL','CR':'CR','COR':'CR','REF':'CR','OCP':'OCP','OPL':'OCP','LAC':'OCP','PTO':'PTO','STR':'PTO','PED':'PTO','TRA':'PTO','ONC':'PTO','GEN':'GEN','EDU':'GEN','CN':'GEN'}
def classify(r,tax):
 prefix=r['aliases'][0]['id'].split('-')[0] if r['aliases'] else ''
 section=PREFIX.get(prefix,'GEN');text=' '.join([r['title'],r.get('seed_description','')]).lower()
 matched=[p['id'] for p in tax['procedures'] if re.search(p['pattern'],text,re.I)]
 local=[p for p in matched if next(t for t in tax['procedures'] if t['id']==p)['section']==section]
 r['section']=section;r['procedures']=list(dict.fromkeys(local+matched)) or [section.lower()+'-general']
 r['cross_sections']=list(dict.fromkeys([next(t for t in tax['procedures'] if t['id']==p)['section'] for p in r['procedures']]))
 return r

def run():
 existing={r['id']:r for r in read(ROOT/'data/records.json',[])};out=[];index={};audit=[];tax=read(ROOT/'config/taxonomy.json')
 for edition in ['expanded','original']:
  src=read(WORK/f'{edition}_entries.json',[])
  for raw in src:
   keys=identities(raw);matches={index[(raw['kind'],k)] for k in keys if (raw['kind'],k) in index};key=edition+':'+raw['id']
   if len(matches)>1:
    audit.append({'source_key':key,'status':'pending-conflict','reason':'multiple canonical identities','matches':sorted(matches)})
   rid=next(iter(matches)) if len(matches)==1 else ('eye-'+('v-' if raw['kind']=='video' else 'a-')+digest(keys[0] if keys else key)[:12])
   alias={'edition':edition,'id':raw['id'],'title':raw['title']}
   if not matches or len(matches)>1:
    paras=raw.get('paragraphs',[]);line=paras[0] if paras else '';parts=[p.strip() for p in re.split(r'\s*[|·]\s*',line)]
    years=re.findall(r'\b(?:19|20)\d{2}\b',parts[0] if raw['kind']=='literature' else parts[-1])
    r={'id':rid,'kind':raw['kind'],'title':raw['title'],'aliases':[alias],'identity_keys':keys,'source_keys':[key],'seed_history':[{'source_key':key,'paragraphs':paras}],
       'seed_description':paras[1] if len(paras)>1 else '', 'source':parts[1] if raw['kind']=='literature' and len(parts)>1 else parts[0],
       'resource_type':parts[2] if raw['kind']=='literature' and len(parts)>2 else (parts[1] if len(parts)>1 else '未核实'),
       'year':int(years[0]) if years and '未标年' not in line else None,'language':'zh' if re.search(r'中文|中华|中国',line) else 'en',
       'urls':[{'label':x['label'],'url':x['url']} for x in raw['links'] if x.get('url')],'doi':None,'pmid':None,'pmcid':None,'authors':[],
       'first_added_at':now(),'last_changed_at':now(),'identity':{'status':'pending','scope':'种子文档历史记录，未继承为本轮已核验'},
       'note':None,'page_checks':[],'fulltext':{'status':'unknown','url':None,'read_scope':None},'publication_status':'pending',
       'video':{'playback':'unknown','embedding':'unknown','embed_test':'not_attempted','duration':None,'audio_language':None,'subtitle_language':None,'recorded_at':None,'published_at':None,'summary':paras[1] if len(paras)>1 else '', 'summary_basis':'种子文档概括；待原站核对','relations':[]}}
    for k in keys:
     if k.startswith(('doi:','pmid:','pmcid:')):a,b=k.split(':',1);r[a]=b
    if raw['id'].startswith('CN-'):r['language']='zh'
    if raw['kind']=='video':
     host=urllib.parse.urlsplit(r['urls'][0]['url']).hostname if r['urls'] else ''
     hosts={'morancore.utah.edu':'Moran CORE','cybersight.org':'Cybersight','webeye.ophth.uiowa.edu':'University of Iowa EyeRounds','eyerounds.org':'EyeRounds','eyetube.net':'Eyetube','www.aao.org':'AAO','www.djo.harvard.edu':'Digital Journal of Ophthalmology'}
     if host in hosts:r['source']=hosts[host]
    r=classify(r,tax);out.append(r);audit.append({'source_key':key,'canonical_id':rid,'status':'imported-pending'})
   else:
    r=next(x for x in out if x['id']==rid);r['aliases'].append(alias);r['source_keys'].append(key);r['seed_history'].append({'source_key':key,'paragraphs':raw['paragraphs']});r['identity_keys']=list(dict.fromkeys(r['identity_keys']+keys))
    for u in raw['links']:
     if u.get('url') and u['url'] not in [x['url'] for x in r['urls']]:r['urls'].append({'label':u['label'],'url':u['url']})
    audit.append({'source_key':key,'canonical_id':rid,'status':'merged','basis':sorted(set(keys)&set(r['identity_keys']))})
   for k in keys:index[(raw['kind'],k)]=rid
 # Re-import cannot erase notes, verification or first-added dates.
 for r in out:
  if r['id'] in existing:
   old=existing[r['id']]
   for k in ['note','identity','page_checks','fulltext','publication_status','video','first_added_at','last_changed_at','authors','doi','pmid','pmcid','source','resource_type','year','language','corrections','scientific_status_checked_at','source_changed_since_note','verification_details']:
    if k in old:r[k]=old[k]
 for rid,r in existing.items():
  if rid not in {x['id'] for x in out}:out.append(r)
 write(ROOT/'data/records.json',out)
 aliases={}
 for r in out:
  for a in r['aliases']:aliases.setdefault(a['id'],[]).append({'edition':a['edition'],'canonical_id':r['id'],'title':a['title']})
 report={'at':now(),'inputs':{'expanded':432,'original':177},'input_rows':len(audit),'canonical_records':len(out),'kind_counts':dict(Counter(r['kind'] for r in out)),
 'dispositions':dict(Counter(x['status'] for x in audit)),'same_label_different_identity':{k:v for k,v in aliases.items() if len({a['canonical_id'] for a in v})>1},'rows':audit}
 write(ROOT/'reports/import-reconciliation.json',report);print(json.dumps({k:v for k,v in report.items() if k not in ['rows','same_label_different_identity']},ensure_ascii=False))
if __name__=='__main__':run()
