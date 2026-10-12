"""Direct shared-credential cloud client; no secrets written or printed."""
import json
import urllib.request
from coordinator import digest

BASE='https://swarm-collision-coordinator.tjlabs-publisher.workers.dev'
class CloudCoordinator:
    def __init__(self, credential_loader, base=BASE):
        self.loader,self.base=credential_loader,base
    def request(self,path,payload=None):
        request=urllib.request.Request(self.base+path,data=None if payload is None else json.dumps(payload).encode(),
            headers={'Authorization':'Bearer '+self.loader(),'Content-Type':'application/json','User-Agent':'TokenJunkieLabs-Collision-Coordinator'})
        with urllib.request.urlopen(request,timeout=25) as response:return json.load(response)
    def take(self,r):return self.request('/take',r)
    def progress(self,r):return self.request('/progress',r)
    def reserve(self,r):return self.request('/reserve',r)
    def snapshot(self):return self.request('/snapshot')
    def dispatch(self,r,send,readback,no_effect_checker=None):
        result=self.reserve(r)
        if result['decision']!='RESERVED':return result
        binding={k:r[k] for k in ('operation_id','provider','conversation_id','action','payload_hash','source_version','actor')}
        winner=self.request('/transition',{**binding,'before':'RESERVED','after':'DISPATCHED'})
        if winner.get('dispatch_winner') is not True:return winner
        effect=None
        try:
            effect=send(r);receipt=readback(effect,r)
            if not receipt or receipt.get('verified') is not True or receipt.get('actor')!=r['actor'] or not receipt.get('provider_id'):
                raise ValueError('provider readback incomplete')
            self.request('/transition',{**binding,'before':'DISPATCHED','after':'SENT','receipt':receipt})
            return {'decision':'SENT','receipt':receipt}
        except BaseException:
            if no_effect_checker is not None and isinstance(effect,dict):
                try:
                    result=no_effect_checker(effect,r)
                    if result and result.get('decision')=='NO_EFFECT_CONFIRMED':return result
                except Exception:pass
            partial=None
            if isinstance(effect,dict):
                handle=effect.get('ts') or effect.get('id') or effect.get('publication',{}).get('receipt',{}).get('id')
                if handle:partial={'provider_id':str(handle),'thread_id':effect.get('thread_id',effect.get('threadId')),
                                  'label_ids':effect.get('label_ids',effect.get('labelIds')),'actor':r['actor'],'verified':False}
            try:self.request('/transition',{**binding,'before':'DISPATCHED','after':'UNKNOWN_EFFECT','receipt':partial})
            except Exception:pass # DISPATCHED cloud fence survives local transport loss.
            raise
