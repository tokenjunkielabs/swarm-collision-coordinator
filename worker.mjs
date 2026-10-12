import { DurableObject } from 'cloudflare:workers';
export const NOTE = 'If this tool is misbehaving or broken, feel free to fix it on the spot.';
const VERSION = '2026-10-12.6';
const facets = {identity:['auth','authentication','authorization','login','log in','signin','sign in','signup','sign up','oauth','session','credential','password','sso','jwt','permission'],payments:['payment','billing','checkout','invoice','stripe','charge'],interface:['ui','frontend','screen','layout','design','accessibility'],storage:['database','schema','sql','storage','persistence','migration'],performance:['performance','latency','speed','optimization','cache','caching'],documentation:['docs','documentation','document','readme','guide'],outreach:['email','reply','contact','outreach','send','proposal']};
const canon = x => String(x || '').trim().toLowerCase().replace(/^https?:\/\/(www\.)?/, '').replace(/\/$/, '').replace(/\.git$/, '');
const json = (value,status=200) => Response.json({...value,note:NOTE,version:VERSION},{status});
const sha = async value => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(value))))).map(b=>b.toString(16).padStart(2,'0')).join('');
const canonicalJSON=value=>JSON.stringify(value,(_,v)=>v && typeof v==='object' && !Array.isArray(v)?Object.fromEntries(Object.keys(v).sort().map(k=>[k,v[k]])):v);
const canonicalSha=async value=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(canonicalJSON(value))))).map(b=>b.toString(16).padStart(2,'0')).join('');
function work(r) {
  const entity=canon(r.entity); if(!entity) throw Error('canonical entity required');
  const text=String(r.description || '').toLowerCase().replace(/[_-]/g,' '), found=new Set(r.facets || []);
  for(const [f,words] of Object.entries(facets)) if(words.some(w=>new RegExp('\\b'+w+'(?:s|ed|ing)?\\b').test(text))) found.add(f);
  const kind=r.kind || (found.has('documentation')?'documentation':found.has('interface')?'interface':'engineering');
  return {entity,description:String(r.description || ''),kind,resources:[...new Set((r.resources || []).map(canon))].sort(),facets:[...found].sort()};
}
function conflict(a,b) {
  if(a.entity!==b.entity || a.kind==='read' || b.kind==='read') return null;
  const paths=a.resources.some(x=>b.resources.some(y=>x===y || x.startsWith(y+'/') || y.startsWith(x+'/')));
  if(a.kind!==b.kind && !paths) return null;
  const common=a.facets.filter(x=>b.facets.includes(x));
  if(paths || common.length) return {reason:paths?'shared resource':'shared contribution facet',facets:common};
  if(a.resources.length && b.resources.length || a.facets.length && b.facets.length) return null;
  return {reason:'scope is broad; choose a concrete independent contribution',ambiguous:true,facets:[]};
}
export class Coordination extends DurableObject {
  constructor(ctx,env) {
    super(ctx,env); this.ctx=ctx;this.env=env;this.sql=ctx.storage.sql;
    this.sql.exec(`CREATE TABLE IF NOT EXISTS leases(id TEXT PRIMARY KEY,owner TEXT,scope TEXT,until REAL,state TEXT); CREATE TABLE IF NOT EXISTS sends(id TEXT PRIMARY KEY,fence TEXT UNIQUE,binding TEXT,state TEXT,receipt TEXT,updated REAL); CREATE TABLE IF NOT EXISTS send_fences(fence TEXT PRIMARY KEY,operation_id TEXT); CREATE TABLE IF NOT EXISTS events(n INTEGER PRIMARY KEY,at REAL,type TEXT,object TEXT,data TEXT); CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,data TEXT); CREATE TABLE IF NOT EXISTS observations(id TEXT PRIMARY KEY,source TEXT,data TEXT);`);
    this.sql.exec('CREATE INDEX IF NOT EXISTS lease_activity ON leases(state,until); CREATE INDEX IF NOT EXISTS send_reconciliation ON sends(state,updated);');
  }
  rows(sql,...args){return [...this.sql.exec(sql,...args)];}
  event(type,id,data){this.sql.exec('INSERT INTO events(at,type,object,data) VALUES(?,?,?,?)',Date.now(),type,id,JSON.stringify(data));}
  take(r) {
    const s=work(r),now=Date.now(),ttl=Math.max(30,Math.min(1800,Number(r.ttl_seconds || 300)))*1000;
    const aliases=this.state('aliases');s.entity=aliases[s.entity] || s.entity;
    const enrichment=this.state('facet_terms'),lower=s.description.toLowerCase();
    for(const[facet,terms]of Object.entries(enrichment))if(Array.isArray(terms) && terms.some(term=>lower.includes(String(term).toLowerCase())))s.facets.push(facet);
    s.facets=[...new Set(s.facets)].sort();
    if(!r.operation_id || !r.owner) throw Error('operation_id and owner required');
    return this.ctx.storage.transactionSync(()=>{
      const old=this.rows('SELECT * FROM leases WHERE id=?',r.operation_id)[0];
      if(old && (old.owner!==r.owner || old.scope!==JSON.stringify(s))) throw Error('operation ID bound to different work');
      const conflicts=[];
      for(const l of this.rows("SELECT * FROM leases WHERE state='ACTIVE' AND until>? AND id!=?",now,r.operation_id)){
        const other=JSON.parse(l.scope);other.entity=aliases[other.entity] || other.entity;
        const c=conflict(s,other);if(c) conflicts.push({operation_id:l.id,owner:l.owner,until:l.until,...c});
      }
      const definite=conflicts.filter(c=>!c.ambiguous);
      if(definite.length) return {decision:'CHOOSE_DIFFERENT_ANGLE',conflicts:definite,send_authorized:false,message:'Please choose a different angle of contribution or engineering for this claim, or choose another.',alternatives:Object.keys(facets).filter(f=>f!=='outreach' && !definite.some(c=>c.facets.includes(f)))};
      this.sql.exec('INSERT INTO leases VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET until=excluded.until,state=excluded.state',r.operation_id,r.owner,JSON.stringify(s),now+ttl,'ACTIVE');
      this.event('take',r.operation_id,s);return {decision:conflicts.length?'TAKEN_WITH_SCOPE_ADVICE':'TAKEN',operation_id:r.operation_id,until:now+ttl,send_authorized:false,...(conflicts.length?{scope_advice:conflicts,message:'Continue a concrete independent angle; broad prior wording does not reserve the whole project.',alternatives:Object.keys(facets).filter(f=>f!=='outreach')}: {})};
    });
  }
  progress(r) {
    const row=this.rows('SELECT * FROM leases WHERE id=?',r.operation_id)[0];
    if(!row || row.owner!==r.owner) throw Error('unknown lease or owner mismatch');
    const state=r.state || 'ACTIVE';if(!['ACTIVE','DONE','RELEASED'].includes(state)) throw Error('invalid lease state');
    if(state==='ACTIVE' && row.until<=Date.now()) return {decision:'RETAKE_REQUIRED',alternatives:Object.keys(facets).filter(f=>f!=='outreach')};
    const until=Date.now()+Math.max(30,Math.min(1800,Number(r.ttl_seconds || 300)))*1000;
    this.sql.exec('UPDATE leases SET until=?,state=? WHERE id=?',until,state,r.operation_id);this.event('progress',r.operation_id,{state,progress:r.progress || ''});return {decision:state,until};
  }
  async reserve(r) {
    for(const k of ['operation_id','provider','conversation_id','action','payload_hash','source_version','actor']) if(!r[k]) throw Error('missing outbound binding: '+k);
    const binding=JSON.stringify(Object.fromEntries(['provider','conversation_id','action','payload_hash','source_version','actor'].map(k=>[k,r[k]])));
    const fence=await sha([canon(r.provider),String(r.conversation_id),String(r.action)]);
    const allFences=[...new Set([fence,...await Promise.all((r.conversation_ids || []).map(id=>sha([canon(r.provider),String(id),String(r.action)])))])];
    return this.ctx.storage.transactionSync(()=>{
      // A stale pre-dispatch reservation has no possible provider effect. CAS
      // cancels its original dispatch right before allowing a new operation.
      for(const expired of this.rows("SELECT * FROM sends WHERE state='RESERVED' AND updated<?",Date.now()-120000)){
        this.sql.exec("UPDATE sends SET state='CANCELLED_BEFORE_DISPATCH',fence=? WHERE id=? AND state='RESERVED'",expired.fence+':cancelled:'+expired.id,expired.id);
        this.sql.exec('DELETE FROM send_fences WHERE operation_id=?',expired.id);
        this.event('CANCELLED_BEFORE_DISPATCH',expired.id,{});
      }
      let prior=this.rows('SELECT * FROM sends WHERE fence=? OR id=?',fence,r.operation_id)[0];
      for(const key of allFences){if(prior)break;const shared=this.rows('SELECT operation_id FROM send_fences WHERE fence=?',key)[0];if(shared)prior=this.rows('SELECT * FROM sends WHERE id=?',shared.operation_id)[0];}
      if(prior) return {decision:prior.id===r.operation_id && prior.binding===binding?'ALREADY_RESERVED':'DO_NOT_SEND',operation_id:prior.id,state:prior.state,send_authorized:false,message:'Existing outbound effect is being reconciled; continue other work.'};
      this.sql.exec('INSERT INTO sends VALUES(?,?,?,?,?,?)',r.operation_id,fence,binding,'RESERVED',null,Date.now());this.event('reserved',r.operation_id,JSON.parse(binding));
      for(const key of allFences)this.sql.exec('INSERT INTO send_fences VALUES(?,?)',key,r.operation_id);
      return {decision:'RESERVED',operation_id:r.operation_id,send_authorized:false};
    });
  }
  transition(r) {
    // Compare-and-swap dispatch winner; no timeout release of provider effects.
    const allowed={RESERVED:['DISPATCHED'],DISPATCHED:['UNKNOWN_EFFECT','SENT'],UNKNOWN_EFFECT:['SENT']};
    if(!allowed[r.before]?.includes(r.after)) throw Error('invalid outbound transition');
    if(r.after==='SENT' && (!r.receipt?.verified || !r.receipt?.provider_id)) throw Error('exact provider receipt required');
    return this.ctx.storage.transactionSync(()=>{
      const row=this.rows('SELECT * FROM sends WHERE id=?',r.operation_id)[0];
      if(!row || row.state!==r.before) return {decision:'DO_NOT_SEND',state:row?.state || 'UNKNOWN_OPERATION'};
      const binding=JSON.parse(row.binding);
      if(['provider','conversation_id','action','payload_hash','source_version','actor'].some(k=>r[k]!==binding[k])) throw Error('conversation/action/payload/source/actor fence changed');
      if(r.after==='SENT' && r.receipt.actor!==binding.actor) throw Error('readback actor mismatch');
      this.sql.exec('UPDATE sends SET state=?,receipt=?,updated=? WHERE id=?',r.after,JSON.stringify(r.receipt || null),Date.now(),r.operation_id);this.event(r.after,r.operation_id,r.receipt || {});
      return {decision:r.after,dispatch_winner:r.after==='DISPATCHED',operation_id:r.operation_id};
    });
  }
  async fetch(request) {
    try{
      const path=new URL(request.url).pathname;
      if(path==='/health') return json({ok:true,storage:'cloud-sql-durable-object',pc_required:false});
      if(path==='/snapshot') return json({now:Date.now(),leases:this.rows('SELECT * FROM leases').map(l=>({...l,scope:JSON.parse(l.scope),effective_state:l.state==='ACTIVE' && l.until<=Date.now()?'STALE':l.state})),outbound:this.rows('SELECT * FROM sends').map(s=>({...s,binding:JSON.parse(s.binding),receipt:s.receipt?JSON.parse(s.receipt):null})),sources:this.rows('SELECT * FROM sources')});
      const r=await request.json();let result;
      if(path==='/take') result=this.take(r);
      else if(path==='/progress') result=this.progress(r);
      else if(path==='/reserve') result=await this.reserve(r);
      else if(path==='/transition') result=this.transition(r);
      else if(path==='/confirm-preflight-no-effect') result=await this.confirmPreflightNoEffect(r);
      else if(path==='/collect') {result=await this.collect();await this.reconcile();
        if(!await this.ctx.storage.getAlarm())await this.ctx.storage.setAlarm(Date.now()+60000);
        this.save('collector:clock',{...this.state('collector:clock'),last_manual_tick:Date.now(),next_tick:await this.ctx.storage.getAlarm(),phase:'scheduled'});}
      else if(path==='/observe'){
        if(!r.id || !r.source) throw Error('observation ID/source required');
        this.sql.exec('INSERT INTO observations VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',r.id,r.source,JSON.stringify(r));result={decision:'OBSERVED'};
        if(r.claim)result={...result,claim:this.take({...r.claim,operation_id:r.id,owner:r.claim.owner || r.owner})};
      } else if(path==='/alias'){
        const aliases=this.state('aliases'),entity=canon(r.entity);if(!entity || !Array.isArray(r.aliases))throw Error('canonical entity and aliases required');
        for(const name of r.aliases)aliases[canon(name)]=entity;this.save('aliases',aliases);
        if(r.facet_terms){const enrichment=this.state('facet_terms');for(const[facet,terms]of Object.entries(r.facet_terms))if(Array.isArray(terms))enrichment[facet]=[...new Set([...(enrichment[facet] || []),...terms.map(String)])];this.save('facet_terms',enrichment);}
        this.event('aliases',entity,r.aliases);result={decision:'ALIASES_UPDATED',entity,aliases:r.aliases};
      } else return json({error:'unknown endpoint'},404);
      return json(result);
    }catch(e){return json({error:e.message,decision:'REPAIR_REQUEST',alternatives:['choose another independent contribution','continue read-only source research']},400);}
  }
  state(id){return JSON.parse(this.rows('SELECT data FROM sources WHERE id=?',id)[0]?.data || '{}');}
  async confirmPreflightNoEffect(r){
    const row=this.rows('SELECT * FROM sends WHERE id=?',r.operation_id)[0],input=r.publisher_envelope;
    if(!row || !['DISPATCHED','UNKNOWN_EFFECT'].includes(row.state) || !this.env.PUBLICATION_JOURNAL || !input || input.operation_id!==row.id || input.operation!=='issue.comment.create')return {decision:'DO_NOT_SEND',message:'No authoritative pre-provider rejection receipt.'};
    const b=JSON.parse(row.binding),actorId={tokenjunkielabs:311286379,woahwhattheheck:293286387}[b.actor],a=input.args;
    if(!actorId || !a || b.provider!=='github' || b.conversation_id!==String(a.owner+'/'+a.repo).toLowerCase()+':issue:'+a.issue_number || await sha(a.body)!==b.payload_hash)return {decision:'DO_NOT_SEND'};
    // Read the existing authoritative publisher row only. Never replay its
    // publication endpoint, reset consumed claims, or mutate its journal.
    const original=await this.env.PUBLICATION_JOURNAL.prepare('SELECT digest,state,result FROM ops WHERE op_id=?').bind(row.id).first();
    const expected=await canonicalSha({version:'tjlabs-publication-2026-09-19.1',path:'/v1/publish',input,actor_id:actorId});
    if(!original || original.digest!==expected || original.state!=='REWRITE_REQUIRED')return {decision:'DO_NOT_SEND'};
    const proof=JSON.parse(original.result || '{}');
    if(proof.allow!==false || proof.incident!==false || proof.operation_id!==row.id || proof.error!=='ATTRIBUTION_REWRITE_REQUIRED')return {decision:'DO_NOT_SEND'};
    return this.ctx.storage.transactionSync(()=>{
      const current=this.rows('SELECT * FROM sends WHERE id=?',row.id)[0];
      if(!current || current.state!==row.state)return {decision:'DO_NOT_SEND'};
      const evidence={provider:'central-publisher',state:original.state,error:proof.error,operation_id:row.id,digest:original.digest,no_provider_effect:true};
      this.sql.exec("UPDATE sends SET state='NO_EFFECT_CONFIRMED',fence=?,receipt=?,updated=? WHERE id=?",row.fence+':no-effect:'+row.id,JSON.stringify(evidence),Date.now(),row.id);
      this.sql.exec('DELETE FROM send_fences WHERE operation_id=?',row.id);this.event('NO_EFFECT_CONFIRMED',row.id,evidence);
      return {decision:'NO_EFFECT_CONFIRMED',message:'Repair the draft under a new stable operation ID and continue the authorized action.'};
    });
  }
  save(id,value){this.sql.exec('INSERT INTO sources VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',id,JSON.stringify(value));}
  async slack(method,args,id){
    const state=this.state(id);if(state.retry_at>Date.now()) return null;
    try{
      const url=new URL('https://slack.com/api/'+method);for(const[k,v]of Object.entries(args))url.searchParams.set(k,String(v));
      const response=await fetch(url,{headers:{Authorization:'Bearer '+this.env.SLACK_TOKEN},signal:AbortSignal.timeout(15000)});
      const body=await response.json();if(!body.ok){this.save(id,{...state,error:body.error || 'read_failed',retry_at:Date.now()+Number(response.headers.get('Retry-After') || 60)*1000,complete:false});return null;}return body;
    }catch(e){this.save(id,{...state,error:'read_unavailable',retry_at:Date.now()+60000,complete:false});return null;}
  }
  observe(channel,m){
    const text=m.text || '',id='slack:'+channel+':'+m.ts,candidate=/\b(taking|claimed|working on|claim|take)\b/i.test(text);
    this.sql.exec('INSERT INTO observations VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',id,'slack:'+channel,JSON.stringify({ts:m.ts,user:m.user,thread_ts:m.thread_ts,claim_candidate:candidate,text}));
    const marker=text.match(/<collision_claim>([\s\S]*?)<\/collision_claim>/);
    if(marker){try{
      const claim=JSON.parse(marker[1]),operation_id=claim.operation_id || id,owner=claim.owner || m.user || 'unknown';
      const timestamp=Number(m.edited?.ts || m.ts)*1000,ttl=Math.max(30,Math.min(1800,Number(claim.ttl_seconds || 300)))*1000;
      if(['DONE','RELEASED'].includes(String(claim.state || '').toUpperCase()))this.progress({operation_id,owner,state:String(claim.state).toUpperCase(),progress:'Explicit source lifecycle '+id});
      else if(Number.isFinite(timestamp) && Date.now()<timestamp+ttl)this.take({...claim,operation_id,owner,ttl_seconds:Math.max(30,(timestamp+ttl-Date.now())/1000)});
    }catch{}return;}
    if(candidate && Date.now()-Number(m.ts)*1000<1800000){
      for(const match of text.matchAll(/https?:\/\/github\.com\/([\w.-]+\/[\w.-]+)(?:\/(issues|pull)\/(\d+))?/g)){
        try{this.take({operation_id:id+':'+match[1],owner:m.user || 'unknown',entity:'github.com/'+match[1],description:text,resources:match[2]?[match[2]+'/'+match[3]]:[],ttl_seconds:Math.max(30,(Number(m.ts)*1000+1800000-Date.now())/1000)});}catch{}
      }
    }
  }
  async collect(){
    if(!this.env.SLACK_TOKEN){this.save('slack:channels',{error:'shared_slack_binding_unconfigured',complete:false});return {decision:'COLLECTOR_NOT_CONFIGURED'};}
    await this.ensureSocket();
    let catalog=this.state('slack:channels'),calls=0;
    const list=await this.slack('conversations.list',{limit:100,cursor:catalog.cursor || '',exclude_archived:true},'slack:channels');calls++;
    if(list){catalog={...catalog,channels:[...new Set([...(catalog.channels || []),...(list.channels || []).map(c=>c.id)])].sort(),cursor:list.response_metadata?.next_cursor || '',complete:!list.response_metadata?.next_cursor,error:null};this.save('slack:channels',catalog);}
    const channels=catalog.channels || [];if(!channels.length)return {requests:calls,channels:0};
    const index=catalog.index || 0,channel=channels[index%channels.length],id='slack:'+channel;
    let state=this.state(id),oldest=state.oldest || String(Date.now()/1000-86400);
    state.bootstrap_latest ||= oldest;
    const history=await this.slack('conversations.history',{channel,limit:100,oldest,cursor:state.cursor || '',inclusive:false},id);calls++;
    if(history){let watermark=Number(state.watermark || oldest),threads=state.threads || {};
      for(const m of history.messages || []){this.observe(channel,m);watermark=Math.max(watermark,Number(m.ts));if(m.reply_count)threads[m.ts] ||= {cursor:'',oldest:'0'};}
      const cursor=history.response_metadata?.next_cursor || '';state={...state,cursor,oldest:cursor?oldest:String(watermark),watermark,threads,error:null,complete:!cursor};this.save(id,state);
    }
    // One retained historical page per channel visit discovers older thread
    // roots once. Completed bootstraps are never restarted or fully rescanned.
    if(!state.bootstrap_complete && calls<6){
      const page=await this.slack('conversations.history',{channel,limit:100,oldest:'0',latest:state.bootstrap_latest,cursor:state.bootstrap_cursor || '',inclusive:false},id+':bootstrap');calls++;
      if(page){state.threads ||= {};for(const m of page.messages || []){this.observe(channel,m);if(m.reply_count)state.threads[m.ts] ||= {cursor:'',oldest:'0'};}
        state.bootstrap_cursor=page.response_metadata?.next_cursor || '';state.bootstrap_complete=!state.bootstrap_cursor;state.bootstrap_pages=(state.bootstrap_pages || 0)+1;this.save(id,state);}
    }
    const threads=Object.entries(state.threads || {}),start=state.thread_index || 0;let visited=0;
    for(let n=0;n<threads.length && calls<6;n++){
      const[root,t]=threads[(start+n)%threads.length],result=await this.slack('conversations.replies',{channel,ts:root,limit:100,oldest:t.oldest,cursor:t.cursor},id+':thread:'+root);calls++;visited++;
      if(result){for(const m of result.messages || [])this.observe(channel,m);t.cursor=result.response_metadata?.next_cursor || '';if(!t.cursor && result.messages?.length)t.oldest=String(Math.max(...result.messages.map(m=>Number(m.ts))));}
    }
    if(threads.length){state.thread_index=(start+visited)%threads.length;this.save(id,state);}
    catalog.index=index+1;this.save('slack:channels',catalog);return {decision:'COLLECTED',requests:calls,channels:channels.length,visited:channel};
  }
  async ensureSocket(){
    // Independent read-only source receiver. It can ACK Slack envelopes only;
    // it contains no chat.postMessage, command transport or publisher replay.
    if(this.socket?.readyState===1 || this.connecting || !this.env.SLACK_APP_TOKEN)return;
    const prior=this.state('slack:events');if(prior.retry_at>Date.now())return;
    this.connecting=true;
    try{
      const response=await fetch('https://slack.com/api/apps.connections.open',{method:'POST',headers:{Authorization:'Bearer '+this.env.SLACK_APP_TOKEN,'Content-Type':'application/x-www-form-urlencoded'},body:'',signal:AbortSignal.timeout(15000)});
      const result=await response.json();if(!result.ok || !result.url){this.save('slack:events',{phase:'unavailable',error:result.error || 'socket_url_missing',retry_at:Date.now()+60000});return;}
      const connection=await fetch(result.url.replace(/^wss:/,'https:'),{headers:{Upgrade:'websocket'}});
      if(!connection.webSocket)throw Error('socket_upgrade_unavailable');
      const socket=this.socket=connection.webSocket;socket.accept();
      this.save('slack:events',{phase:'connected',connected_at:Date.now(),received:prior.received || 0,read_only:true});
      socket.addEventListener('message',event=>{
        try{
          const envelope=JSON.parse(event.data);
          if(envelope.envelope_id)socket.send(JSON.stringify({envelope_id:envelope.envelope_id}));
          const payload=envelope.payload?.event;
          const state=this.state('slack:events');this.save('slack:events',{...state,last_envelope_at:Date.now(),received:(state.received || 0)+1,last_event_type:payload?.type || envelope.type,last_envelope_type:envelope.type,...(envelope.type==='disconnect'?{disconnect_reason:envelope.reason || 'provider_disconnect'}:{})});
          if(envelope.type==='disconnect'){this.save('slack:events',{...this.state('slack:events'),retry_at:Date.now()+(envelope.reason==='too_many_websockets'?300000:60000)});socket.close(1000,'Read-only receiver reconnect');return;}
          if(payload?.type==='message' && payload.channel){
            const message=payload.message || payload;if(message.ts)this.observe(payload.channel,message);
            const key='slack:'+payload.channel,channel=this.state(key),root=message.thread_ts;
            if(root){channel.threads ||= {};channel.threads[root] ||= {cursor:'',oldest:'0'};this.save(key,channel);}
          }
          if(payload?.type==='channel_created' && payload.channel?.id){const catalog=this.state('slack:channels');catalog.channels=[...new Set([...(catalog.channels || []),payload.channel.id])];this.save('slack:channels',catalog);}
        }catch{this.save('slack:events',{...this.state('slack:events'),parse_error_at:Date.now()});}
      });
      socket.addEventListener('close',()=>{this.socket=null;this.save('slack:events',{...this.state('slack:events'),phase:'disconnected',disconnected_at:Date.now()});});
      socket.addEventListener('error',()=>{this.socket=null;this.save('slack:events',{...this.state('slack:events'),phase:'unavailable',retry_at:Date.now()+60000});});
    }catch{this.save('slack:events',{phase:'unavailable',error:'socket_connection_unavailable',retry_at:Date.now()+60000});}
    finally{this.connecting=false;}
  }
  async alarm(){
    try{const result=await this.collect();await this.reconcile();const state=this.state('collector:clock');
      this.save('collector:clock',{...state,last_alarm_tick:Date.now(),alarm_ticks:(state.alarm_ticks || 0)+1,phase:'collected',requests:result.requests});
    }catch{this.save('collector:clock',{...this.state('collector:clock'),last_alarm_tick:Date.now(),phase:'read_unavailable'});}
    finally{await this.ctx.storage.setAlarm(Date.now()+60000);this.save('collector:clock',{...this.state('collector:clock'),next_tick:await this.ctx.storage.getAlarm()});}
  }
  async reconcile(){
    // Read-only reconciliation of exact handles only, never blind resend.
    const rows=this.rows("SELECT * FROM sends WHERE state IN ('DISPATCHED','UNKNOWN_EFFECT') ORDER BY updated LIMIT 4");
    for(const row of rows){const b=JSON.parse(row.binding),receipt=JSON.parse(row.receipt || 'null');
      if(b.provider==='slack' && receipt?.provider_id && this.env.SLACK_TOKEN){
        const[channel,root]=b.conversation_id.split(':'),m=await this.slack('conversations.replies',{channel,ts:root,oldest:receipt.provider_id,latest:receipt.provider_id,inclusive:true,limit:2},'reconcile:'+row.id);
        const found=m?.messages?.find(x=>x.ts===receipt.provider_id && x.user===b.actor);
        if(found && await sha(found.text)===b.payload_hash)this.transition({operation_id:row.id,before:row.state,after:'SENT',...b,receipt:{verified:true,actor:b.actor,provider_id:receipt.provider_id}});
      }
      if(b.provider==='github' && receipt?.provider_id && this.env.GITHUB_TOKEN){
        const repo=b.conversation_id.split(':issue:')[0];
        try{
          const response=await fetch('https://api.github.com/repos/'+repo+'/issues/comments/'+receipt.provider_id,{headers:{Authorization:'Bearer '+this.env.GITHUB_TOKEN,'User-Agent':'TokenJunkieLabs-Collision-Coordinator'},signal:AbortSignal.timeout(10000)});
          if(response.ok){const m=await response.json();if(m.user?.login===b.actor && await sha(m.body)===b.payload_hash)this.transition({operation_id:row.id,before:row.state,after:'SENT',...b,receipt:{verified:true,actor:b.actor,provider_id:String(m.id)}});}
        }catch{}
      }
      this.sql.exec('UPDATE sends SET updated=? WHERE id=?',Date.now(),row.id);
    }
  }
}
const authCache=new Map();
async function authenticated(request){
  const token=request.headers.get('Authorization')?.replace(/^Bearer /,'');if(!token)return false;
  const fingerprint=await sha(token),cached=authCache.get(fingerprint);if(cached && cached>Date.now())return true;
  const response=await fetch('https://api.github.com/user',{headers:{Authorization:'Bearer '+token,'User-Agent':'TokenJunkieLabs-Collision-Coordinator','Accept':'application/vnd.github+json'},signal:AbortSignal.timeout(10000)});
  if(!response.ok)return false;const user=await response.json();
  if(![311286379,293286387].includes(user.id))return false;
  if(authCache.size>64)authCache.clear();authCache.set(fingerprint,Date.now()+300000);return true;
}
export default {
  async fetch(request,env){
    if(new URL(request.url).pathname==='/health')return json({ok:true,storage:'cloud-sql-durable-object',pc_required:false});
    try{if(!await authenticated(request))return json({error:'use existing shared github credential; every peer may retrieve it directly'},401);
      const stub=env.COORDINATION.get(env.COORDINATION.idFromName('shared'));
      if(new URL(request.url).pathname==='/mcp'){
        const rpc=await request.json(),id=rpc.id;
        const reply=result=>json({jsonrpc:'2.0',id,result});
        if(rpc.method==='initialize')return reply({protocolVersion:'2025-03-26',capabilities:{tools:{}},serverInfo:{name:'TokenJunkieLabs-Collision-Coordinator',version:VERSION},instructions:NOTE});
        if(rpc.method==='notifications/initialized')return new Response(null,{status:202,headers:{'X-Coordination-Repair-Note':NOTE}});
        const schemas=[
          {name:'collision_take',description:'Register a scoped expiring work take; fast alternatives keep independent work moving. '+NOTE,inputSchema:{type:'object',required:['operation_id','owner','entity'],properties:{operation_id:{type:'string'},owner:{type:'string'},entity:{type:'string'},description:{type:'string'},kind:{type:'string'},resources:{type:'array',items:{type:'string'}},facets:{type:'array',items:{type:'string'}},ttl_seconds:{type:'integer'}}}},
          {name:'collision_progress',description:'Heartbeat, complete or release planning scope; never cancel provider effects. '+NOTE,inputSchema:{type:'object',required:['operation_id','owner'],properties:{operation_id:{type:'string'},owner:{type:'string'},state:{type:'string'},progress:{type:'string'},ttl_seconds:{type:'integer'}}}},
          {name:'collision_snapshot',description:'Read shared scopes, durable effect states and source coverage. '+NOTE,inputSchema:{type:'object',properties:{}}}
        ];
        if(rpc.method==='tools/list')return reply({tools:schemas});
        if(rpc.method==='tools/call'){
          const routes={collision_take:'/take',collision_progress:'/progress',collision_snapshot:'/snapshot'},route=routes[rpc.params?.name];
          if(!route)return reply({isError:true,content:[{type:'text',text:'Unknown coordination tool. '+NOTE}]});
          const response=await stub.fetch('https://internal'+route,route==='/snapshot'?{}:{method:'POST',body:JSON.stringify(rpc.params.arguments || {})});
          const value=await response.json();return reply({isError:response.status>=400,structuredContent:value,content:[{type:'text',text:JSON.stringify(value)}]});
        }
        return json({jsonrpc:'2.0',id,error:{code:-32601,message:'Unsupported method. '+NOTE}},400);
      }
      return await stub.fetch(request);
    }catch(e){return json({error:'service unavailable; continue independent work and repair road'},503);}
  },
  async scheduled(event,env,ctx){ctx.waitUntil(env.COORDINATION.get(env.COORDINATION.idFromName('shared')).fetch('https://internal/collect',{method:'POST',body:'{}'}));}
};
