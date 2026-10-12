"""Compose into CombinedCatalog: real Slack and GitHub sends use shared fences.

Underlying service retains all incident/contact/publication controls. Reads and
credentials delegate unchanged. No provider credentials are stored here.
"""
from coordinator import digest
import urllib.parse
import re
NOTE='If this tool is misbehaving or broken, feel free to fix it on the spot.'

def github_event(value):
    value=str(value).strip()
    comment=re.search(r'issuecomment[-:]?(\d+)',value,re.I)
    if comment:return 'comment:'+comment.group(1)
    issue=re.search(r'(?:/issues/|issue:|^#)(\d+)',value,re.I)
    if issue:return 'issue:'+issue.group(1)
    return value

class CoordinatedCatalog:
    SENDS = {'slack_post_message', 'github_add_issue_comment', 'github_create_pull_request'}
    def __init__(self, catalog, coordinator):
        self.catalog, self.coordinator = catalog, coordinator
        self.services = getattr(catalog, 'services', catalog)
    def __getattr__(self, name):
        return getattr(self.catalog,name)
    def tools(self, **kwargs):
        tools = self.catalog.tools(**kwargs)
        for tool in tools:
            if tool['name'] in self.SENDS:
                tool = tool.copy()
                schema = tool['inputSchema'] = dict(tool['inputSchema'])
                schema['properties'] = dict(schema['properties'])
                schema['properties'].update({key: {'type': 'string'} for key in ('operation_id', 'source_version', 'inbound_event_id')})
                schema['required'] = sorted(set(schema.get('required', [])) | {'operation_id', 'source_version', 'inbound_event_id'})
            yield tool
        for name,description,required,properties in [
            ('collision_take','Register a scoped expiring engineering take; shared cloud authority returns compatible angles automatically.',['operation_id','owner','entity'],{'operation_id':'string','owner':'string','entity':'string','description':'string','kind':'string','ttl_seconds':'integer'}),
            ('collision_progress','Update progress or release an engineering take; never cancels outbound effects.',['operation_id','owner'],{'operation_id':'string','owner':'string','state':'string','progress':'string','ttl_seconds':'integer'}),
            ('collision_snapshot','Read shared cloud coordination and collector coverage.',[],{})]:
            schema={'type':'object','required':required,'properties':{k:{'type':v} for k,v in properties.items()}}
            if name=='collision_take':schema['properties'].update({k:{'type':'array','items':{'type':'string'}} for k in ('resources','facets')})
            yield {'name':name,'description':description+' '+NOTE,'inputSchema':schema}
    def call(self, name, arguments):
        try:
            result=self._call(name,arguments)
            return {**result,'note':NOTE} if isinstance(result,dict) else result
        except Exception as exc:
            return {'ok':False,'state':'ROAD_REPAIR_REQUIRED','error':type(exc).__name__,
                    'message':'Repair this road and continue independent work. An uncertain send retains its cloud effect fence.','note':NOTE}
    def _call(self, name, arguments):
        if name=='collision_take':return self.coordinator.take(arguments)
        if name=='collision_progress':return self.coordinator.progress(arguments)
        if name=='collision_snapshot':return self.coordinator.snapshot()
        if name not in self.SENDS:
            return self.catalog.call(name, arguments)
        for field in ('operation_id', 'source_version', 'inbound_event_id'):
            if not arguments.get(field):
                return {'ok': False, 'state': 'COORDINATION_BINDING_REQUIRED', 'field': field,
                        'message': 'Use the canonical provider inbound event and stable operation ID before dispatch.','note':NOTE}
        underlying = {k: v for k, v in arguments.items() if k not in ('source_version', 'inbound_event_id')}
        if name == 'slack_post_message':
            provider = 'slack'
            channel, root = arguments['channel_id'], arguments.get('thread_ts', 'channel')
            conversation = channel + ':' + root
            actor_result = self.services.slack('auth.test', {}, fresh=True)
            if not actor_result.get('ok') or not actor_result.get('user_id'):
                return {'ok': False, 'state': 'ACTOR_READ_FAILED'}
            actor = actor_result['user_id']
            def readback(effect, binding):
                if not effect.get('ok') or not effect.get('ts'):
                    raise ValueError('no successful provider message handle')
                result = self.services.slack('conversations.history', {'channel': channel, 'oldest': effect['ts'], 'latest': effect['ts'], 'inclusive': 'true', 'limit': 1}, fresh=True)
                rows = result.get('messages', [])
                match = next((m for m in rows if m.get('ts') == effect['ts']), None)
                # Thread reply exact readback falls back to provider thread endpoint.
                if not match and root != 'channel':
                    result = self.services.slack('conversations.replies', {'channel': channel, 'ts': root, 'oldest': effect['ts'], 'latest': effect['ts'], 'inclusive': 'true', 'limit': 2}, fresh=True)
                    match = next((m for m in result.get('messages', []) if m.get('ts') == effect['ts']), None)
                return {'verified': bool(match and match.get('user') == actor and match.get('text') == arguments['text']),
                        'actor': match.get('user') if match else None, 'provider_id': effect['ts']}
        else:
            provider = 'github'
            repo = arguments['repository']
            is_pr=name=='github_create_pull_request'
            event=github_event(arguments['inbound_event_id'])
            conversation = repo.lower() + (':solution:' + event if is_pr else ':issue:' + str(arguments['issue_number']))
            # Mirror existing claim-account routing before dispatch; ordinary
            # comments preserve the current working account route.
            from integrations.shared_equipment.github_publication import _claim_actor, _named_actor_token, _actor_readback
            named = (arguments['head'].split(':',1)[0] if ':' in arguments['head'] else repo.split('/',1)[0]) if is_pr else (_claim_actor('issue.comment.create', underlying, None) or 'tokenjunkielabs')
            actor_result = _actor_readback(_named_actor_token(named))
            actor = actor_result.get('login')
            if not actor:
                return {'ok': False, 'state': 'ACTOR_READ_FAILED'}
            if is_pr:
                branch=arguments['head'].split(':',1)[-1]
                source_repo=arguments.get('head_repo') or repo.split('/',1)[1]
                if '/' not in source_repo:source_repo=named+'/'+source_repo
                current=self.services.github('repos/'+source_repo+'/git/ref/heads/'+urllib.parse.quote(branch,safe=''),method='GET')
                if current.get('object',{}).get('sha')!=arguments['source_version']:
                    return {'ok':False,'state':'SOURCE_HEAD_MOVED','message':'Refresh exact outgoing head and retain the original task action.'}
            def readback(effect, binding):
                # Central publisher may nest its provider effect. Preserve original
                # operation receipt; never use text search to invent a send handle.
                result = effect.get('publication', {}).get('receipt', effect.get('result', effect))
                comment_id = result.get('number' if is_pr else 'id') if isinstance(result, dict) else None
                if is_pr and effect.get('pull_request'):comment_id=effect['pull_request'].get('number')
                if not comment_id:
                    raise ValueError('central publisher receipt lacks provider comment ID')
                message = self.services.github('repos/' + repo + ('/pulls/' if is_pr else '/issues/comments/') + str(comment_id), method='GET')
                sender = message.get('user', {}).get('login')
                matched=sender==actor and message.get('body')==arguments['body']
                if is_pr:matched=matched and message.get('head',{}).get('sha')==arguments['source_version'] and message.get('title')==arguments['title']
                return {'verified': matched,
                        'actor': sender, 'provider_id': str(comment_id)}
        request = {'operation_id': arguments['operation_id'], 'provider': provider, 'conversation_id': conversation,
                   'action': ('submit-solution:' if name=='github_create_pull_request' else 'respond-to:') + (github_event(arguments['inbound_event_id']) if provider=='github' else arguments['inbound_event_id']), 'payload_hash': digest(arguments.get('text',arguments.get('body'))),
                   'source_version': arguments['source_version'], 'actor': actor}
        if name=='github_add_issue_comment' and re.search(r'(?m)^\s*/claim(?:\s|$)',arguments['body']):
            request['action']='claim-issue'
        def send(_):
            if name=='github_add_issue_comment':
                from integrations.shared_equipment.github_publication import publish
                owner,repository_name=repo.split('/',1)
                return publish('issue.comment.create',{'owner':owner,'repo':repository_name,'issue_number':arguments['issue_number'],'body':arguments['body']},arguments['operation_id'],actor=named)
            return self.catalog.call(name,underlying)
        if name=='github_add_issue_comment' and hasattr(self.coordinator,'request'):
            def no_effect(effect,b):
                receipt=effect.get('publication',{})
                if receipt.get('error')!='ATTRIBUTION_REWRITE_REQUIRED' or receipt.get('allow') is not False or receipt.get('incident') is not False:return None
                owner,repository_name=repo.split('/',1)
                envelope={'operation_id':arguments['operation_id'],'operation':'issue.comment.create','args':{'owner':owner,'repo':repository_name,'issue_number':arguments['issue_number'],'body':arguments['body']}}
                return self.coordinator.request('/confirm-preflight-no-effect',{'operation_id':arguments['operation_id'],'publisher_envelope':envelope})
            return self.coordinator.dispatch(request,send,readback,no_effect_checker=no_effect)
        return self.coordinator.dispatch(request, send, readback)
