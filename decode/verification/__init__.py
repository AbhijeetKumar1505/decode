"""Verification (subsystem 10).

A verify step the agent loop runs before accepting a "done" message: it checks
the task's completion conditions against a context built from the latest
observations and findings. When the objective is not actually met, the loop
surfaces the failure and replans (bounded) instead of reporting false success.
"""

from .verifier import ModelVerifier, VerificationResult, Verifier

__all__ = ["ModelVerifier", "VerificationResult", "Verifier"]
