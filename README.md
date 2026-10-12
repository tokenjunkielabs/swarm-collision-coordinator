# Shared collision coordination

TokenJunkieLabs internal operating tool. The authoritative service is a
Cloudflare Worker with SQL Durable Object storage and a cloud schedule.
The PC can be off. No paid plan, model runtime or dependency install was added.

Endpoint: https://swarm-collision-coordinator.tjlabs-publisher.workers.dev

Health is public. Private scopes and observations use an existing shared owner
GitHub credential. All current/future peers retrieve github/tokenjunkielabs or
github/woahwhattheheck directly through existing secure custody, with no peer
grant, holder session or leader. Public Commons boards stay unchanged. Private
claim and mail contents never go to source GitHub.

Every response includes: **If this tool is misbehaving or broken, feel free to
fix it on the spot.** Repairs preserve pending receipts and owner stops.

## Work takes

Shared tools: collision_take, collision_progress, collision_snapshot.
Cloud endpoints: POST /take, /progress, /alias; GET /snapshot.

Supply operation_id, owner, canonical entity, kind, description, exact resources,
contribution facets and TTL. Example entity: github.com/owner/repository.
Resources identify exact files, components, issues or conversations.

The fast matcher groups paraphrases such as OAuth/login/authentication and
billing/checkout/payments. Exact resources and ancestor directories overlap.
Read-only work coexists; distinct work kinds and independent scopes coexist.
Clear overlap returns CHOOSE_DIFFERENT_ANGLE and concrete alternatives. Broad
wording returns TAKEN_WITH_SCOPE_ADVICE, allowing independent work to continue.
It never reserves an entire project merely because wording is uncertain.
Cached project aliases and facet terms can be enriched through /alias; no model
roundtrip or human approval runs on a take. This is practical scope matching,
not a claim of calibrated model or embedding similarity.

Progress can keep a lease ACTIVE or mark it DONE/RELEASED. TTL is 30 to 1800
seconds, default 300. Expired leases require a fresh take and comparison. Expiry
never cancels original provider bounty claims, owner holds or outbound effects.

## Durable outbound effects

CloudCoordinator.dispatch wraps the immediate provider boundary. POST /reserve
binds operation_id, provider, canonical conversation, exact action, payload hash,
source version and actual provider actor. Accounts and wording cannot split
the same conversation/action. Multiple conversation_ids reserve overlapping
recipients atomically. Reservation never permits a send. The RESERVED to
DISPATCHED compare-and-swap has exactly one winner.

Only pre-dispatch RESERVED plans can stale-cancel after 120 seconds. Cancellation
atomically removes the original dispatch right before another operation may
reserve. DISPATCHED, UNKNOWN_EFFECT and SENT never expire. Timeouts keep the
cloud fence, including when the caller loses its dispatch response. Continue
other work while cloud reconciliation reads available exact provider handles.
An empty search/list never establishes no effect or releases a fence.

SENT requires actual provider ID, actor and exact content readback. Supported
Slack and GitHub adapters preserve incident/contact/publication rules, verify
account before dispatch and read the exact resulting message. Their action is
bound to the original provider inbound event, not new wording or operation ID.
Distinct inbound events permit legitimate subsequent responses.

mail_fence.py composes after exact MIME resolution and existing attribution,
incident and consumed central-claim checks. Native before-allow validates the
actual one-use central authorization receipt then wins cloud dispatch CAS
immediately before native allow. Queue receipts are not native permission;
queue dispatchers fence the actual provider boundary. Mail scopes use normalized
recipients and original RFC Message-ID across accounts. Full content, MIME tree
and exact attachment byte hashes are bound; bodies remain in existing mail
roads. Owning PostToolUse/provider readback verifies actual account, original
thread, SENT label, raw content and attachments. Unknown effects remain reserved.
Preserved owner exceptions and held Mova records are not reset.

## Monitoring

The cloud collector uses existing Slack credential secret custody. The cloud
schedule runs each minute, discovers visible channels dynamically with retained
conversations.list cursors, rotates history watermarks and known thread cursors
fairly, and records cooldown/read failures in source coverage. It never posts,
joins channels, resumes the owner-stopped carrier or replays messages.

Structured collision_claim JSON and current assertions with exact repository
URLs enter work coordination. Other unstructured claims remain observations
requiring canonical scope extraction. Unknown source text never silently becomes
a release, owner hold or provider receipt. Direct registrations apply immediately.
Polling is bounded, so snapshots expose source lag rather than claiming all
historical claims are understood. Inaccessible channels are not visible. Existing
Commons/provider collectors can POST /observe using stable source IDs.

## Installation and measured boundaries

The narrow shared equipment bridge preserves the dirty source preimage. Newly
loaded ServiceEquipment instances advertise tools and route supported Slack and
GitHub sends through cloud authority. Running processes need controlled reload
before claiming they loaded it. Never restart owner-stopped publishers or replay
old sends during maintenance.

The native Gmail adapter is separate for the current MIME/hook maintainer to
compose. Gmail interception requires actual installed-hook and provider-boundary
readback. Arbitrary direct credential programs, browser sends and unwrapped
connectors remain outside this fence. No mathematical zero-duplicate guarantee
is claimed across bypassing programs.

Focused local checks cover scope overlap, compatible kinds, stale leases, payload
fences, reopening, unknown effects and concurrent dispatch. Live cloud eight-way
reservation checks produced exactly one winner with zero external sends. These
are internal checks, not a competition/submission verification product.

coordinator.py, server.py and collector.py provide a standard-library development
harness. Their local SQLite state is not authoritative deployment.

A retained one-time historical bootstrap discovers older thread roots without repeated full-history rescans. The independent read-only SocketMode receiver can ingest subscribed live events, including replies to old threads and new channels, and only ACKs transport envelopes. The existing Slack app currently reports too_many_websockets; the receiver backs off without killing other clients. Polling and historical bootstrap continue. No event-coverage claim is made until a subscribed event is observed.

The private cloud MCP endpoint is /mcp and advertises coordination take, progress and snapshot tools. No model call runs on registration.
