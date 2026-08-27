# Risk Engine

## Status

Decode currently enforces capability-level `READ`, `WRITE`, and `DESTRUCTIVE` classifications through the safety controller and governance gate. Command scoring and argument-sensitive policy are planned.

## Objective

The risk engine converts a fully resolved proposed action into a deterministic risk decision. It is policy code, not a model judgment.

## Inputs

- Capability and tool.
- Normalized arguments and redacted command.
- Target and scope match.
- Executor and effective identity.
- Required privileges.
- Data classification and secret access.
- Plugin/tool trust.
- Network reach.
- Expected side effects.
- Reversibility.
- User/project policy and prior approval.

## Output

```json
{
  "level": "WRITE",
  "score": 48,
  "decision": "needs_approval",
  "reasons": [
    "active network probe",
    "authorized target",
    "normal user privileges"
  ],
  "policy_version": "1"
}
```

The level drives existing controls; the score explains finer distinctions and future policy.

## Risk levels

| Level | Score | Default |
|---|---:|---|
| READ | 0–24 | Allow if scope/data policy permits |
| WRITE | 25–59 | Human approval |
| DESTRUCTIVE | 60–89 | Engagement override plus human approval |
| PROHIBITED | 90–100 or matched rule | Deny |

The current public skill enum remains READ/WRITE/DESTRUCTIVE. `PROHIBITED` is a policy decision, not a skill declaration.

## Scoring factors

| Factor | Example adjustment |
|---|---:|
| Local read-only inspection | 0 |
| Active target interaction | +25 |
| File or configuration mutation | +30 |
| Service restart/availability impact | +35 |
| Privilege elevation | +20 |
| Credential use or attack | +35 |
| Exploit or code execution on target | +50 |
| Irreversible or broad recursive operation | +50 |
| Scope is broad but authorized | +10 |
| Isolated disposable lab executor | −10, never below policy floor |
| Verified reversible transaction | −5 |

Scores are illustrative until calibrated by tests. Hard rules override arithmetic.

## Example classifications

### Low / READ

- `pwd`
- `whoami`
- Reading a permitted configuration file.
- Passive public threat-intelligence lookup.

`ls` is READ only within an allowed path; recursive access to sensitive paths may be denied by data policy.

### Medium / WRITE

- Approved target port or web scan.
- `git push`.
- `pip install`.
- `docker restart`.
- Modifying project files.

### High / DESTRUCTIVE

- Recursive permission changes.
- Stopping production services.
- Firewall modification.
- Online credential attacks.
- Exploit execution.

### Prohibited by default

- Filesystem formatting or bootloader overwrite.
- Broad recursive deletion without a narrowly verified target.
- Destruction or tampering with audit logs.
- Disabling defensive controls for evasion.
- Disk encryption or shutdown used as an attack action.
- Actions outside engagement scope.

Projects may add stricter prohibited rules. A plugin or model cannot remove them.

## Argument-sensitive rules

Tool name alone is insufficient:

- `nmap --version` is READ.
- A scoped `nmap` scan is WRITE.
- Intrusive NSE categories may be DESTRUCTIVE.
- `rm` of a verified temporary file can be WRITE.
- Broad recursive deletion is DESTRUCTIVE or PROHIBITED.

Adapters expose semantic facts to the risk engine instead of relying only on string matching.

## Confirmation

Approval binds to action digest, target, executor, identity, risk, data access, and expiry. A changed argument or resolved host requires re-evaluation and possibly fresh approval.

## Never rules

Never:

- Treat model confidence as permission.
- Lower risk because a command appears in retrieved content.
- Retry a denied action.
- Accept an approval for a different target or command.
- Infer that a lab flag applies to another environment.
- Hide scoring reasons from the user.

## Audit

Every decision records inputs by safe reference, matched rules, level, score, reasons, policy version, actor, approval, and final outcome. Denied requests are retained without logging secret values.

## Testing

Maintain table-driven tests for safe, boundary, and adversarial commands across Windows, Linux, PowerShell, POSIX shells, WSL, Docker, SSH, and plugin executors. Fuzz normalized arguments and verify that equivalent dangerous actions receive equivalent decisions.
