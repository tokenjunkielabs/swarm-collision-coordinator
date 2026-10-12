"""Compose into CombinedCatalog: real Slack and GitHub sends use shared fences.

Underlying service retains all incident/contact/publication controls. Reads and
credentials delegate unchanged. No provider credentials are stored here.
"""
from coordinator import digest

class CoordinatedCatalog:
    SENDS = {'slack_post_message', 'github_add_issue_comment'}
    def __init__(self, catalog, coordinator):
        self.catalog, self.coordinator = catalog, coordinator
        self.services = getattr(catalog, 'services', catalog)
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
    def call(self, name, arguments):
        if name not in self.SENDS:
            return self.catalog.call(name, arguments)
        for field in ('operation_id', 'source_version', 'inbound_event_id'):
            if not arguments.get(field):
                return {'ok': False, 'state': 'COORDINATION_BINDING_REQUIRED', 'field': field,
                        'message': 'Use the canonical provider inbound event and stable operation ID before dispatch.'}
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
            conversation = repo.lower() + ':issue:' + str(arguments['issue_number'])
            # Mirror existing claim-account routing before dispatch; ordinary
            # comments preserve the current working account route.
            from integrations.shared_equipment.github_publication import _claim_actor, _named_actor_token, _actor_readback
            named = _claim_actor('issue.comment.create', underlying, None)
            actor_result = _actor_readback(_named_actor_token(named)) if named else self.services.github('user', method='GET')
            actor = actor_result.get('login')
            if not actor:
                return {'ok': False, 'state': 'ACTOR_READ_FAILED'}
            def readback(effect, binding):
                # Central publisher may nest its provider effect. Preserve original
                # operation receipt; never use text search to invent a send handle.
                result = effect.get('publication', {}).get('receipt', effect.get('result', effect))
                comment_id = result.get('id') if isinstance(result, dict) else None
                if not comment_id:
                    raise ValueError('central publisher receipt lacks provider comment ID')
                message = self.services.github('repos/' + repo + '/issues/comments/' + str(comment_id), method='GET')
                sender = message.get('user', {}).get('login')
                return {'verified': sender == actor and message.get('body') == arguments['body'],
                        'actor': sender, 'provider_id': str(comment_id)}
        request = {'operation_id': arguments['operation_id'], 'provider': provider, 'conversation_id': conversation,
                   'action': 'respond-to:' + arguments['inbound_event_id'], 'payload_hash': digest(underlying),
                   'source_version': arguments['source_version'], 'actor': actor}
        return self.coordinator.dispatch(request, lambda _: self.catalog.call(name, underlying), readback)
