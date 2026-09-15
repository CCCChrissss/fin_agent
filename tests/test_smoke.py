import json

from financial_annotation_harness.demo import demo_data, judge_pass, search_turn
from financial_annotation_harness.model_client import Turn
from financial_annotation_harness.smoke import run_smoke
from test_screening import FakeProvider, screening_config


class SmokeProvider(FakeProvider):
    def begin_question(self):
        pass
    def describe_request(self, role, seed):
        return {"role": role, "seed": seed}
    def verify_identity(self):
        return {}
    def close(self):
        pass


def test_smoke_judge_fresh_and_no_feedback(tmp_path, rules, prompts):
    artifact = demo_data()[3]
    providers = []
    def factory(*args, **kwargs):
        p = SmokeProvider([Turn(content="malformed"), search_turn(), Turn(content=json.dumps(artifact)), judge_pass()])
        providers.append(p)
        return p
    report = run_smoke(screening_config(), rules, prompts, tmp_path / "smoke", {}, provider_factory=factory)
    assert len(report["results"]) == 6 and len(providers) == 2
    for provider in providers:
        judges = [r for r in provider.requests if r["role"] == "judge"]
        assert len(judges) == 1 and len(judges[0]["messages"]) == 2
        sent = json.dumps(judges)
        assert "malformed" not in sent and "Gold_Answer" not in sent and "validation_feedback" not in sent
    assert all(r["schema_pass"] for r in report["results"] if r["kind"] == "judge")
