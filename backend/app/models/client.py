from __future__ import annotations
import ast
import json
import re
import time
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ValidationError

class ModelInvocation(BaseModel):
    provider: str
    model_id: str
    prompt: str
    schema_name: str | None = None
    duration_ms: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None

class ModelOutput(BaseModel):
    raw: str
    parsed: dict[str, Any] | None = None
    invocation: ModelInvocation

class ModelClient(ABC):
    provider: str
    model_id: str

    @abstractmethod
    def generate_structured(self, prompt: str, schema: type[BaseModel], **kwargs: Any) -> ModelOutput:
        ...

    @abstractmethod
    def generate_text(self, prompt: str, **kwargs: Any) -> ModelOutput:
        ...

class FakeModelClient(ModelClient):
    """Deterministic fake provider for S1 contract tests. No network."""

    provider = "fake"
    model_id = "fake-diagnostic-v1"

    def __init__(
        self,
        fixtures: dict[str, dict[str, Any]] | None = None,
        model_id: str | None = None,
    ):
        # fixtures: prompt_substring -> parsed dict
        self.fixtures = fixtures or {}
        self.model_id = model_id or type(self).model_id
        self.calls: list[ModelInvocation] = []

    def _record(self, prompt: str, schema_name: str | None) -> ModelInvocation:
        inv = ModelInvocation(
            provider=self.provider,
            model_id=self.model_id,
            prompt=prompt[:2000],
            schema_name=schema_name,
            duration_ms=5,
            input_tokens=None,
            output_tokens=None,
            cost_usd=0.0,
        )
        self.calls.append(inv)
        return inv

    def _default_fixture(self, prompt: str, schema: type[BaseModel]) -> dict[str, Any] | None:
        """Return a deterministic demo proposal for the real API path.

        Tests can still provide explicit fixtures. This fallback keeps the
        local vertical slice runnable without pretending to call a provider.
        """
        if schema.__name__ != "MasteryProposal":
            return None
        student_match = re.search(r"student ([^ ]+) subskill", prompt)
        subskill_match = re.search(r"subskill ([^\.]+)\. Evidence IDs:", prompt)
        state_match = re.search(r"label=([a-z_]+) confidence=([0-9.]+)", prompt)
        evidence_match = re.search(r"Evidence IDs: (\[.*?\])\. Deterministic", prompt)
        policy_match = re.search(r"policy_id=([^ ]+) policy_version=([^ ]+)\.", prompt)
        if not (student_match and subskill_match and state_match and evidence_match and policy_match):
            return None
        try:
            evidence_ids = ast.literal_eval(evidence_match.group(1))
        except (SyntaxError, ValueError):
            return None
        label = state_match.group(1)
        return {
            "student_id": student_match.group(1),
            "subskill_id": subskill_match.group(1),
            "status": "needs_more_evidence" if label == "insufficient_evidence" else "pending_tutor_review",
            "label": label,
            "confidence": float(state_match.group(2)),
            "evidence_ids": evidence_ids,
            "policy_id": policy_match.group(1),
            "policy_version": policy_match.group(2),
            "reason": f"Evidence {evidence_ids} supports {label}; policy version {policy_match.group(2)} was applied.",
            "alternative_explanation": None,
            "recommended_next_action": "collect_more_evidence" if label == "insufficient_evidence" else "assign_targeted_practice",
            "source_refs": [],
        }

    def generate_structured(self, prompt: str, schema: type[BaseModel], **kwargs: Any) -> ModelOutput:
        t0 = time.time()
        # Try to find a matching fixture by substring; otherwise return a minimal valid instance via schema defaults if possible
        parsed: dict[str, Any] | None = None
        for key, value in self.fixtures.items():
            if key in prompt:
                parsed = value
                break
        if parsed is not None:
            try:
                schema.model_validate(parsed)
            except ValidationError:
                # Surface validation error as raw invalid output — caller must handle repair/failure
                raw = json.dumps(parsed)
                inv = self._record(prompt, schema.__name__)
                inv.duration_ms = int((time.time()-t0)*1000)
                return ModelOutput(raw=raw, parsed=None, invocation=inv)
            raw = json.dumps(parsed)
            inv = self._record(prompt, schema.__name__)
            inv.duration_ms = int((time.time()-t0)*1000)
            return ModelOutput(raw=raw, parsed=parsed, invocation=inv)
        default = self._default_fixture(prompt, schema)
        if default is not None:
            schema.model_validate(default)
            raw = json.dumps(default)
            inv = self._record(prompt, schema.__name__)
            inv.duration_ms = int((time.time()-t0)*1000)
            return ModelOutput(raw=raw, parsed=default, invocation=inv)
        # No fixture: produce a deterministic invalid response for contract tests.
        try:
            # Try to instantiate with minimal required fields missing — will fail
            # Instead we return a raw that is clearly invalid so caller can test repair path
            raw = json.dumps({"_fake": "no_fixture_for_prompt"})
            inv = self._record(prompt, schema.__name__)
            inv.duration_ms = int((time.time()-t0)*1000)
            # Attempt to parse; if fails, parsed stays None
            try:
                schema.model_validate_json(raw)
                parsed = json.loads(raw)
            except ValidationError:
                parsed = None
            return ModelOutput(raw=raw, parsed=parsed, invocation=inv)
        except Exception:
            raw = json.dumps({"error": "fake_no_fixture"})
            inv = self._record(prompt, schema.__name__)
            return ModelOutput(raw=raw, parsed=None, invocation=inv)

    def generate_text(self, prompt: str, **kwargs: Any) -> ModelOutput:
        t0 = time.time()
        raw = self.fixtures.get("__text__", {}).get(prompt[:50], "Fake text response for tests.")
        if isinstance(raw, dict):
            raw = json.dumps(raw)
        inv = self._record(prompt, None)
        inv.duration_ms = int((time.time()-t0)*1000)
        return ModelOutput(raw=str(raw), parsed=None, invocation=inv)

def get_model_client() -> ModelClient:
    from backend.app.config import get_settings
    s = get_settings()
    if s.model_provider == "fake":
        return FakeModelClient(model_id=s.model_id)
    # S1 only supports fake; later S4 will add groq/bedrock adapters behind same interface
    raise ValueError(f"Unsupported model_provider in S1: {s.model_provider}")
