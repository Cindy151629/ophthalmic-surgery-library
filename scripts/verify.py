"""Bounded primary-page checks. A page check never upgrades playback or reading."""
from common import *
from page_parser import parse_page_content,txt
from concurrent.futures import ThreadPoolExecutor,as_completed
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET

def one(item):
 rid,url,title=item
 resp,log=fetch(url,retries=1)
 if resp is not None:
  log,body=parse_page_content(resp.content,title,log)
  dest=WORK/'page_cache';dest.mkdir(exist_ok=True)
  (dest/(digest(url)+'.txt')).write_text(body)
  if len(resp.content)<12_000_000:(dest/(digest(url)+'.bin')).write_bytes(resp.content)
  log['text_cache_hash']=digest(url)
  if log.get('content_format')=='HTML':
   soup=BeautifulSoup(resp.content,'html.parser')
   log['players']=[{'kind':x.name,'src':x.get('src'),'type':x.get('type')} for x in soup.select('video, iframe') if x.get('src') or x.name=='video'][:10]
   log['canonical_url']=next((x.get('href') for x in soup.select('link[rel=canonical]')),None)
 return rid,url,log

def run(kind='video',limit=None):
 records=read(ROOT/'data/records.json',[]);logs=read(WORK/'page_checks.json',{})
 tasks=[]
 for r in records:
  if kind!='all' and r['kind']!=kind:continue
  urls=r['urls'][:1] if r['kind']=='video' else r['urls']
  for link in urls:
   url=link['url'];key=digest(url)
   if key not in logs:tasks.append((r['id'],url,r['title']))
 if limit:tasks=tasks[:limit]
 with ThreadPoolExecutor(max_workers=8) as pool:
  for f in as_completed([pool.submit(one,x) for x in tasks]):
   rid,url,log=f.result();logs[digest(url)]=log;write(WORK/'page_checks.json',logs)
   if len(logs)%20==0:print('checked',len(logs),flush=True)
 print('completed',len(tasks),'cached',len(logs),flush=True)

if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--kind',default='video');p.add_argument('--limit',type=int);a=p.parse_args();run(a.kind,a.limit)
