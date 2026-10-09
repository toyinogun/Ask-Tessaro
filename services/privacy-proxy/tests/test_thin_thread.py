"""The tracer bullet: one conversation through every layer (spec 0006 AC-1, AC-4, AC-5, AC-7)."""

import json

from .conftest import CONVERSATION, Json, Proxy, answer, everything_in, tool_call, user


async def test_daan_is_masked_both_turns_and_restored_in_tool_arguments(proxy: Proxy) -> None:
    """covers: AC-1, AC-4, AC-5, AC-7 (happy path from the spec's critical scenarios)"""
    proxy.upstream.reply = lambda _body: answer(
        tool_calls=[tool_call("get_colleague", {"name": "<PERSON_1>"})]
    )
    first = await proxy.chat([user("Is Daan de Wit in the office today?")])
    assert first.status_code == 200
    sent = proxy.upstream.bodies[0]
    assert sent["messages"][0]["content"] == "Is <PERSON_1> in the office today?"
    arguments = first.json()["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
    assert json.loads(arguments) == {"name": "Daan de Wit"}

    proxy.upstream.reply = lambda _body: answer("<PERSON_1> works from Amsterdam today.")
    history: list[Json] = [
        user("Is Daan de Wit in the office today?"),
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [tool_call("get_colleague", {"name": "Daan de Wit"})],
        },
        {"role": "tool", "tool_call_id": "call-1", "content": '{"name": "Daan de Wit"}'},
    ]
    second = await proxy.chat(history)
    assert second.json()["choices"][0]["message"]["content"] == (
        "Daan de Wit works from Amsterdam today."
    )
    outgoing = everything_in(proxy.upstream.bodies[1])
    assert "Daan" not in outgoing
    assert "Wit" not in outgoing
    assert outgoing.count("<PERSON_1>") == 3
    assert proxy.upstream.requests[1].headers["Authorization"] == "Bearer upstream-secret"


async def test_a_turn_naming_only_the_first_name_restores_the_full_name(proxy: Proxy) -> None:
    """covers: AC-7 (a directory employee's placeholder restores to the display name)"""
    proxy.upstream.reply = lambda _body: answer(
        tool_calls=[tool_call("get_colleague", {"name": "<PERSON_1>"})]
    )
    response = await proxy.chat([user("Where is Daan?")], conversation=CONVERSATION + "-x")
    arguments = response.json()["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
    assert json.loads(arguments) == {"name": "Daan de Wit"}
