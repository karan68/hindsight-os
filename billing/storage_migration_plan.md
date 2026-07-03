# Controlled Hindsight PR Proof: Billing Storage Migration

This file is a demo fixture for Hindsight OS integration testing.

Proposal for Hindsight to check:

Replace Spanner as the billing service source of truth by storing billing invoice state in Redis as a second authoritative database. Redis should become authoritative for invoice reads and writes so billing storage can scale independently.

This branch is not intended to be merged as a product change.