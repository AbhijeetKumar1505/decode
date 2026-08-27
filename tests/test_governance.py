import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import ValidationError

from decode.governance import ScopePolicy, GovernanceGate, Decision
from decode.audit import AuditLayer
from decode.feedback import FeedbackStore
from decode.logging_service import LoggingService
from decode.runtime import (
    ApprovalGrant,
    credential_refs_from_params,
    ExecutionCoordinator,
    ExecutionErrorCategory,
    ExecutionIdentity,
    ExecutionRequest,
    ExecutionStatus,
    redact_sensitive,
)
from decode.persistence.evidence import ProtectedEvidenceStore
from decode.skills.base import RiskLevel


class TestScopePolicy(unittest.TestCase):
    def test_cidr_membership(self):
        p = ScopePolicy(allowed=["10.0.0.0/24"])
        self.assertTrue(p.is_in_scope("10.0.0.5"))
        self.assertFalse(p.is_in_scope("10.0.1.5"))

    def test_exact_host(self):
        p = ScopePolicy(allowed=["target.example.com"])
        self.assertTrue(p.is_in_scope("target.example.com"))
        self.assertFalse(p.is_in_scope("other.example.com"))

    def test_wildcard_domain(self):
        p = ScopePolicy(allowed=["*.example.com"])
        self.assertTrue(p.is_in_scope("app.example.com"))
        self.assertTrue(p.is_in_scope("example.com"))
        self.assertFalse(p.is_in_scope("example.org"))

    def test_url_target_extracts_host(self):
        p = ScopePolicy(allowed=["example.com"])
        self.assertTrue(p.is_in_scope("https://example.com/app?x=1"))

    def test_host_with_port(self):
        p = ScopePolicy(allowed=["10.0.0.0/24"])
        self.assertTrue(p.is_in_scope("10.0.0.5:8080"))

    def test_cidr_subnet_target(self):
        p = ScopePolicy(allowed=["10.0.0.0/16"])
        self.assertTrue(p.is_in_scope("10.0.5.0/24"))
        self.assertFalse(p.is_in_scope("11.0.0.0/24"))

    def test_empty_scope_denies_all(self):
        p = ScopePolicy(allowed=[])
        self.assertFalse(p.is_in_scope("10.0.0.5"))

    def test_allow_all(self):
        self.assertTrue(ScopePolicy(allow_all=True).is_in_scope("anything.at.all"))


class TestGovernanceGate(unittest.TestCase):
    def _gate(self, allowed=None, allow_all=False, allow_destructive=False):
        self.tmp = tempfile.mkdtemp()
        audit = AuditLayer(base_path=Path(self.tmp))
        gate = GovernanceGate(
            ScopePolicy(allowed=allowed, allow_all=allow_all),
            audit=audit, allow_destructive=allow_destructive,
        )
        return gate, audit

    def test_out_of_scope_denied_and_audited(self):
        gate, audit = self._gate(allowed=["10.0.0.0/24"])
        d = gate.evaluate("port_scan", "8.8.8.8", "WRITE")
        self.assertEqual(d.decision, Decision.DENY)
        self.assertTrue(any(e.event == "rejection" for e in audit.query()))

    def test_read_in_scope_auto_allows(self):
        gate, _ = self._gate(allowed=["example.com"])
        d = gate.evaluate("subdomain_enum", "example.com", "READ")
        self.assertEqual(d.decision, Decision.ALLOW)

    def test_write_in_scope_needs_approval(self):
        gate, _ = self._gate(allowed=["10.0.0.0/24"])
        d = gate.evaluate("port_scan", "10.0.0.5", "WRITE")
        self.assertEqual(d.decision, Decision.NEEDS_APPROVAL)

    def test_destructive_denied_without_override(self):
        gate, audit = self._gate(allowed=["10.0.0.0/24"], allow_destructive=False)
        d = gate.evaluate("sql_injection", "10.0.0.5", "DESTRUCTIVE")
        self.assertEqual(d.decision, Decision.DENY)
        self.assertTrue(any(e.event == "rejection" for e in audit.query()))

    def test_destructive_denial_redacts_target_secret(self):
        gate, audit = self._gate(allow_all=True, allow_destructive=False)
        target = "https://example.test/?token=synthetic-secret"

        decision = gate.evaluate("sql_injection", target, "DESTRUCTIVE")

        self.assertEqual(decision.decision, Decision.DENY)
        serialized = " ".join(event.model_dump_json() for event in audit.query())
        self.assertNotIn("synthetic-secret", serialized)
        self.assertIn("token=[REDACTED]", serialized)

    def test_destructive_with_override_needs_approval(self):
        gate, _ = self._gate(allowed=["10.0.0.0/24"], allow_destructive=True)
        d = gate.evaluate("sql_injection", "10.0.0.5", "DESTRUCTIVE")
        self.assertEqual(d.decision, Decision.NEEDS_APPROVAL)

    def test_missing_required_target_denied_even_when_allow_all(self):
        gate, audit = self._gate(allow_all=True)
        decision = gate.evaluate(
            "port_scan",
            "",
            "WRITE",
            target_required=True,
        )

        self.assertEqual(decision.decision, Decision.DENY)
        self.assertIn("target is required", decision.reason)
        self.assertTrue(any(event.event == "rejection" for event in audit.query()))


    def test_scope_beats_risk(self):
        # Even a READ capability is denied when the target is out of scope.
        gate, _ = self._gate(allowed=["10.0.0.0/24"])
        d = gate.evaluate("subdomain_enum", "evil.com", "READ")
        self.assertEqual(d.decision, Decision.DENY)


