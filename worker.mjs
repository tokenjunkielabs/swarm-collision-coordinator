import { DurableObject } from 'cloudflare:workers';
export const NOTE = 'If this tool is misbehaving or broken, feel free to fix it on the spot.';
const VERSION = '2026-10-12.1';
const facets = {identity:['auth','authentication','login','signin','oauth','session'],payments:['payment','billing','checkout','invoice','stripe'],interface:['ui','frontend','screen','layout','design'],storage:['database','schema','sql','storage','persistence'],performance:['performance','latency','speed','optimization','cache'],documentation:['docs','documentation','readme','guide'],outreach:['email','reply','contact','outreach','send','proposal']};
const canon = x => String(x || '').trim().toLowerCase().replace(/^https?:\/\/(www\.)?/, '').replace(/\/$/, '').replace(/\.git$/, '');
const json = (value,status=200) => Response.json({...value,note:NOTE,version:VERSION},{status});
const sha = async value => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(value))))).map(b=>b.toString(16).padStart(2,'0')).join('');
function work(r) {
  const entity=canon(r.entity); if(!entity) throw Error('canonical entity required');
  const text=String(r.description || '').toLowerCase(), found=new Set(r.facets || []);
  for(const [f,words] of Object.entries(facets)) if(words.some(w=>new RegExp('\\b'+w+'\\b').test(text))) found.add(f);
  return {entity,description:String(r.description || ''),kind:r.kind || 'engineering',resources:[...new Set((r.resources || []).map(canon))].sort(),facets:[...found].sort()};
}
function conflict(a,b) {
  if(a.entity!==b.entity || a.kind==='read' || b.kind==='read') return null;
  const paths=a.resources.some(x=>b.resources.some(y=>x===y || x.startsWith(y+'/') || y.startsWith(x+'/')));
  const common=a.facets.filter(x=>b.facets.includes(x));
  if(paths || common.length) return {reason:paths?'shared resource':'shared contribution facet',facets:common};
  if(a.resources.length && b.resources.length || a.facets.length && b.facets.length) return null;
  return {reason:'scope is broad; choose a concrete independent contribution',ambiguous:true,facets:[]};
}
export class Coordination extends DurableObject {
  constructor(ctx,env) {
    super(ctx,env); this.ctx=ctx;this.env=env;this.sql=ctx.storage.sql;
    this.sql.exec(`CREATE TABLE IF NOT EXISTS leases(id TEXT PRIMARY KEY,owner TEXT,scope TEXT,until REAL,state TEXT); CREATE TABLE IF NOT EXISTS sends(id TEXT PRIMARY KEY,fence TEXT UNIQUE,binding TEXT,state TEXT,receipt TEXT,updated REAL); CREATE TABLE IF NOT EXISTS events(n INTEGER PRIMARY KEY,at REAL,type TEXT,object TEXT,data TEXT); CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,data TEXT); CREATE TABLE IF NOT EXISTS observations(id TEXT PRIMARY KEY,source TEXT,data TEXT);`);
  }
  rows(sql,...args){return [...this.sql.exec(sql,...args)];}
  event(type,id,data){this.sql.exec('INSERT INTO events(at,type,object,data) VALUES(?,?,?,?)',Date.now(),type,id,JSON.stringify(data));}
  take(r) {
    const s=work(r),now=Date.now(),ttl=Math.max(30,Math.min(1800,Number(r.ttl_seconds || 300)))*1000;
    if(!r.operation_id || !r.owner) throw Error('operation_id and owner required');
    return this.ctx.storage.transactionSync(()=>{
      const old=this.rows('SELECT * FROM leases WHERE id=?',r.operation_id)[0];
      if(old && (old.owner!==r.owner || old.scope!==JSON.stringify(s))) throw Error('operation ID bound to different work');
      const conflicts=[];
      for(const l of this.rows("SELECT * FROM leases WHERE state='ACTIVE' AND until>? AND id!=?",now,r.operation_id)){
        const c=conflict(s,JSON.parse(l.scope));if(c) conflicts.push({operation_id:l.id,owner:l.owner,until:l.until,...c});
      }
      if(conflicts.length) return {decision:'CHOOSE_DIFFERENT_ANGLE',conflicts,send_authorized:false,message:'Please choose a different angle of contribution or engineering for this claim, or choose another.',alternatives:Object.keys(facets).filter(f=>f!=='outreach' && !conflicts.some(c=>c.facets.includes(f)))};
      this.sql.exec('INSERT INTO leases VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET until=excluded.until,state=excluded.state',r.operation_id,r.owner,JSON.stringify(s),now+ttl,'ACTIVE');
      this.event('take',r.operation_id,s);return {decision:'TAKEN',operation_id:r.operation_id,until:now+ttl,send_authorized:false};
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
    return this.ctx.storage.transactionSync(()=>{
      const prior=this.rows('SELECT * FROM sends WHERE fence=? OR id=?',fence,r.operation_id)[0];
      if(prior) return {decision:prior.id===r.operation_id && prior.binding===binding?'ALREADY_RESERVED':'DO_NOT_SEND',operation_id:prior.id,state:prior.state,send_authorized:false,message:'Existing outbound effect is being reconciled; continue other work.'};
      this.sql.exec('INSERT INTO sends VALUES(?,?,?,?,?,?)',r.operation_id,fence,binding,'RESERVED',null,Date.now());this.event('reserved',r.operation_id,JSON.parse(binding));
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
      if(r.payload_hash!==binding.payload_hash || r.source_version!==binding.source_version || r.actor!==binding.actor) throw Error('payload/source/actor fence changed');
      if(r.after==='SENT' && r.receipt.actor!==binding.actor) throw Error('readback actor mismatch');
      this.sql.exec('UPDATE sends SET state=?,receipt=?,updated=? WHERE id=?',r.after,JSON.stringify(r.receipt || null),Date.now(),r.operation_id);this.event(r.after,r.operation_id,r.receipt || {});
      return {decision:r.after,dispatch_winner:r.after==='DISPATCHED',operation_id:r.operation_id};
    });
  }
  async fetch(request) {
    try{
      const path=new URL(request.url).pathname;
      if(path==='/health') return json({ok:true,storage:'cloud-sql-durable-object',pc_required:false});
      if(path==='/snapshot') return json({leases:this.rows('SELECT * FROM leases'),outbound:this.rows('SELECT * FROM sends'),sources:this.rows('SELECT * FROM sources')});
      const r=await request.json();let result;
      if(path==='/take') result=this.take(r);
      else if(path==='/progress') result=this.progress(r);
      else if(path==='/reserve') result=await this.reserve(r);
      else if(path==='/transition') result=this.transition(r);
      else if(path==='/collect') result=await this.collect();
      else if(path==='/observe'){
        if(!r.id || !r.source) throw Error('observation ID/source required');
        this.sql.exec('INSERT INTO observations VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',r.id,r.source,JSON.stringify(r));result={decision:'OBSERVED'};
      } else return json({error:'unknown endpoint'},404);
      return json(result);
    }catch(e){return json({error:e.message,decision:'REPAIR_REQUEST',alternatives:['choose another independent contribution','continue read-only source research']},400);}
  }
  state(id){return JSON.parse(this.rows('SELECT data FROM sources WHERE id=?',id)[0]?.data || '{}');}
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
    if(marker){try{this.take({...JSON.parse(marker[1]),operation_id:id,owner:m.user || 'unknown'});}catch{}return;}
    if(candidate && Date.now()-Number(m.ts)*1000<1800000){
      for(const match of text.matchAll(/https?:\/\/github\.com\/([\w.-]+\/[\w.-]+)(?:\/(issues|pull)\/(\d+))?/g)){
        try{this.take({operation_id:id+':'+match[1],owner:m.user || 'unknown',entity:'github.com/'+match[1],description:text,resources:match[2]?[match[2]+'/'+match[3]]:[],ttl_seconds:Math.max(30,(Number(m.ts)*1000+1800000-Date.now())/1000)});}catch{}
      }
    }
  }
  async collect(){
    if(!this.env.SLACK_TOKEN){this.save('slack:channels',{error:'shared_slack_binding_unconfigured',complete:false});return {decision:'COLLECTOR_NOT_CONFIGURED'};}
    let catalog=this.state('slack:channels'),calls=0;
    const list=await this.slack('conversations.list',{limit:100,cursor:catalog.cursor || '',exclude_archived:true},'slack:channels');calls++;
    if(list){catalog={...catalog,channels:[...new Set([...(catalog.channels || []),...(list.channels || []).map(c=>c.id)])].sort(),cursor:list.response_metadata?.next_cursor || '',complete:!list.response_metadata?.next_cursor,error:null};this.save('slack:channels',catalog);}
    const channels=catalog.channels || [];if(!channels.length)return {requests:calls,channels:0};
    const index=catalog.index || 0,channel=channels[index%channels.length],id='slack:'+channel;
    let state=this.state(id),oldest=state.oldest || String(Date.now()/1000-86400);
    const history=await this.slack('conversations.history',{channel,limit:100,oldest,cursor:state.cursor || '',inclusive:false},id);calls++;
    if(history){let watermark=Number(state.watermark || oldest),threads=state.threads || {};
      for(const m of history.messages || []){this.observe(channel,m);watermark=Math.max(watermark,Number(m.ts));if(m.reply_count)threads[m.ts] ||= {cursor:'',oldest:'0'};}
      const cursor=history.response_metadata?.next_cursor || '';state={...state,cursor,oldest:cursor?oldest:String(watermark),watermark,threads,error:null,complete:!cursor};this.save(id,state);
    }
    const threads=Object.entries(state.threads || {}),start=state.thread_index || 0;let visited=0;
    for(let n=0;n<threads.length && calls<6;n++){
      const[root,t]=threads[(start+n)%threads.length],result=await this.slack('conversations.replies',{channel,ts:root,limit:100,oldest:t.oldest,cursor:t.cursor},id+':thread:'+root);calls++;visited++;
      if(result){for(const m of result.messages || [])this.observe(channel,m);t.cursor=result.response_metadata?.next_cursor || '';if(!t.cursor && result.messages?.length)t.oldest=String(Math.max(...result.messages.map(m=>Number(m.ts))));}
    }
    if(threads.length){state.thread_index=(start+visited)%threads.length;this.save(id,state);}
    catalog.index=index+1;this.save('slack:channels',catalog);return {decision:'COLLECTED',requests:calls,channels:channels.length,visited:channel};
  }
  async alarm(){
    await this.collect();await this.reconcile();await this.ctx.storage.setAlarm(Date.now()+60000);
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
      return await stub.fetch(request);
    }catch(e){return json({error:'service unavailable; continue independent work and repair road'},503);}
  },
  async scheduled(event,env,ctx){ctx.waitUntil(env.COORDINATION.get(env.COORDINATION.idFromName('shared')).fetch('https://internal/collect',{method:'POST',body:'{}'}));}
};
