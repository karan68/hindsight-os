from __future__ import annotations

from app.models import MemoryItem


SEED_MEMORIES: list[MemoryItem] = [
    MemoryItem(
        id="adr-021",
        label="ADR-021 Service Source of Truth",
        text=(
            "ADR-021: Each user-facing service keeps its source of truth in Spanner "
            "(regionally replicated). Caches such as Memcache and the CDN are "
            "non-authoritative and must be regenerable from Spanner. A service must NOT "
            "introduce a second authoritative store for the same entity. Owner: Priya. "
            "Status: accepted."
        ),
        node_sets=["data", "storage", "architecture-decision", "trusted"],
        source="ADR · docs/adr in GitHub",
    ),
    MemoryItem(
        id="rel-policy-09",
        label="Release & Canary Policy",
        text=(
            "After a P1 caused by a no-canary launch (INC-19), every production rollout "
            "must progress through canary at 1%, then 10%, then 100%, with automated "
            "rollback on any SLO regression. No production pushes during the Friday 16:00 "
            "to Monday 09:00 freeze window. Owner: SRE. Status: enforced."
        ),
        node_sets=["release", "reliability", "incident-learning", "trusted"],
        source="Postmortem · Jira INC-19",
    ),
    MemoryItem(
        id="priv-014",
        label="PII Logging Restriction",
        text=(
            "User PII (email, full name, postal address, raw IP) must never be written to "
            "application logs, traces, or analytics events; use the hashed user_id instead. "
            "Log retention is 30 days. Reason: GDPR/CCPA obligations and the INC-31 leak. "
            "Owner: Privacy. Status: mandatory."
        ),
        node_sets=["privacy", "logging", "compliance", "trusted"],
        source="Standard · Privacy wiki",
    ),
    MemoryItem(
        id="exp-208",
        label="EXP-208 Infinite Scroll A/B Test",
        text=(
            "EXP-208 tested infinite scroll on the results page against pagination. Task "
            "completion dropped and p95 latency rose on low-end devices, so the change was "
            "rolled back. Decision: keep pagination on the results page. Owner: Diego (PM). "
            "Status: concluded and reverted."
        ),
        node_sets=["search", "ux", "experiment", "failed-experiment"],
        source="Experiment · A/B platform",
    ),
    MemoryItem(
        id="dep-policy-03",
        label="Third-Party Dependency Policy",
        text=(
            "New third-party dependencies must pass OSS review (license plus security scan) "
            "and be added through the locked, vendored manifest. Builds must never pull "
            "'latest' from public registries at build time. Reason: software supply-chain "
            "risk. Owner: Security. Status: enforced."
        ),
        node_sets=["security", "supply-chain", "policy", "trusted"],
        source="Standard · Security wiki",
    ),
    MemoryItem(
        id="brainstorm-localstorage",
        label="Client-Side Session Storage Brainstorm",
        text=(
            "Brainstorm: store user session and profile state in client-side localStorage "
            "to cut Spanner cost. Written before ADR-021; never adopted and superseded by "
            "the Spanner-plus-Memcache decision. Status: obsolete candidate."
        ),
        node_sets=["data", "brainstorm", "obsolete-candidate"],
        status="obsolete",
        source="Slack thread · #eng-decisions",
    ),
    MemoryItem(
        id="brainstorm-public-grpc",
        label="Direct Public gRPC Exposure Spike",
        text=(
            "Spike: expose internal gRPC services directly to mobile and partner clients "
            "to remove the API gateway hop. The idea was rejected and superseded by "
            "ADR-041, which requires all external traffic to enter through the API gateway "
            "for authentication, rate limiting, and WAF enforcement. Status: obsolete candidate."
        ),
        node_sets=["api", "platform", "security", "brainstorm", "obsolete-candidate"],
        status="obsolete",
        source="Design spike · Platform review",
    ),
    MemoryItem(
        id="brainstorm-long-sessions",
        label="Long-Lived Login Session Proposal",
        text=(
            "Brainstorm: make login sessions last 30 days with long-lived browser cookies "
            "so users rarely need to re-authenticate. Later superseded by ADR-014, which "
            "requires 15-minute JWT access tokens plus rotating refresh tokens and forbids "
            "long-lived or non-expiring sessions. Status: obsolete candidate."
        ),
        node_sets=["auth", "security", "brainstorm", "obsolete-candidate"],
        status="obsolete",
        source="Product brainstorm · Identity backlog",
    ),
    MemoryItem(
        id="brainstorm-raw-pii-logs",
        label="Raw Checkout Logging Debug Plan",
        text=(
            "Brainstorm: temporarily log raw checkout requests, including email address "
            "and IP, to debug an intermittent payment issue. Later superseded by the PII "
            "Logging Restriction, which requires hashed user_id and forbids raw PII in "
            "logs, traces, or analytics events. Status: obsolete candidate."
        ),
        node_sets=["privacy", "logging", "brainstorm", "obsolete-candidate"],
        status="obsolete",
        source="Incident debug plan · Slack",
    ),
    MemoryItem(
        id="api-conv-02",
        label="Service API & RPC Conventions",
        text=(
            "Internal service-to-service traffic uses gRPC with deadlines, retries, and the "
            "standard auth interceptor. The public edge is REST/JSON behind the API gateway. "
            "Services must not reach across boundaries into another service's database. "
            "Owner: Platform. Status: accepted."
        ),
        node_sets=["api", "platform", "architecture-decision", "trusted"],
        source="RFC · Google Docs",
    ),
    # --- Payments / ledger cluster --------------------------------------------
    # These memories give GRAPH_COMPLETION useful relationship facts (checkout
    # writes to the payments ledger, ledger entries are append-only, Redis caches
    # must not be authoritative) without claiming graph retrieval out-ranks
    # semantic similarity.
    MemoryItem(
        id="checkout-arch",
        label="Checkout Service Architecture",
        text=(
            "The checkout-service converts a shopping cart into a confirmed order and writes "
            "every order and payment event to the payments-ledger. It is the highest-traffic "
            "write path on the platform and calls the payments-ledger synchronously on the "
            "critical path. Owner: Payments. Status: accepted."
        ),
        node_sets=["payments", "checkout", "architecture-decision", "trusted"],
        source="Service doc · Backstage",
    ),
    MemoryItem(
        id="adr-030",
        label="ADR-030 Payments Ledger Append-Only",
        text=(
            "ADR-030: The payments-ledger is strictly append-only. Entries are immutable once "
            "written; they are never updated or removed. Corrections are made by appending a "
            "compensating reversal entry that references the original. This immutability is a "
            "hard requirement for financial reconciliation and SOX audit. Owner: Finance "
            "Engineering. Status: accepted."
        ),
        node_sets=["payments", "ledger", "compliance", "architecture-decision", "trusted"],
        source="ADR · docs/adr in GitHub",
    ),
    MemoryItem(
        id="inc-51",
        label="INC-51 Double-Charge Postmortem",
        text=(
            "INC-51: a double-charge hit customers when a service treated a Redis cache of "
            "ledger balances as authoritative and served a stale balance during a retry. Root "
            "cause: caching authoritative ledger state and missing idempotency keys. Actions: "
            "never treat a cache as the source of truth for the ledger; enforce idempotency "
            "keys on every payment write. Owner: Payments. Status: closed."
        ),
        node_sets=["payments", "reliability", "incident-learning", "trusted"],
        source="Postmortem · Jira INC-51",
    ),
    # --- Data retention + analytics cluster -----------------------------------
    MemoryItem(
        id="ret-std-07",
        label="Data Retention & Cleanup Standard",
        text=(
            "Batch cleanup jobs that purge expired or abandoned rows must run in the off-peak "
            "window, be idempotent and resumable, and delete in small batches to reclaim "
            "storage without holding long locks. Applies to caches, session tables, and "
            "soft-deleted records. Owner: Platform. Status: enforced."
        ),
        node_sets=["data", "operations", "policy", "trusted"],
        source="Standard · Platform wiki",
    ),
    MemoryItem(
        id="adr-022",
        label="ADR-022 Analytics on the Warehouse",
        text=(
            "ADR-022: Analytics and reporting workloads run against the data-warehouse via the "
            "nightly ETL, never against the production transactional databases or their read "
            "replicas. Ad-hoc analytical queries on production are prohibited to protect OLTP "
            "latency. Owner: Data Platform. Status: accepted."
        ),
        node_sets=["data", "analytics", "architecture-decision", "trusted"],
        source="ADR · docs/adr in GitHub",
    ),
    MemoryItem(
        id="inc-33",
        label="INC-33 Prod Replica Overload",
        text=(
            "INC-33: a heavy analytical JOIN run against a production read replica saturated it "
            "and spiked checkout latency platform-wide. Root cause: an analytics query on "
            "production infrastructure. Actions: move the query to the warehouse and add a "
            "query-cost guard. Owner: SRE. Status: closed."
        ),
        node_sets=["data", "reliability", "incident-learning", "trusted"],
        source="Postmortem · Jira INC-33",
    ),
    # --- Auth / security cluster ---------------------------------------------
    MemoryItem(
        id="adr-014",
        label="ADR-014 Short-Lived Auth Tokens",
        text=(
            "ADR-014: Authentication uses short-lived JWT access tokens with a 15-minute expiry "
            "issued by the auth-service, plus rotating refresh tokens. Long-lived or "
            "non-expiring sessions are not permitted, and tokens are validated at the gateway. "
            "Owner: Identity. Status: accepted."
        ),
        node_sets=["auth", "security", "architecture-decision", "trusted"],
        source="ADR · docs/adr in GitHub",
    ),
    MemoryItem(
        id="sec-std-05",
        label="Secrets Management Standard",
        text=(
            "All credentials, API keys, and tokens are stored in the secrets vault and injected "
            "at runtime. Secrets must never be committed to code, baked into images, or written "
            "to logs or environment dumps. Rotation is mandatory every 90 days. Owner: "
            "Security. Status: enforced."
        ),
        node_sets=["security", "secrets", "policy", "trusted"],
        source="Standard · Security wiki",
    ),
    # --- Infra / deploy cluster ----------------------------------------------
    MemoryItem(
        id="adr-041",
        label="ADR-041 Edge Traffic via API Gateway",
        text=(
            "ADR-041: All external traffic enters through the API gateway, which enforces "
            "authentication, rate limiting, and WAF rules. Services are never exposed directly "
            "to the public internet; the gateway is the only ingress. Owner: Platform. Status: "
            "accepted."
        ),
        node_sets=["api", "platform", "security", "architecture-decision", "trusted"],
        source="ADR · docs/adr in GitHub",
    ),
    MemoryItem(
        id="inc-60",
        label="INC-60 Cascading Timeout Failure",
        text=(
            "INC-60: a missing RPC deadline let a slow dependency exhaust the caller's thread "
            "pool, cascading into a platform-wide outage. Root cause: no timeout on a gRPC "
            "call. Actions: every gRPC call must set a deadline, with circuit breakers and "
            "bounded retries. Owner: SRE. Status: closed."
        ),
        node_sets=["reliability", "platform", "incident-learning", "trusted"],
        source="Postmortem · Jira INC-60",
    ),
    # --- Frontend cluster -----------------------------------------------------
    MemoryItem(
        id="ds-01",
        label="Design System Component Standard",
        text=(
            "Product UI is built from the shared component library (buttons, forms, tables, "
            "modals), which encodes accessibility and theming. Bespoke one-off components are "
            "discouraged and require design-system review before use. Owner: Design Systems. "
            "Status: accepted."
        ),
        node_sets=["frontend", "design-system", "standard", "trusted"],
        source="Standard · Storybook docs",
    ),
]

# Stable id -> source map so persisted state (seeded before this field existed) can be
# backfilled on read without forcing a re-seed.
SEED_SOURCE_BY_ID = {memory.id: memory.source for memory in SEED_MEMORIES}

DEMO_PROPOSALS = [
    "RFC: add a Redis cluster as a second source of truth for user profiles to cut Spanner cost.",
    "RFC: add a Memcache read-through cache (non-authoritative, 60s TTL) for the profile read path.",
    "RFC: keep pagination instead of infinite scroll for the results-page redesign.",
    "Add a nightly cleanup job to the checkout service that hard-deletes abandoned carts and old "
    "order rows from the payments ledger to reclaim database storage.",
]
