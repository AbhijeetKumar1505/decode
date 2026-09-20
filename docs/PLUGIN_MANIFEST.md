# Extensions, Skills, and Plugins

**Status:** Current declarative/MCP foundations; workflow hierarchy is authority

```text
workflow -> phase -> task -> capability -> tool
                         ^
                    skill guidance
```

Skills guide; they do not own policy/state/approval/execution/verification.
Native capabilities are trusted kernel operations. System tools are discovered.
MCP offers external tools. Plugin packages bundle declarative assets/providers,
never arbitrary in-process code.

Install/registration, verification, enablement, discovery, authorization, and
invocation are separate; install grants no execution authority.

Manifests declare identity/version, compatibility, paths, source integrity,
licenses, workflow/skill schemas, MCP, requested capabilities/data handling, and
revocation. Reject traversal, unknown schema, in-process entrypoints, undeclared
binaries, unpinned remote sources.

Project overrides user/system config but cannot weaken policy. Extensions are
untrusted: validate, isolate, namespace, restrict network/files/credentials,
record provenance, support disable/remove/revoke.

Policy, scope, approval, state, evidence, audit, scheduler, brains, UTOS,
host control, and providers are not plugins.

Preserve current `extensions/`, MCP commands, and declarative plugins while
aligning envelopes. Do not restore the old in-process hardcoded-tool loader.
