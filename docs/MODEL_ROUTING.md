# Model Gateway and Routing

**Status:** Current adapters/registry/routing are foundations; UTOS owns v2 strategy

Gateway normalizes requests, responses, streaming, errors, capabilities, and
usage. It does not choose workflows, authorize tools, or declare completion.

Logical roles: core, worker, reasoning, security, reviewer, summarizer, fast.
Providers/models are selected under policy without changing methodology.

Hard filters: data class, locality/retention, capabilities/context, health,
pinning, budget. No fallback crosses trust boundaries or repeats external tools.

Optimization uses decision type/locality, difficulty, phase, quality history,
context, latency/cost/budget, and health. UTOS records public reason/rules.

Preserve provider token categories; unknown stays unknown. Record provider/model/
version/context manifest. Reservations reconcile after response.

Retry only safe bounded inference. Fallback stays in compatible groups. Model
failure never repeats an external action.

Current `models/` and `kernel/provider.py` remain foundations; v2 moves
strategy behind [UTOS.md](UTOS.md).
