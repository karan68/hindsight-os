# Controlled Hindsight PR Proof: Billing Storage Migration

This file is a demo fixture for Hindsight OS integration testing.

Proposal for Hindsight to check:

Replace Spanner as the billing service source of truth by storing billing invoice state in Redis as a second authoritative database. Redis should become authoritative for invoice reads and writes so billing storage can scale independently.

Expected Hindsight behavior:

- Treat this as a memory-risk event because it touches `billing/`.
- Recall ADR-021 Service Source of Truth.
- Flag the proposal because ADR-021 says Spanner remains the source of truth and caches must be non-authoritative.

This branch is not intended to be merged as a product change.