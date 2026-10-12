/* TokenJunkieLabs: compose at the existing immediate Gmail provider boundary. */
export const REPAIR_NOTE='If this tool is misbehaving or broken, feel free to fix it on the spot.';
const BASE='https://swarm-collision-coordinator.tjlabs-publisher.workers.dev';
const ownerReviewHashes=new Set(['ae646d823871f31c6089671187ff9e31eb35cab27d309d946e667bbe88a44c0e','f394ac323133c106ba9bf9e20e0b341561afaa8bee8f954d20104ad2540b4ac8','2320cb840d27a3159fe488b8bc28a51a96d4bc600b26658f95ac1b953f6f14a8','f550b5b6bbd9f37e88b5fd9b12989bd9165831120a977f5806d31b2266f0d711','9bd4ca58428fa2a2d65f9fd38846182262f6c1349f8613e183e57bf9e6914286']);
const labRouteHash='32f3d105520402d7269774e9371916f660fbff6a1c76fd8c9c48feca8514d0f7';
const canonical=value=>JSON.stringify(value,(_,v)=>v && typeof v==='object' && !Array.isArray(v)?Object.fromEntries(Object.keys(v).sort().map(k=>[k,v[k]])):v);
const hashText=async text=>[...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text)))].map(x=>x.toString(16).padStart(2,'0')).join('');
const hash=value=>hashText(canonical(value));
const address=value=>{const match=String(value).trim().match(/(?:^|<)([^<>\s]+@[^<>\s]+)>?$/);if(!match)throw Error('resolved mail address invalid');return match[1].toLowerCase();};
const hex=value=>typeof value==='string' && /^[a-f0-9]{64}$/.test(value);

export async function mailBinding(resolved){
  for(const key of ['operation_id','attempt_id','account','sender','to','subject','content_digest','mime_tree_digest','link_id'])if(resolved[key]===undefined || resolved[key]===null || resolved[key]==='')throw Error('mail binding missing '+key);
  const selected=resolved.selected_account;
  if(selected!==undefined && selected!==null){
    if(typeof selected!=='object' || Array.isArray(selected))throw Error('selected account binding invalid');
    for(const key of ['link_id','profile_id'])if(key in selected && String(selected[key] || '')!==String(resolved[key] || ''))throw Error('selected account '+key+' mismatch');
    for(const key of ['account','email'])if(key in selected && address(selected[key])!==address(resolved.account))throw Error('selected account address mismatch');
  }
  for(const key of ['to','cc','bcc'])if(!Array.isArray(resolved[key] || []))throw Error('resolved recipient lists required');
  if(!resolved.to.length || !hex(resolved.content_digest) || !hex(resolved.mime_tree_digest))throw Error('full exact mail/MIME SHA256 required');
  const attachments=resolved.attachments || [];
  if(!Array.isArray(attachments) || attachments.some(a=>!a.filename || !(a.content_type || a.mime_type) || !hex(a.byte_sha256 || a.sha256)))throw Error('exact attachment filename/type/byte SHA256 required');
  const kind=resolved.kind || 'send',original=resolved.original_rfc_message_id || null;
  if(['reply','forward','sent_followup'].includes(kind) && !original)throw Error('resolve original RFC Message-ID through provider');
  const recipients=[...new Set(['to','cc','bcc'].flatMap(k=>(resolved[k] || []).map(address)))].sort();
  let action=original?'respond-to:'+original:'initial-contact';
  if(kind==='owner_review'){
    const authorized=ownerReviewHashes.has(await hashText(resolved.operation_id)) && await hashText(resolved.link_id+'|'+String(resolved.profile_id || ''))===labRouteHash && address(resolved.account)==='tokenjunkielabs@gmail.com' && address(resolved.sender)==='tokenjunkielabs@gmail.com' && resolved.to.length===1 && address(resolved.to[0])==='tokenjunkielabs@gmail.com' && !(resolved.cc || []).length && !(resolved.bcc || []).length && !original && hex(resolved.central_claim_id);
    if(!authorized)throw Error('owner review requires exact source-authorized central consumed claim and selected lab account');
    action='owner-review:'+resolved.operation_id;
  }
  const content={account:resolved.account,sender:address(resolved.sender),to:resolved.to.map(address).sort(),cc:(resolved.cc || []).map(address).sort(),bcc:(resolved.bcc || []).map(address).sort(),subject:resolved.subject,kind,content_digest:resolved.content_digest,mime_tree_digest:resolved.mime_tree_digest,attachments,original_thread_id:resolved.original_thread_id || null,original_message_id:resolved.original_message_id || null,original_rfc_message_id:original,attempt_id:resolved.attempt_id,central_claim_id:resolved.central_claim_id || null,selected_account:{link_id:resolved.link_id,profile_id:resolved.profile_id || null,account:address(resolved.account)}};
  return {operation_id:resolved.operation_id,provider:'gmail',conversation_id:await hash(['mail-recipient-conversation',recipients]),conversation_ids:await Promise.all(recipients.map(x=>hash(['mail-recipient',x]))),action,payload_hash:await hash(content),source_version:String(resolved.source_version || await hash([original,resolved.original_thread_id || null])),actor:address(resolved.account)};
}

