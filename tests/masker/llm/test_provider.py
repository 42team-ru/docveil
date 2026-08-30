from masker.llm import FakeProvider, Message


def test_fake_provider_is_scriptable_and_deterministic() -> None:
    provider = FakeProvider(["result", "result"])
    messages = [Message("user", "test")]
    assert provider.complete(messages) == "result"
    assert provider.complete(messages) == "result"
    assert provider.calls == 2
