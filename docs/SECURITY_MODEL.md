# Security Model

**Status:** Normative v2 security architecture

The goal is useful engineering/authorized security without allowing a model,
tool, workflow, extension, or provider to grant itself authority.

Untrusted: user artifacts, model/tool/web/repo content, playbooks/extensions,
MCP, memory. Trusted base: validated contracts, policy/scope, approval binding,
coordinator, state/event/evidence integrity, secret manager, verification.

Every action evaluates identity, workflow authority, target/network/filesystem/
output/credential scope, provider, capability, side effects/risk, approval,
budget, time, and rate.

Before active security testing, lock exact in/out scope, rules, forbidden tests,
rate, authentication, reporting/disclosure, safe harbor, and expiry. Ambiguity
pauses. A public program URL alone is not scope evidence when details need login.

Approval binds exact target/provider/action/outputs/credentials/data/risk/scope/
expiry to a digest. Chat assent is not a token.

Use opaque credential references and late injection. Never put secrets in
prompts, definitions, displays, logs, evidence metadata, memory, or reports.

Treat content as data; isolate instructions; preserve source labels; enforce
authority independently. Retrieved memory is untrusted.

Use Linux permissions, scoped users/workspaces, rootless containers, namespaces,
seccomp/AppArmor, egress/resource controls, and higher isolation where needed.
Docker alone is not complete.

Protected raw evidence is owner-only: POSIX stores enforce directory `0700` and
file `0600`; Windows stores apply a protected DACL granting full access only to
the current user. Failure to apply the platform control fails evidence capture
and therefore consequential execution.

Pin/verify dependencies/extensions. MCP/plugins receive explicit envelopes and
no ambient access. Fail closed on missing audit/evidence, unknown effects,
provider drift, safety-affecting parser ambiguity, scope conflict, secret-store
failure, or migration incompatibility.

Red/blue/purple are workflows. Generated findings start as candidates and require
declared validation evidence; unresolved leads remain unresolved.
