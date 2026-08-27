# Plugin Manifest and Lifecycle

## Status

**Implemented P2 managed-plugin trust boundary.** Third-party packages are
manifest-managed. Discovery, integrity verification, lifecycle operations, and
conformance checks never import an entrypoint. The legacy `decode.plugins`
package remains a separate trusted in-tree compatibility mechanism.

## Manifest contract

Every package supplies `plugin.json` with schema version, stable ID, semantic
version, `module:callable` entrypoint, Decode compatibility range, SHA-256
entrypoint digest, requested capabilities, dependencies, permissions,
platforms, and sandbox profile. Unknown fields fail validation.

Source digest, compatibility, revocation, and entrypoint static inspection must
all pass before a package can be enabled. Manifest declarations never grant
scope, approval, executor, credential, memory, filesystem, network, or model
access.

## Lifecycle

`PluginLifecycleManager` persists local state under its managed package root
and supports:

- install and verification without code import;
- explicit enable and disable;
- source-pinned upgrade and rollback to a retained version;
- policy revocation; and
- uninstall without deleting evidence or audit data.

A revoked package cannot be enabled. Enabling requires static conformance:
valid syntax, a declared entrypoint callable, verified source, and the
container sandbox profile.

## Container profile

`PluginContainerProfile` produces a Docker invocation with network disabled,
a read-only root filesystem, dropped Linux capabilities, `no-new-privileges`,
PID/CPU/memory limits, a noexec temporary filesystem, and a read-only package
mount. Plugin manifests requesting network access fail closed. Target-scoped
container networking is deliberately unsupported until it has a separately
verified policy implementation.

## Remaining runtime work

The managed lifecycle is complete, but generic plugin invocation has not been
exposed as a public execution path. It will be added only when the container
protocol can pass typed input and output through `ExecutionCoordinator` without
broadening the manifest’s effective permissions.