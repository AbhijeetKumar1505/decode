# ADR-004: Keep Extensions Outside the Trusted Kernel

**Status:** Accepted; amended for v2

## Decision

Use native capabilities for kernel operations, provider-discovered tools behind
adapters, skills for guidance, workflows for procedure, and isolated MCP/
declarative packages for external integration. Every invocation crosses the
coordinator.

## Consequences

Install does not grant execution. Extensions need schema, provenance,
compatibility, envelopes, isolation, lifecycle, and revocation. The removed
in-process hardcoded-tool loader remains superseded.
