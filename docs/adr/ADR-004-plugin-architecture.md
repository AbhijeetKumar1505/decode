# ADR-004: Keep Domain Extensions Outside the Kernel

**Status:** Accepted

## Context

A cybersecurity platform must grow without turning the trusted kernel into a collection of tool-specific behaviors.

## Decision

Expose versioned skill/plugin contracts for capabilities, risk, dependencies, inputs, outputs, and lifecycle. Keep the kernel focused on orchestration and policy.

## Consequences

- Community extension becomes possible without kernel modification.
- Plugin trust, compatibility, isolation, and revocation require first-class controls.
- In-process plugins remain fully trusted until isolation is implemented.
