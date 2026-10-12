"""Use existing Cloudflare MCP OAuth custody, not a REST API-token assumption."""
import base64
import argparse
import json
import sys
import subprocess
import urllib.error
import urllib.parse
import urllib.request
sys.path.insert(0,'C:/Users/lucys/Documents/Codex/2026-08-25/yo/work/commons-spark-link')
from integrations.shared_equipment.credential_transfer import CredentialSources

def parse(raw):
    try:return json.loads(raw)
    except ValueError:
        for line in raw.splitlines():
            if line.startswith('data: '):return json.loads(line[6:])
        raise ValueError('MCP response unavailable')

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--binding',default='SLACK_TOKEN')
    parser.add_argument('--credential-ref',default='slack/bot')
    args=parser.parse_args()
    f=CredentialSources()
    current=subprocess.run(['node','reviewed_native_custody.mjs','--private-custody-pipe'],capture_output=True,timeout=90)
    if current.returncode:
        print(json.dumps({'success':False,'native_error':current.stderr.decode().strip()}));sys.exit(1)
    card=json.loads(current.stdout)
    token=card['token_response']['access_token'];session=None
    def call(method,params,ident=1):
        headers={'Authorization':'Bearer '+token,'Content-Type':'application/json','Accept':'application/json, text/event-stream','User-Agent':'TokenJunkieLabs-Collision-Coordinator'}
        if session:headers['Mcp-Session-Id']=session
        r=urllib.request.Request(card['url'],data=json.dumps({'jsonrpc':'2.0','id':ident,'method':method,'params':params}).encode(),headers=headers)
        with urllib.request.urlopen(r,timeout=45) as response:return parse(response.read().decode()),response.headers.get('Mcp-Session-Id')
    try:
        try:response,session=call('initialize',{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'TokenJunkieLabs-Coordination','version':'1'}})
        except urllib.error.HTTPError as exc:
            if exc.code not in (401,403):raise
            issuer=card['issuer'].rstrip('/')
            with urllib.request.urlopen(issuer+'/.well-known/oauth-authorization-server',timeout=20) as r:metadata=json.load(r)
            form=urllib.parse.urlencode({'grant_type':'refresh_token','refresh_token':card['token_response']['refresh_token'],'client_id':card['client_id']}).encode()
            r=urllib.request.Request(metadata['token_endpoint'],data=form,headers={'Content-Type':'application/x-www-form-urlencoded'})
            with urllib.request.urlopen(r,timeout=25) as result:grant=json.load(result)
            token=grant['access_token']
            response,session=call('initialize',{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'TokenJunkieLabs-Coordination','version':'1'}})
        tools,_=call('tools/list',{},2)
        names=[t['name'] for t in tools.get('result',{}).get('tools',[])]
        target=next((n for n in names if n=='execute' or n.endswith('_execute')),None)
        if not target:raise ValueError('Cloudflare execute capability missing')
        value=f.read(args.credential_ref)
        code="async () => {return cloudflare.request({method:'PUT',path:'/accounts/ce19b3a08eecfce3843070ba868afa3e/workers/scripts/swarm-collision-coordinator/secrets',body:{name:"+json.dumps(args.binding)+",type:'secret_text',text:"+json.dumps(value)+"}});}"
        result,_=call('tools/call',{'name':target,'arguments':{'account_id':'ce19b3a08eecfce3843070ba868afa3e','code':code}},3)
        body=result.get('result',{})
        print(json.dumps({'secret_binding':args.binding,'mcp_error':bool(body.get('isError')),'receipt':body.get('content',[])}))
    except Exception as exc:
        print(json.dumps({'secret_binding':'SLACK_TOKEN','success':False,'error':type(exc).__name__,'http_status':getattr(exc,'code',None)}));sys.exit(1)
