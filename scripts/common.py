from pathlib import Path
import json,datetime,hashlib,re,os,urllib.parse,socket,ipaddress,time,threading
import requests
ROOT=Path(__file__).resolve().parents[1]
WORK=Path(os.environ.get('OPHTH_WORK_DIR',str(ROOT.parents[1]/'work/ophthalmic_surgery')))
WORK.mkdir(parents=True,exist_ok=True)
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def read(p,default=None):
 p=Path(p);return json.loads(p.read_text()) if p.exists() else default
def write(p,d):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(d,ensure_ascii=False,indent=2));tmp.replace(p)
def digest(b):return hashlib.sha256(b.encode('utf-8') if isinstance(b,str) else b).hexdigest()
def norm(s):return re.sub(r'[^\w]','',str(s).casefold())
def doi(s):return re.sub(r'^https?://(?:dx\.)?doi.org/','',str(s or '').strip().lower()).rstrip('.')
_locks={};_guard=threading.Lock();_last={}
def safe_url(url):
 p=urllib.parse.urlsplit(url)
 if p.scheme not in ('https','http') or not p.hostname or p.username or p.password:raise ValueError('unsafe URL')
 for item in socket.getaddrinfo(p.hostname,p.port or (443 if p.scheme=='https' else 80)):
  if not ipaddress.ip_address(item[4][0]).is_global:raise ValueError('private destination denied')
 return p.hostname
def fetch(url,params=None,timeout=22,retries=2,conditional=None):
 if params:url+='&' if '?' in url else '?';url+=urllib.parse.urlencode(params) if params else ''
 initial=url;record={'requested_url':initial,'checked_at':now(),'attempts':[]}
 for attempt in range(retries+1):
  try:
   for redirect in range(8):
    host=safe_url(url)
    with _guard:lock=_locks.setdefault(host,threading.Lock())
    with lock:
     time.sleep(max(0,.45-(time.monotonic()-_last.get(host,0))))
     if re.search(r'\.(mp4|m3u8|webm|mov|mp3)(?:$|\?)',url,re.I):raise ValueError('media download disabled')
     headers={'User-Agent':'Ophthalmic-Surgery-Library/1.0 (educational bibliography verification)'}
     headers.update({k:v for k,v in (conditional or {}).items() if k in ('If-None-Match','If-Modified-Since') and isinstance(v,str)})
     r=requests.get(url,timeout=timeout,allow_redirects=False,stream=True,headers=headers)
     ct=r.headers.get('content-type','').lower()
     if ct.startswith(('video/','audio/')) or 'mpegurl' in ct:
      r.close();raise ValueError('media download disabled')
     chunks=[];size=0
     for chunk in r.iter_content(65536):
      size+=len(chunk)
      if size>25_000_000:r.close();raise ValueError('response size budget exceeded')
      chunks.append(chunk)
     r._content=b''.join(chunks);r._content_consumed=True;r.close()
     _last[host]=time.monotonic()
    if r.status_code in (301,302,303,307,308) and r.headers.get('Location'):url=urllib.parse.urljoin(url,r.headers['Location']);continue
    break
   record['attempts'].append({'status':r.status_code,'url':r.url});record.update(status=r.status_code,final_url=r.url,content_type=r.headers.get('content-type',''),bytes=len(r.content),sha256=digest(r.content))
   record.update(etag=r.headers.get('etag'),last_modified=r.headers.get('last-modified'))
   if r.status_code in (429,500,502,503,504) and attempt<retries:time.sleep(min(8,2**(attempt+1)));continue
   return r,record
  except Exception as e:
   record['attempts'].append({'error':type(e).__name__+': '+str(e)[:250]})
   if attempt<retries:time.sleep(1+attempt)
 record.update(status=None,error=record['attempts'][-1].get('error','request failed'),final_url=url)
 return None,record
