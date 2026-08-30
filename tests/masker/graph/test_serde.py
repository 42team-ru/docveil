import json
from pathlib import Path

from masker.detect.agent import DetectAgent
from masker.graph.serde import profiles_from_dicts, profiles_to_dicts
from masker.ingest.docx_ingest import ingest_docx
from masker.profile import ProfileAgent

FIXTURES = Path(__file__).parents[3] / "fixtures" / "labeled"


def test_profile_serde_round_trip_is_json_stable() -> None:
    document = ingest_docx(FIXTURES / "contract_01.docx")
    profiles = ProfileAgent().profile(document, DetectAgent().detect(document)).profiles
    serialized = profiles_to_dicts(profiles)
    assert profiles_from_dicts(serialized) == profiles
    assert json.dumps(serialized, ensure_ascii=False, sort_keys=True) == json.dumps(
        profiles_to_dicts(profiles_from_dicts(serialized)), ensure_ascii=False, sort_keys=True
    )
