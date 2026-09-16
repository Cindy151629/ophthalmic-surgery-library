"""Verify deployed artifact bytes; only then write a public deployment receipt."""
from common import *
import argparse
from cloud_recovery import SITE_FILES,validate_site
def schedule_evidence():
 token=os.environ.get('GITHUB_TOKEN');repo=os.environ.get('GITHUB_REPOSITORY')
 if not token or not repo:return {'schedule_active':None,'schedule_check_scope':'未提供远程工作流 API 凭据'}
 r=requests.get('https://api.github.com/repos/'+repo+'/actions/workflows/weekly.yml',headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'},timeout=20)
 if r.status_code!=200:return {'schedule_active':None,'schedule_api_status':r.status_code}
 d=r.json()
 return {'schedule_active':d.get('state')=='active','schedule_workflow_url':d.get('html_url'),'schedule_checked_at':now(),'schedule_check_scope':'GitHub Actions API 确认工作流 active；配置每周一 09:17 Asia/Shanghai。是否发生定时触发另看 observed_scheduled_run。'}
def verify(url,directory,rollback=False):
 expected={name:(directory/name).read_bytes() for name in SITE_FILES};hashes={n:digest(b) for n,b in expected.items()};errors=[];observed={}
 for attempt in range(6):
  errors=[]
  for name,body in expected.items():
   r,l=fetch(urllib.parse.urljoin(url,name),{'v':hashes[name][:12]},timeout=25,retries=1)
   if r is None or r.status_code!=200 or digest(r.content)!=hashes[name]:errors.append(name)
   observed[name]=l
  if not errors:break
  time.sleep(8)
 if errors:raise RuntimeError('deployed bytes differ: '+', '.join(errors))
 m=json.loads(expected['manifest.json']);stamp=now();prior=read(ROOT/'data/publication-status.json',{})
 receipt={'domain_id':'ophthalmic-surgery','deployed':True,'verified_at':stamp,'data_version':m['version'],'file_hashes':hashes,'https_url':url,'run_id':os.environ.get('GITHUB_RUN_ID'),'run_url':'https://github.com/'+os.environ.get('GITHUB_REPOSITORY','')+'/actions/runs/'+os.environ.get('GITHUB_RUN_ID',''),'event':os.environ.get('GITHUB_EVENT_NAME'),'observed_scheduled_run':stamp if os.environ.get('GITHUB_EVENT_NAME')=='schedule' else prior.get('observed_scheduled_run'),'rollback':rollback}
 receipt.update(schedule_evidence())
 from zoneinfo import ZoneInfo
 local=datetime.datetime.now(ZoneInfo('Asia/Shanghai'));next_run=local.replace(hour=9,minute=17,second=0,microsecond=0)+datetime.timedelta(days=(0-local.weekday())%7)
 if next_run<=local:next_run+=datetime.timedelta(days=7)
 receipt['next_planned_run']=next_run.isoformat()
 validate_site(expected,receipt);write(ROOT/'data/publication-status.json',receipt);write(ROOT/'reports/deployment-verification.json',{'at':stamp,'receipt':receipt,'responses':observed});print(json.dumps(receipt))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--url',required=True);p.add_argument('--expected-dir',type=Path,default=ROOT/'site');p.add_argument('--rollback',action='store_true');a=p.parse_args();verify(a.url,a.expected_dir,a.rollback)
