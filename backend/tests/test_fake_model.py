from pydantic import BaseModel
from backend.app.models.client import FakeModelClient

class DummySchema(BaseModel):
    subskill: str
    confidence: str

def test_fake_model_returns_fixture_when_matched():
    fake = FakeModelClient(fixtures={"hello": {"subskill": "FRC-EQUIV", "confidence": "high"}})
    out = fake.generate_structured("say hello world", DummySchema)
    assert out.parsed is not None
    assert out.parsed["subskill"] == "FRC-EQUIV"
    assert out.invocation.provider == "fake"

def test_fake_model_invalid_output_produces_none_parsed():
    fake = FakeModelClient(fixtures={})
    out = fake.generate_structured("unmatched prompt", DummySchema)
    # No fixture -> parsed is None (simulates invalid structured output)
    assert out.parsed is None
    assert "fake" in out.raw

def test_fake_model_records_calls():
    fake = FakeModelClient()
    fake.generate_text("hi")
    assert len(fake.calls) == 1
