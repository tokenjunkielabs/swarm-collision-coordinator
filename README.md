# Shared collision coordination

TokenJunkieLabs internal operating tool. Python standard library, SQLite WAL,
no dependency install, no model runtime, no credentials in the database.

Run `python server.py --database <private-state-path>/coordination.sqlite3`.
The default endpoint is `http://127.0.0.1:8891`. Bind an existing shared transport
to this endpoint for remote peers; the service imposes no peer admission rules.

POST `/take` with operation_id, owner, entity, kind, description, resources,
facets, ttl_seconds. The entity must be the canonical repository/provider/deal
identity. resources are exact files/conversations/components. Explicit facets
and built-in synonym groups catch paraphrases such as login/authentication.
Same files, ancestor directories or contribution facets conflict. Read-only
work coexists. Disjoint exact resources or known contribution facets coexist.
Ambiguous same-project work returns CHOOSE_DIFFERENT_ANGLE with alternatives.
This is practical scope matching, not a calibrated model similarity score.

POST `/progress` with operation_id, owner, state ACTIVE/DONE/RELEASED and
progress. Active leases last 30–1800 seconds. Expired leases require a fresh
take and collision comparison. Expiry never cancels provider bounty claims,
owner holds or outbound reservations.

POST `/reserve` binds an outbound operation to provider, conversation_id,
action, payload_hash, source_version and actual provider actor. This reserves
the exact conversation/action across accounts and different wording. It never
returns permission to send. Real adapters call Coordinator.dispatch, whose
atomic reservation winner alone may reach the provider. A duplicate, including
the same operation ID retry, returns its existing state without re-execution.

Adapters must verify actor before dispatch, bind the exact approved payload
hash/source version, preserve existing incident/contact/publication controls,
and read back provider ID, actor and exact body after sending. Exceptions and
incomplete readback become UNKNOWN_EFFECT. RESERVED, DISPATCHED, UNKNOWN_EFFECT
and SENT do not expire. Provider reconciliation can mark a verified message
SENT; an empty search/list never proves no effect and never releases a fence.
This conservative first implementation keeps every conversation/action fence;
subsequent legitimate responses need explicit distinct provider inbound event
identities as part of the action. Never use arbitrary wording or account names
to create a fresh action and bypass an unresolved effect.

SlackCollector reads through existing shared Slack equipment. It discovers
visible channels with retained conversations.list cursors, rotates channel
history with high-water marks, and retains known thread cursors. Structured
`<collision_claim>{...}</collision_claim>` registrations are imported. Other
claim-like messages remain observations requiring canonical scope extraction;
they are not silently treated as authoritative claims or releases. Coverage,
read failures and cooldown deadlines stay in sources. Collection never posts,
joins a channel, resumes the owner-stopped carrier, or replays messages.

Current boundaries: the service and dispatcher API work; arbitrary direct
provider programs remain outside this fence until their send road is wrapped.
Unstructured historical claims need source-specific identity extraction before
they can reliably participate in overlap decisions. Visible-channel discovery
cannot discover inaccessible provider channels. Thread scans are bounded and
known-thread scheduling needs a fair queue for channels with many threads.
Use snapshot source coverage to assess monitoring lag. Do not claim zero
duplicates across bypassing programs.

Focused checks: `python -m unittest test_coordination -v` covers semantic scope,
compatible work, stale leases, binding changes, database reopening, unknown
effect retention and twelve concurrent senders producing one provider call.
