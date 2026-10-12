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
    vague={**a,'entity':entity+'-vague','operation_id':run+'v1','description':'take the project'}
    client.take(vague)
    ambiguity=client.take({**vague,'operation_id':run+'v2','description':'work on an independent contribution'})
    assert ambiguity['decision']=='TAKEN_WITH_SCOPE_ADVICE',ambiguity
    client.request('/alias',{'entity':entity+'-alias','aliases':[run+' project']})
    client.take({**a,'entity':entity+'-alias','operation_id':run+'alias1'})
    alias=client.take({**a,'entity':run+' project','operation_id':run+'alias2','description':'authentication signin'})
    assert alias['decision']=='CHOOSE_DIFFERENT_ANGLE',alias
    common={'provider':'internal-check','action':'one-external-action','payload_hash':digest('exact body'),'source_version':'v1','actor':'actor'}
    first=client.reserve({**common,'operation_id':run+'multi1','conversation_id':run+'groupAB','conversation_ids':[run+'recipientA',run+'recipientB']})
    second=client.reserve({**common,'operation_id':run+'multi2','actor':'other-actor','conversation_id':run+'groupAC','conversation_ids':[run+'recipientA',run+'recipientC'],'payload_hash':digest('different wording')})
    assert first['decision']=='RESERVED' and second['decision']=='DO_NOT_SEND',(first,second)
    winner=winners[0]['operation_id'];winner_index=int(winner.removeprefix(run+'send'))
    bound={**common,'operation_id':winner,'actor':'actor'+str(winner_index),'payload_hash':digest('approved body'),'conversation_id':run,'action':'same-inbound-event'}
    dispatched=client.request('/transition',{**bound,'before':'RESERVED','after':'DISPATCHED'})
    assert dispatched['dispatch_winner'] is True,dispatched
    replay=client.request('/transition',{**bound,'before':'RESERVED','after':'DISPATCHED'})
    assert replay['decision']=='DO_NOT_SEND',replay
    client.request('/transition',{**bound,'before':'DISPATCHED','after':'UNKNOWN_EFFECT'})
    unknown=client.reserve({**bound,'operation_id':run+'unknown-new','conversation_id':run,'action':'same-inbound-event'})
    assert unknown['decision']=='DO_NOT_SEND' and unknown['state']=='UNKNOWN_EFFECT',unknown
    for oid in (run+'a',run+'c'):client.progress({'operation_id':oid,'owner':'focused-check','state':'RELEASED'})
    for oid in (run+'v1',run+'v2',run+'alias1'):client.progress({'operation_id':oid,'owner':'focused-check','state':'RELEASED'})
    print(json.dumps({'run':run,'scope_checks':results,'ambiguous_scope':ambiguity['decision'],'alias_overlap':alias['decision'],
        'concurrent_reservations':8,'winners':len(winners),'overlapping_recipient_sets':second['decision'],
        'dispatch_replay':replay['decision'],'unknown_effect_retake':unknown['decision'],'outbound_provider_calls':0}))
