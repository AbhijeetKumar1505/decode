# ADR-004: Keep Domain Extensions Outside the Kernel

**Status:** Superseded by the universal-agent model (see [../SYSTEM_ARCHITECTURE.md](../SYSTEM_ARCHITECTURE.md) and [../PLUGIN_MANIFEST.md](../PLUGIN_MANIFEST.md))

## Context

A cybersecurity platform must grow without turning the trusted kernel into a collection of tool-specific behaviors.

## Decision (original)

Expose versioned skill/plugin contracts for capabilities, risk, dependencies, inputs, outputs, and lifecycle. Keep the kernel focused on orchestration and policy.

## What replaced it

The core intent — keep the kernel tool-agnostic — still holds, but the mechanism
changed. Domain behavior is no longer added through in-tree plugins or a tool
catalog. The agent **discovers** installed tools (`list_tools`) and drives them
through the governed `shell_command` capability, and repeatable procedures are
authored as **markdown playbooks**. The in-process plugin loader and the
manifest/sandbox/lifecycle code were removed. *Plugins* are now reserved for
optional, isolated connectors to **external** systems, still to be designed.

## Consequences

- Community extension happens through playbooks and native capabilities, not kernel modification.
- No arbitrary third-party code runs in-process; the removed loader's trust risk is gone.
- A future external-plugin surface must pass typed I/O through `ExecutionCoordinator` under isolation before it is reintroduced.
