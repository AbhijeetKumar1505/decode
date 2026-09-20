# Risk Engine

**Status:** Current classifier is foundation; side-effect model is Target

Risk is deterministic for the exact resolved action immediately before execution.

- **READ:** observe authorized state without material mutation.
- **WRITE:** change files/repos/services/remote state or consequential network.
- **DESTRUCTIVE:** deletion, disruption, exploitation, identity/privilege change,
  high-impact scanning, irreversible or broad effects.
- **PROHIBITED:** out of scope, secret leakage, illegal/unsupported ambiguity.

Inputs include capability, exact argv/payload, provider, all scopes, outputs,
side effects, privilege, credentials, rate, retries, reversibility, and phase.

| Action | Minimum |
|---|---|
| `curl URL` body | READ + network scope |
| `curl -o file URL` | WRITE + destination scope |
| HTTP state-changing method | WRITE/DESTRUCTIVE by semantics |
| shell redirect | WRITE; reject in vector-only mode |
| package install/update | WRITE, often privileged |
| Git status/diff | READ |
| Git mutation/force | WRITE/DESTRUCTIVE |
| active scan | WRITE + target/rate policy |
| exploit/disruption | DESTRUCTIVE + explicit authority |
| credential use/export | WRITE + secret/data policy |

Unknown effects fail closed. Decision returns level, allow/deny/approval, reason,
rules, digest, scopes, and evidence. Material change needs new approval.

Retry risk matters: duplicate irreversible effects may be DESTRUCTIVE. Only
declared transient idempotent operations auto-retry. Property/table tests cover
options, redirects, sudo, paths, HTTP, rates, credentials, provider drift, and
approval changes.
