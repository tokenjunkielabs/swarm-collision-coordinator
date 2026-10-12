import concurrent.futures
import json
import sys
import uuid
sys.path.insert(0,'C:/Users/lucys/Documents/Codex/2026-08-25/yo/work/commons-spark-link')
from integrations.shared_equipment.credential_transfer import CredentialSources
from cloud_client import CloudCoordinator
from coordinator import digest

if __name__=='__main__':
    token=CredentialSources().read('github/tokenjunkielabs')
    client=CloudCoordinator(lambda:token)
    run='focused-'+uuid.uuid4().hex
    entity='internal-check:'+run
    results=[]
    a={'operation_id':run+'a','owner':'focused-check','entity':entity,'description':'repair OAuth login'}
    results.append(client.take(a)['decision'])
    results.append(client.take({**a,'operation_id':run+'b','description':'fix authentication signin'})['decision'])
    results.append(client.take({**a,'operation_id':run+'c','description':'improve billing checkout'})['decision'])
    def reserve(n):return client.reserve({'operation_id':run+'send'+str(n),'provider':'internal-check','conversation_id':run,
        'action':'same-inbound-event','payload_hash':digest('approved body'),'source_version':'v1','actor':'actor'+str(n)})
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:races=list(executor.map(reserve,range(8)))
    winners=[r for r in races if r['decision']=='RESERVED']
    assert results==['TAKEN','CHOOSE_DIFFERENT_ANGLE','TAKEN'],results
    assert len(winners)==1,races
    for oid in (run+'a',run+'c'):client.progress({'operation_id':oid,'owner':'focused-check','state':'RELEASED'})
    print(json.dumps({'run':run,'scope_checks':results,'concurrent_reservations':8,'winners':len(winners),'outbound_provider_calls':0}))