export function createMailCollisionFence({tokenProvider,endpoint=BASE,fetchImpl=fetch}={}){
  if(typeof tokenProvider!=='function')throw Error('existing shared credential reader required');
  async function request(path,input){
    const response=await fetchImpl(endpoint+path,{method:'POST',headers:{Authorization:'Bearer '+await tokenProvider(),'Content-Type':'application/json','User-Agent':'TokenJunkieLabs-Collision-Coordinator'},body:JSON.stringify(input)});
    const value=await response.json();if(!response.ok)throw Error('collision road repair required');return value;
  }
  async function reserveResolved(resolved){
    // Run BEFORE beginDispatchAttempt consumes an actual provider attempt.
    // The existing service's attempt ID is deterministic from claim_id, so its
    // planned value is bound before consumption and checked again at dispatch.
    const binding=await mailBinding(resolved),result=await request('/reserve',binding);
    return {binding,planned_attempt_id:resolved.attempt_id,selected_account:{account:resolved.account,link_id:resolved.link_id,profile_id:resolved.profile_id},result,note:REPAIR_NOTE};
  }
  async function beforeProviderSend(reservation,begun,existingBeforeSend){
    if(reservation.result.decision!=='RESERVED' || begun.attempt_id!==reservation.planned_attempt_id)return false;
    if(typeof existingBeforeSend!=='function' || await existingBeforeSend()!==true)return false;
    const result=await request('/transition',{...reservation.binding,before:'RESERVED',after:'DISPATCHED'});
    return result.dispatch_winner===true;
  }
  async function outcome(reservation,providerResult,verifyProviderReadback){
    const b=reservation.binding;
    const id=providerResult?.id || providerResult?.providerMessageId;
    const partial={provider_id:id?String(id):null,thread_id:providerResult?.thread_id || providerResult?.threadId || providerResult?.providerThreadId || null,label_ids:providerResult?.label_ids || providerResult?.labelIds || null,actor:b.actor,selected_account:reservation.selected_account,verified:false};
    let receipt=null;
    try{if(typeof verifyProviderReadback==='function')receipt=await verifyProviderReadback(providerResult,reservation);}catch{}
    // An accepted ID alone is NEVER SENT. The trusted owning reader checks
    // selected account, SENT label, original thread, raw MIME headers/body and
    // attachment byte hashes, then returns the actual provider handle.
    const verified=receipt?.verified===true && receipt.actor===b.actor && receipt.provider_id && receipt.selected_account_verified===true && receipt.sent_label_verified===true && receipt.raw_mime_verified===true && receipt.attachments_verified===true;
    return request('/transition',{...b,before:'DISPATCHED',after:verified?'SENT':'UNKNOWN_EFFECT',receipt:verified?receipt:partial});
  }
  return {reserveResolved,beforeProviderSend,outcome,request};
}
