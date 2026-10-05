"""Publish only dataset outputs to data, preserving every other file."""
import os
import time
from pathlib import Path
import requests

def publish():
    root=Path('data/datasets')
    files=[p for p in root.glob('*') if p.suffix in ['.json','.md']]
    if not files:print('No dataset files to publish');return
    repository=os.environ['GITHUB_REPOSITORY'];token=os.environ['GITHUB_TOKEN']
    session=requests.Session();session.headers.update({'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json'})
    def api(method,path,**kwargs):
        response=session.request(method,'https://api.github.com/repos/'+repository+path,timeout=40,**kwargs)
        response.raise_for_status();return response.json()
    for attempt in range(3):
        try:
            ref=api('GET','/git/ref/heads/data');head=ref['object']['sha']
            tree=api('GET','/git/commits/'+head)['tree']['sha']
        except requests.HTTPError as error:
            if error.response.status_code!=404:raise
            # A fresh fork can start an empty data tree without copying main.
            head=None;tree=None
        payload={'tree':[{'path':p.as_posix(),'mode':'100644','type':'blob','content':p.read_text(encoding='utf-8')} for p in files]}
        if tree:payload['base_tree']=tree
        new_tree=api('POST','/git/trees',json=payload)['sha']
        if new_tree==tree:print('Dataset outputs unchanged');return
        commit=api('POST','/git/commits',json={'message':'update: daily dataset selections','tree':new_tree,'parents':[head] if head else []})['sha']
        try:
            if head:api('PATCH','/git/refs/heads/data',json={'sha':commit,'force':False})
            else:api('POST','/git/refs',json={'ref':'refs/heads/data','sha':commit})
            print('Published dataset results:',commit);return
        except requests.HTTPError as error:
            if error.response.status_code not in (409,422) or attempt==2:raise
            time.sleep(2)
    raise RuntimeError('Dataset publication could not update data branch')
if __name__=='__main__':publish()
