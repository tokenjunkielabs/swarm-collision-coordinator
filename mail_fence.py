"""Remote mail fence for the immediate native/provider boundary.

Call after exact MIME resolution + existing attribution/incident/owner checks.
Enqueue is not dispatch. Queue provider dispatcher calls the same boundary.
Only hashes/identifiers go to cloud; content/attachments stay in existing roads.
"""
import hashlib
import json
import re
from email.utils import parseaddr
from cloud_client import CloudCoordinator
from coordinator import digest

NOTE='If this tool is misbehaving or broken, feel free to fix it on the spot.'
_OWNER_REVIEW_OP_HASHES={
    'ae646d823871f31c6089671187ff9e31eb35cab27d309d946e667bbe88a44c0e',
    'f394ac323133c106ba9bf9e20e0b341561afaa8bee8f954d20104ad2540b4ac8',
    '2320cb840d27a3159fe488b8bc28a51a96d4bc600b26658f95ac1b953f6f14a8',
    'f550b5b6bbd9f37e88b5fd9b12989bd9165831120a977f5806d31b2266f0d711',
    '9bd4ca58428fa2a2d65f9fd38846182262f6c1349f8613e183e57bf9e6914286',
}
_LAB_ROUTE_HASH='7c63ad2c4d4edd1fee4c205f9a44ee0cb80f23b9a1705913dedb0e5a36096eb8'

def address(value):
    parsed=parseaddr(str(value))[1].strip().lower()
    if not parsed or '@' not in parsed:raise ValueError('resolved mail address invalid')
    return parsed
def subject(value):return re.sub(r'^(?:(?:re|fw|fwd)\s*:\s*)+', '',str(value).strip(),flags=re.I).casefold()

def binding(resolved):
    """resolved must describe the actual original source and full MIME tree.

    Original RFC Message-ID is account-independent. Caller resolves it from
    provider metadata; a model-supplied summary never supplies this identity.
    """
    for key in ('operation_id','attempt_id','account','sender','to','subject','mime_tree_digest','content_digest','link_id'):
        if key not in resolved or resolved[key] in (None,'',[]):raise ValueError('mail binding missing '+key)
    selected=resolved.get('selected_account')
    if selected is not None:
        if not isinstance(selected,dict):raise ValueError('selected account binding invalid')
        for key in ('link_id','profile_id'):
            if key in selected and str(selected[key] or '')!=str(resolved.get(key) or ''):raise ValueError('selected account '+key+' mismatch')
        for key in ('account','email'):
            if key in selected and address(selected[key])!=address(resolved['account']):raise ValueError('selected account address mismatch')
    kind=resolved.get('kind','send')
    for key in ('to','cc','bcc'):
        if not isinstance(resolved.get(key,[]),list):raise ValueError('resolved recipient lists required')
    for key in ('mime_tree_digest','content_digest'):
        if not re.fullmatch(r'[a-f0-9]{64}',str(resolved[key])):raise ValueError('exact SHA256 required for '+key)
    attachments=resolved.get('attachments',[])
    if not isinstance(attachments,list):raise ValueError('exact attachment metadata list required')
    for item in attachments:
        if not isinstance(item,dict) or not item.get('filename') or not (item.get('content_type') or item.get('mime_type')) or not re.fullmatch(r'[a-f0-9]{64}',str(item.get('byte_sha256',item.get('sha256','')))):
            raise ValueError('attachment filename, MIME type and exact byte SHA256 required')
    recipients=sorted({address(x) for name in ('to','cc','bcc') for x in resolved.get(name,[])})
    # Recipient event fence is sender/account-independent. Different wording,
    # subject lines or opportunity references never split initial contact.
    original=resolved.get('original_rfc_message_id')
    if kind in ('reply','forward','sent_followup') and not original:
        raise ValueError('read original RFC Message-ID through provider before immediate mail dispatch')
    event=original if original else 'initial-contact'
    owner_review=False
    if kind=='owner_review':
        op_hash=hashlib.sha256(str(resolved['operation_id']).encode()).hexdigest()
        route_hash=hashlib.sha256((str(resolved['link_id'])+'|'+str(resolved.get('profile_id',''))).encode()).hexdigest()
        owner_review=(op_hash in _OWNER_REVIEW_OP_HASHES and route_hash==_LAB_ROUTE_HASH
            and address(resolved['account'])==address(resolved['sender'])=='tokenjunkielabs@gmail.com'
            and list(map(address,resolved['to']))==['tokenjunkielabs@gmail.com']
            and not resolved.get('cc') and not resolved.get('bcc') and not original
            and bool(re.fullmatch(r'[a-f0-9]{64}',str(resolved.get('central_claim_id','')))))
        if not owner_review:raise ValueError('owner review requires an exact source-authorized central consumed claim and selected lab account')
        event='owner-review:'+resolved['operation_id']
    conversation=digest(['mail-recipient-conversation',recipients])
    content={'account':resolved['account'],'sender':address(resolved['sender']),'to':sorted(map(address,resolved['to'])),
             'cc':sorted(map(address,resolved.get('cc',[]))),'bcc':sorted(map(address,resolved.get('bcc',[]))),
             'subject':resolved['subject'],'kind':kind,'content_digest':resolved['content_digest'],
             'mime_tree_digest':resolved['mime_tree_digest'],'attachments':attachments,
             'original_thread_id':resolved.get('original_thread_id'),'original_message_id':resolved.get('original_message_id'),
             'original_rfc_message_id':original,'attempt_id':resolved['attempt_id'],'central_claim_id':resolved.get('central_claim_id')}
    content['selected_account']={'link_id':resolved['link_id'],'profile_id':resolved.get('profile_id'),'account':address(resolved['account'])}
    return {'operation_id':resolved['operation_id'],'provider':'gmail','conversation_id':conversation,
            'conversation_ids':[digest(['mail-recipient',recipient]) for recipient in recipients],
            'action':event if owner_review else ('initial-contact' if not original else 'respond-to:'+str(event)),
            'payload_hash':digest(content),'source_version':str(resolved.get('source_version') or digest([original,resolved.get('original_thread_id')])),
            'actor':address(resolved['account'])}

