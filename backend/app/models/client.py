from __future__ import annotations
import json
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

    def __init__(self, fixtures: dict[str, dict[str, Any]] | None = None):
        # fixtures: prompt_substring -> parsed dict
        self.fixtures = fixtures or {}
        self.calls: list[ModelInvocation] = []

    def _record(self, prompt: str, schema_name: str | None) -> ModelInvocation:
        inv = ModelInvocation(provider=self.provider, model_id=self.model_id, prompt=prompt[:2000], schema_name=schema_name, duration_ms=5, input_tokens=len(prompt)//4, output_tokens=50, cost_usd=0.0)
        self.calls.append(inv)
        return inv

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
            except ValidationError as e:
                # Surface validation error as raw invalid output — caller must handle repair/failure
                raw = json.dumps(parsed)
                inv = self._record(prompt, schema.__name__)
                inv.duration_ms = int((time.time()-t0)*1000)
                return ModelOutput(raw=raw, parsed=None, invocation=inv)
            raw = json.dumps(parsed)
            inv = self._record(prompt, schema.__name__)
            inv.duration_ms = int((time.time()-t0)*1000)
            return ModelOutput(raw=raw, parsed=parsed, invocation=inv)
        # No fixture: produce a deterministic placeholder that validates if schema has defaults; else return None to simulate invalid
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
        return FakeModelClient()
    # S1 only supports fake; later S4 will add groq/bedrock adapters behind same interface
    raise ValueError(f"Unsupported model_provider in S1: {s.model_provider}")
