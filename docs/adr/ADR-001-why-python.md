# ADR-001: Use Python as the Primary Language

**Status:** Accepted

## Context

Decode integrates security tools, model SDKs, data processing, CLI workflows, and research libraries. Rapid extension and broad ecosystem compatibility matter more than single-language purity.

## Decision

Use Python 3.11+ for the kernel, agents, skills, adapters, and local CLI. Use typed boundaries and Pydantic models. Performance- or isolation-critical workers may use other languages behind versioned contracts.

## Consequences

- Security and AI integrations are fast to develop.
- Runtime packaging, dependency supply chain, blocking SDKs, and dynamic imports require discipline.
- CPU-bound or high-assurance components may move behind service/plugin boundaries without changing platform contracts.
