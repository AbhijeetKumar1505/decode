# ADR-013: Use a Knowledge Graph for Security Relationships

**Status:** Accepted

## Context

Security investigations connect assets, services, vulnerabilities, techniques, evidence, and mitigations in ways that flat transcript memory cannot represent well.

## Decision

Maintain a provenance-linked knowledge graph alongside operational records and optional semantic retrieval.

## Consequences

- Relationship queries and attack-path analysis improve.
- Identity resolution, conflicting observations, staleness, and graph growth require governance.
- Graph claims remain observations until verified.