class _FailingAudit:
    def __init__(self, base_path: Path) -> None:
        self.base_path = base_path

    def record(self, event) -> str:
        raise OSError("audit unavailable")


class _FailingEvidenceStore:
    def capture(self, data: object, *, evidence_id: str = "") -> None:
        raise OSError("evidence unavailable")


class TestExecutionCoordinator(unittest.TestCase):
    def _services(self, root: Path):
        audit = AuditLayer(root / "audit")
        logging = LoggingService(root / "logs")
        feedback = FeedbackStore(root / "feedback")
        return audit, logging, feedback

    def test_in_scope_write_requires_bound_approval_and_records_telemetry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit, logging, feedback = self._services(root)
            approvals = []
            executed = []

            async def approve(request):
                approvals.append(request)
                return True

            async def operation():
                executed.append(True)
                return {"ok": True}

            coordinator = ExecutionCoordinator(
                GovernanceGate(ScopePolicy(["192.0.2.10"]), audit=audit),
                approval_callback=approve,
                logging_service=logging,
                audit=audit,
                feedback=feedback,
            )
            request = ExecutionRequest(
                action="port_scan",
                target="192.0.2.10",
                risk=RiskLevel.WRITE,
                params={"target": "192.0.2.10", "ports": "80,443"},
                command="nmap -p 80,443 192.0.2.10",
                executor="local",
                required_privileges=["elevated"],
                credential_refs=["vault:scan-profile"],
                execution_identity=ExecutionIdentity(
                    tool="nmap",
                    tool_version="7.95",
                    adapter_id="builtin.nmap",
                    adapter_version="1.0.0",
                ),
            )
            result = asyncio.run(coordinator.execute(request, operation))

            self.assertTrue(result.success)
            self.assertEqual(executed, [True])
            self.assertEqual(approvals[0].digest, request.approval_digest())
            self.assertEqual(approvals[0].executor, "local")
            self.assertEqual(approvals[0].required_privileges, ["elevated"])
            self.assertEqual(approvals[0].credential_refs, ["vault:scan-profile"])
            self.assertEqual(approvals[0].execution_identity.tool, "nmap")
            self.assertEqual(
                approvals[0].execution_identity.adapter_version,
                "1.0.0",
            )
            self.assertGreater(approvals[0].expires_at, datetime.now(timezone.utc))
            self.assertIsNotNone(result.evidence)
            evidence_store = ProtectedEvidenceStore(root / "evidence" / "executions")
            self.assertTrue(evidence_store.verify(result.evidence))
            self.assertTrue(
                any(event.event == "tool_execution" for event in audit.query())
            )
            execution_log = logging.get_logs()[0]
            self.assertEqual(execution_log["command"], "[redacted]")
            self.assertEqual(execution_log["output_file"], result.evidence.path)
            self.assertTrue(feedback.get_execution_feedback("port_scan")[0]["success"])

    def test_approval_prompt_redacts_secret_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit, logging, feedback = self._services(root)
            approvals = []

            async def approve(request):
                approvals.append(request)
                return True

            async def operation():
                return {"ok": True}

            coordinator = ExecutionCoordinator(
                GovernanceGate(ScopePolicy(allow_all=True), audit=audit),
                approval_callback=approve,
                logging_service=logging,
                audit=audit,
                feedback=feedback,
            )
            result = asyncio.run(
                coordinator.execute(
                    ExecutionRequest(
                        action="credential_check",
                        risk=RiskLevel.WRITE,
                        params={
                            "password": "synthetic-secret",
                            "nested": {"api_key": "synthetic-key"},
                        },
                        command="check password=synthetic-secret",
                        credential_refs=["request-param:password"],
                    ),
                    operation,
                )
            )

            self.assertTrue(result.success)
            self.assertEqual(approvals[0].params["password"], "[REDACTED]")
            self.assertEqual(approvals[0].params["nested"]["api_key"], "[REDACTED]")
            self.assertNotIn("synthetic-secret", approvals[0].command)

    def test_mismatched_or_expired_approval_never_executes(self):
        cases = ["mismatched", "expired"]
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                audit, logging, feedback = self._services(root)
                executed = []

                async def approve(request):
                    now = datetime.now(timezone.utc)
                    return ApprovalGrant(
                        digest="0" * 64 if case == "mismatched" else request.digest,
                        approved_at=now - timedelta(seconds=2),
                        expires_at=(
                            now + timedelta(seconds=30)
                            if case == "mismatched"
                            else now - timedelta(seconds=1)
                        ),
                    )

                async def operation():
                    executed.append(True)

                coordinator = ExecutionCoordinator(
                    GovernanceGate(ScopePolicy(allow_all=True), audit=audit),
                    approval_callback=approve,
                    logging_service=logging,
                    audit=audit,
                    feedback=feedback,
                )
                result = asyncio.run(
                    coordinator.execute(
                        ExecutionRequest(
                            action="write_action",
                            risk=RiskLevel.WRITE,
                        ),
                        operation,
                    )
                )

                expected = (
                    ExecutionErrorCategory.APPROVAL_INVALID
                    if case == "mismatched"
                    else ExecutionErrorCategory.APPROVAL_EXPIRED
                )
                self.assertEqual(result.error_category, expected)
                self.assertEqual(executed, [])

    def test_material_change_after_approval_never_executes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit, logging, feedback = self._services(root)
            executed = []
            request = ExecutionRequest(
                action="port_scan",
                target="192.0.2.10",
                risk=RiskLevel.WRITE,
                params={"ports": "80"},
            )

            async def approve(_):
                request.params["ports"] = "443"
                return True

            async def operation():
                executed.append(True)

            coordinator = ExecutionCoordinator(
                GovernanceGate(ScopePolicy(allow_all=True), audit=audit),
                approval_callback=approve,
                logging_service=logging,
                audit=audit,
                feedback=feedback,
            )
            result = asyncio.run(coordinator.execute(request, operation))

            self.assertEqual(
                result.error_category,
                ExecutionErrorCategory.APPROVAL_INVALID,
            )
            self.assertEqual(executed, [])

    def test_out_of_scope_request_never_calls_operation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit, logging, feedback = self._services(root)
            executed = []

            async def operation():
                executed.append(True)

            coordinator = ExecutionCoordinator(
                GovernanceGate(ScopePolicy(["192.0.2.0/24"]), audit=audit),
                logging_service=logging,
                audit=audit,
                feedback=feedback,
            )
            request = ExecutionRequest(
                action="port_scan",
                target="198.51.100.10",
                risk=RiskLevel.WRITE,
            )
            result = asyncio.run(coordinator.execute(request, operation))

            self.assertEqual(result.status, ExecutionStatus.DENIED)
            self.assertEqual(result.error_category, ExecutionErrorCategory.POLICY_DENIAL)
            self.assertEqual(executed, [])
            self.assertTrue(logging.get_logs())
            self.assertTrue(feedback.get_execution_feedback("port_scan"))

    def test_missing_required_target_never_calls_operation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit, logging, feedback = self._services(root)
            executed = []

            async def operation():
                executed.append(True)

            coordinator = ExecutionCoordinator(
                GovernanceGate(ScopePolicy(allow_all=True), audit=audit),
                logging_service=logging,
                audit=audit,
                feedback=feedback,
            )
            result = asyncio.run(
                coordinator.execute(
                    ExecutionRequest(
                        action="port_scan",
                        target_required=True,
                        risk=RiskLevel.WRITE,
                    ),
                    operation,
                )
            )

            self.assertEqual(result.status, ExecutionStatus.DENIED)
            self.assertEqual(
                result.error_category,
                ExecutionErrorCategory.POLICY_DENIAL,
            )
            self.assertEqual(executed, [])
            self.assertTrue(logging.get_logs())
            self.assertTrue(feedback.get_execution_feedback("port_scan"))


    def test_missing_dependency_blocks_before_governance_and_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit, logging, feedback = self._services(root)
            executed = []

            async def operation():
                executed.append(True)

            coordinator = ExecutionCoordinator(
                GovernanceGate(ScopePolicy(["192.0.2.10"]), audit=audit),
                logging_service=logging,
                audit=audit,
                feedback=feedback,
            )
            result = asyncio.run(
                coordinator.execute(
                    ExecutionRequest(
                        action="vuln_scan",
                        target="192.0.2.10",
                        dependency="nuclei",
                        dependency_available=False,
                        dependency_guidance=(
                            "Required dependency missing: nuclei; install separately"
                        ),
                    ),
                    operation,
                )
            )

            self.assertEqual(result.status, ExecutionStatus.BLOCKED)
            self.assertEqual(
                result.error_category,
                ExecutionErrorCategory.MISSING_DEPENDENCY,
            )
            self.assertEqual(executed, [])
            rows = feedback.get_execution_feedback("vuln_scan")
            self.assertTrue(rows[0]["dependency_missing"])

    def test_write_without_approval_is_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit, logging, feedback = self._services(root)
            executed = []

            async def operation():
                executed.append(True)

            coordinator = ExecutionCoordinator(
                GovernanceGate(ScopePolicy(["192.0.2.10"]), audit=audit),
                logging_service=logging,
                audit=audit,
                feedback=feedback,
            )
            result = asyncio.run(
                coordinator.execute(
                    ExecutionRequest(
                        action="port_scan",
                        target="192.0.2.10",
                        risk=RiskLevel.WRITE,
                    ),
                    operation,
                )
            )

            self.assertEqual(result.status, ExecutionStatus.DENIED)
            self.assertEqual(
                result.error_category,
                ExecutionErrorCategory.APPROVAL_REQUIRED,
            )
            self.assertEqual(executed, [])

    def test_audit_failure_prevents_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit = _FailingAudit(root / "audit")
            logging = LoggingService(root / "logs")
            feedback = FeedbackStore(root / "feedback")
            executed = []

            async def operation():
                executed.append(True)

            coordinator = ExecutionCoordinator(
                GovernanceGate(ScopePolicy(["192.0.2.10"]), audit=audit),
                logging_service=logging,
                audit=audit,
                feedback=feedback,
            )
            result = asyncio.run(
                coordinator.execute(
                    ExecutionRequest(
                        action="safe_lookup",
                        target="192.0.2.10",
                        risk=RiskLevel.READ,
                    ),
                    operation,
                )
            )

            self.assertEqual(
                result.error_category,
                ExecutionErrorCategory.TELEMETRY_FAILURE,
            )
            self.assertEqual(executed, [])

    def test_evidence_failure_marks_execution_failed_and_hides_value(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit, logging, feedback = self._services(root)

            async def operation():
                return {"raw_output": "synthetic output"}

            coordinator = ExecutionCoordinator(
                GovernanceGate(ScopePolicy(allow_all=True), audit=audit),
                logging_service=logging,
                audit=audit,
                feedback=feedback,
                evidence_store=_FailingEvidenceStore(),
            )
            result = asyncio.run(
                coordinator.execute(
                    ExecutionRequest(action="safe_lookup", risk=RiskLevel.READ),
                    operation,
                )
            )

            self.assertFalse(result.success)
            self.assertIsNone(result.value)
            self.assertEqual(
                result.error_category,
                ExecutionErrorCategory.TELEMETRY_FAILURE,
            )

    def test_execution_errors_are_redacted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit, logging, feedback = self._services(root)

            async def operation():
                raise RuntimeError("token=super-secret-value")

            coordinator = ExecutionCoordinator(
                GovernanceGate(ScopePolicy(allow_all=True), audit=audit),
                logging_service=logging,
                audit=audit,
                feedback=feedback,
            )
            result = asyncio.run(
                coordinator.execute(
                    ExecutionRequest(
                        action="safe_lookup",
                        risk=RiskLevel.READ,
                    ),
                    operation,
                )
            )

            self.assertEqual(result.status, ExecutionStatus.ERROR)
            self.assertIn("token=[REDACTED]", result.error)
            self.assertNotIn("super-secret-value", result.error)
            terminal = [
                event for event in audit.query() if event.event == "tool_execution"
            ]
            self.assertTrue(terminal)
            self.assertTrue(terminal[-1].approved)

    def test_timeout_is_distinct_and_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit, logging, feedback = self._services(root)

            async def operation():
                raise asyncio.TimeoutError

            coordinator = ExecutionCoordinator(
                GovernanceGate(ScopePolicy(allow_all=True), audit=audit),
                logging_service=logging,
                audit=audit,
                feedback=feedback,
            )
            result = asyncio.run(
                coordinator.execute(
                    ExecutionRequest(action="safe_lookup", risk=RiskLevel.READ),
                    operation,
                )
            )

            self.assertEqual(result.status, ExecutionStatus.TIMEOUT)
            self.assertEqual(result.error_category, ExecutionErrorCategory.TIMEOUT)
            self.assertEqual(
                feedback.get_execution_feedback("safe_lookup")[0]["error"],
                "timeout",
            )

    def test_cancellation_is_recorded_and_propagated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit, logging, feedback = self._services(root)

            async def operation():
                raise asyncio.CancelledError

            coordinator = ExecutionCoordinator(
                GovernanceGate(ScopePolicy(allow_all=True), audit=audit),
                logging_service=logging,
                audit=audit,
                feedback=feedback,
            )
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(
                    coordinator.execute(
                        ExecutionRequest(
                            action="safe_lookup",
                            risk=RiskLevel.READ,
                        ),
                        operation,
                    )
                )

            self.assertEqual(
                feedback.get_execution_feedback("safe_lookup")[0]["error"],
                "cancellation",
            )
            self.assertTrue(audit.query())
            self.assertTrue(logging.get_logs())

    def test_terminal_paths_emit_all_mandatory_telemetry(self):
        cases = {
            "success": ({}, "success"),
            "blocked": ({"dependency_available": False}, "blocked"),
            "approval_required": ({"risk": RiskLevel.WRITE}, "denied"),
        }
        for name, (updates, expected_status) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                audit, logging, feedback = self._services(root)

                async def operation():
                    return {"case": name}

                coordinator = ExecutionCoordinator(
                    GovernanceGate(ScopePolicy(allow_all=True), audit=audit),
                    logging_service=logging,
                    audit=audit,
                    feedback=feedback,
                )
                request_data = {
                    "action": f"case_{name}",
                    "risk": RiskLevel.READ,
                    **updates,
                }
                request = ExecutionRequest(**request_data)
                result = asyncio.run(coordinator.execute(request, operation))

                self.assertEqual(result.status.value, expected_status)
                self.assertTrue(audit.query())
                self.assertTrue(logging.get_logs(tool_filter=request.action))
                self.assertTrue(feedback.get_execution_feedback(request.action))

    def test_approval_digest_changes_with_material_parameters(self):
        first = ExecutionRequest(
            action="port_scan",
            target="192.0.2.10",
            params={"ports": "80"},
            executor="local",
        )
        second = first.model_copy(update={"params": {"ports": "443"}})
        self.assertNotEqual(first.approval_digest(), second.approval_digest())

    def test_approval_digest_binds_privilege_credentials_and_expiry(self):
        expiry = datetime.now(timezone.utc) + timedelta(minutes=5)
        base = ExecutionRequest(
            action="port_scan",
            target="192.0.2.10",
            approval_expires_at=expiry,
        )
        variants = [
            base.model_copy(update={"required_privileges": ["root"]}),
            base.model_copy(update={"credential_refs": ["vault:scan"]}),
            base.model_copy(
                update={
                    "execution_identity": ExecutionIdentity(
                        tool="nmap",
                        tool_version="7.95",
                        adapter_id="builtin.nmap",
                        adapter_version="1.0.0",
                    )
                }
            ),
            base.model_copy(
                update={"approval_expires_at": expiry + timedelta(seconds=1)}
            ),
        ]

        for variant in variants:
            self.assertNotEqual(base.approval_digest(), variant.approval_digest())

    def test_credential_reference_rejects_secret_material(self):
        with self.assertRaises(ValidationError):
            ExecutionRequest(
                action="credential_check",
                credential_refs=["raw secret value"],
            )

    def test_secret_redaction_and_credential_reference_derivation(self):
        params = {
            "target": "example.test",
            "api_key": "synthetic-key",
            "nested": {"password": "synthetic-password"},
        }

        redacted = redact_sensitive(params)

        self.assertEqual(redacted["api_key"], "[REDACTED]")
        self.assertEqual(redacted["nested"]["password"], "[REDACTED]")
        self.assertEqual(
            credential_refs_from_params(params),
            ["request-param:api_key"],
        )
if __name__ == "__main__":
    unittest.main()
