"""Every model request carries the rule that the assistant does not name its model or vendor."""
from app.services.privacy.service import ASSISTANT_IDENTITY_RULE_RU, prepare_llm_outbound


def test_rule_appended_to_existing_system_message_once():
    out = prepare_llm_outbound({"model": "m", "messages": [{"role": "system", "content": "S"}, {"role": "user", "content": "Q"}]})
    assert out["messages"][0]["content"].startswith("S")
    assert out["messages"][0]["content"].count(ASSISTANT_IDENTITY_RULE_RU) == 1
    again = prepare_llm_outbound(out)
    assert again["messages"][0]["content"].count(ASSISTANT_IDENTITY_RULE_RU) == 1


def test_rule_inserted_when_no_system_message():
    out = prepare_llm_outbound({"model": "m", "messages": [{"role": "user", "content": "Q"}]})
    assert out["messages"][0] == {"role": "system", "content": ASSISTANT_IDENTITY_RULE_RU}
    assert out["messages"][1]["content"] == "Q"


def test_payload_without_messages_untouched():
    assert prepare_llm_outbound({"prompt": "x"}) == {"prompt": "x"}