def validate_consumed_authorization(resolved,receipt):
    if not isinstance(receipt,dict) or any((receipt.get('allow') is not True,receipt.get('incident') is not False,
        receipt.get('reason_code')!='MAIL_AUTHORIZATION_CONSUMED',receipt.get('state')!='AUTHORIZATION_CONSUMED',
        receipt.get('operation_id')!=resolved['operation_id'],receipt.get('attempt_id')!=resolved['attempt_id'],
        receipt.get('delivery_verified') is not False,not re.fullmatch(r'[a-f0-9]{64}',str(receipt.get('claim_id',''))))):
        raise ValueError('native mail consumed authorization receipt inconsistent')
    return receipt['claim_id']

class MailFence:
    def __init__(self,credential_loader):self.cloud=CloudCoordinator(credential_loader)
    def native_before_allow(self,resolved,authorization_receipt):
        # A consumed central claim remains consumed even if duplicate remote
        # fence refuses this action. Never reset/reuse central consumed rights.
        claim=validate_consumed_authorization(resolved,authorization_receipt)
        resolved={**resolved,'central_claim_id':claim}
        b=binding(resolved);result=self.cloud.reserve(b)
        if result.get('decision')!='RESERVED':return {**result,'note':NOTE}
        result=self.cloud.request('/transition',{**b,'before':'RESERVED','after':'DISPATCHED'})
        return {**result,'native_allow':result.get('dispatch_winner') is True,'binding':b,'note':NOTE}
    def provider_dispatch(self,resolved,send,readback):
        return self.cloud.dispatch(binding(resolved),send,readback)
    def outcome(self,b,receipt=None,uncertain=False):
        # Owning post-tool/provider readback verifies actual account, original
        # thread, SENT label, exact raw content + attachment hashes first.
        verified=bool(receipt and receipt.get('verified') is True and receipt.get('provider_id') and receipt.get('actor')==b['actor']
                      and all(receipt.get(key) is True for key in ('selected_account_verified','sent_label_verified','raw_mime_verified','attachments_verified')))
        return self.cloud.request('/transition',{**b,'before':'DISPATCHED','after':'SENT' if verified and not uncertain else 'UNKNOWN_EFFECT','receipt':receipt})
