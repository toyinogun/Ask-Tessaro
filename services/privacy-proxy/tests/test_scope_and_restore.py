"""What gets masked and what comes back (spec 0006 AC-2, AC-3, AC-7)."""

import json

import pytest

from tessaro_privacy_proxy.analyzer.fake import FakeAnalyzer
from tessaro_privacy_proxy.mapping.redis_store import RedisMappingStore
from tessaro_privacy_proxy.masking.directory import Directory, DirectoryEntry
from tessaro_privacy_proxy.masking.mask import Masker
from tessaro_privacy_proxy.masking.models import ChatRequest

from .conftest import Json, Proxy, ProxyFactory, answer, everything_in, tool_call, user


async def test_every_message_part_is_masked_and_name_and_user_dropped(proxy: Proxy) -> None:
    """covers: AC-2"""
    messages: list[Json] = [
        {"role": "system", "content": "You help TES-01005."},
        {"role": "user", "name": "Daan", "content": [{"type": "text", "text": "I am Daan."}]},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                tool_call("lookup", {"who": ["Daan de Wit", 7, True], "Daan": None}),
                tool_call("raw", "not json, Daan de Wit", call_id="call-2"),
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call-1",
            "content": '{"email": "daan.dewit@tessaro.example"}',
        },
    ]
    tools = [{"type": "function", "function": {"name": "lookup", "description": "Find Daan"}}]
    response = await proxy.chat(messages, user="Daan", tools=tools, temperature=0.2, stream=False)
    assert response.status_code == 200
    sent = proxy.upstream.bodies[0]
    assert sent["tools"] == tools  # trusted static content, passed through as written
    assert sent["temperature"] == 0.2
    assert sent["stream"] is False
    assert "user" not in sent
    assert all("name" not in m for m in sent["messages"])
    arguments = json.loads(sent["messages"][2]["tool_calls"][0]["function"]["arguments"])
    assert arguments == {"who": ["<PERSON_1>", 7, True], "Daan": None}  # keys are never masked
    rest = {**sent, "tools": None}
    rest["messages"] = [m for i, m in enumerate(sent["messages"]) if i != 2]
    assert "Daan" not in everything_in(rest)
    assert "TES-01005" not in everything_in(rest)
    assert sent["messages"][2]["tool_calls"][1]["function"]["arguments"] == "not json, <PERSON_1>"
    assert sent["messages"][3] == {
        "role": "tool",
        "content": '{"email": "<EMAIL_ADDRESS_1>"}',
        "tool_call_id": "call-1",
    }


async def test_only_the_name_is_masked_in_a_useful_sentence(make_proxy: ProxyFactory) -> None:
    """covers: AC-3 (FR-P6: dates, amounts, cities and teams stay readable)"""
    proxy = make_proxy(analyzer=FakeAnalyzer.finding([("PERSON", "Daan de Wit")]))
    sentence = "Daan de Wit's Berlin claim of €120.50 from 3 March for the Payments team"
    await proxy.chat([user(sentence)])
    assert proxy.upstream.bodies[0]["messages"][0]["content"] == (
        "<PERSON_1>'s Berlin claim of €120.50 from 3 March for the Payments team"
    )


async def test_analyzer_hits_below_the_threshold_or_of_other_types_are_ignored(
    make_proxy: ProxyFactory,
) -> None:
    """covers: AC-3"""
    weak = FakeAnalyzer.finding([("PERSON", "Zebedeus Quist")], score=0.3)
    await make_proxy(analyzer=weak).chat([user("ask Zebedeus Quist")])
    other = FakeAnalyzer.finding([("LOCATION", "Berlin")])
    proxy = make_proxy(analyzer=other)
    await proxy.chat([user("trip to Berlin")])
    sent = [b["messages"][0]["content"] for b in proxy.upstream.bodies]
    assert sent == ["ask Zebedeus Quist", "trip to Berlin"]


async def test_restore_covers_content_refusal_and_arguments_in_one_pass(proxy: Proxy) -> None:
    """covers: AC-7"""
    await proxy.chat([user("Daan de Wit, TES-01005")])  # issues <PERSON_1>, <EMPLOYEE_ID_1>
    reply = answer("<PERSON_1> (<EMPLOYEE_ID_1>) and <person_1>, <PERSON_1")
    reply["choices"][0]["message"]["refusal"] = "Not for <PERSON_1>"
    reply["choices"][0]["message"]["reasoning_content"] = "thinking about <PERSON_1>"
    reply["choices"][0]["message"]["tool_calls"] = [
        tool_call("a", {"id": "<EMPLOYEE_ID_1>", "n": 3}),
        tool_call("b", "<PERSON_1> raw", call_id="call-2"),
    ]
    reply["choices"][0]["logprobs"] = {"content": [{"token": "<PERSON_1>"}]}
    proxy.upstream.reply = lambda _body: reply
    body = (await proxy.chat([user("again")])).json()
    message = body["choices"][0]["message"]
    assert message["content"] == "Daan de Wit (TES-01005) and <person_1>, <PERSON_1"
    assert message["refusal"] == "Not for Daan de Wit"
    assert "reasoning_content" not in message
    assert "logprobs" not in body["choices"][0]
    assert json.loads(message["tool_calls"][0]["function"]["arguments"]) == {
        "id": "TES-01005",
        "n": 3,
    }
    assert message["tool_calls"][1]["function"]["arguments"] == "Daan de Wit raw"


async def test_restored_text_is_never_expanded_again(make_proxy: ProxyFactory) -> None:
    """covers: AC-7 (a restored value that looks like a placeholder stays as it is)"""
    sneaky = FakeAnalyzer.finding([("PERSON", "<PERSON_2> Quist")])
    proxy = make_proxy(analyzer=sneaky)
    await proxy.chat([user("Daan de Wit met <PERSON_2> Quist")])
    assert proxy.upstream.bodies[0]["messages"][0]["content"] == "<PERSON_1> met <PERSON_2>"
    proxy.upstream.reply = lambda _body: answer("<PERSON_2> and <PERSON_1>")
    body = (await proxy.chat([user("hi")])).json()
    assert body["choices"][0]["message"]["content"] == "<PERSON_2> Quist and Daan de Wit"


async def test_an_unissued_placeholder_is_left_and_logged(
    proxy: Proxy, capsys: pytest.CaptureFixture[str]
) -> None:
    """covers: AC-7"""
    proxy.upstream.reply = lambda _body: answer("ask <PERSON_9>")
    body = (await proxy.chat([user("hi")])).json()
    assert body["choices"][0]["message"]["content"] == "ask <PERSON_9>"
    logs = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    warning = next(e for e in logs if e["event"] == "unknown_placeholder")
    assert warning["placeholder"] == "<PERSON_9>"


async def test_odd_upstream_shapes_pass_through(proxy: Proxy) -> None:
    """covers: AC-7 (restore never crashes on shapes it does not rewrite)"""
    proxy.upstream.reply = lambda _body: {
        "choices": [
            "odd",
            {"index": 1},
            {"message": {"content": None, "tool_calls": ["x", {"function": {"arguments": 5}}]}},
        ]
    }
    body = (await proxy.chat([user("hi")])).json()
    assert body["choices"][0] == "odd"
    assert body["choices"][2]["message"]["tool_calls"][1]["function"]["arguments"] == 5
    proxy.upstream.reply = lambda _body: {"id": "no choices"}
    assert (await proxy.chat([user("hi")])).json() == {"id": "no choices"}


async def test_only_known_parameters_go_upstream(proxy: Proxy) -> None:
    """covers: AC-2 (free text parameters such as `prediction` and `metadata` never leave)"""
    response = await proxy.chat(
        [user("hi")],
        prediction={"type": "content", "content": "Daan de Wit"},
        metadata={"who": "Daan de Wit"},
        temperature=0.2,
        max_tokens=50,
        tool_choice="auto",
        response_format={"type": "json_object"},
    )
    assert response.status_code == 200
    sent = proxy.upstream.bodies[0]
    assert "prediction" not in sent
    assert "metadata" not in sent
    assert "Daan" not in everything_in(sent)
    assert sent["temperature"] == 0.2
    assert sent["max_tokens"] == 50
    assert sent["tool_choice"] == "auto"
    assert sent["response_format"] == {"type": "json_object"}


async def test_decomposed_text_is_sent_and_matched_in_nfc(store: RedisMappingStore) -> None:
    """covers: AC-4 (NFD input, as macOS or a copy and paste can produce, still matches)"""
    entry = DirectoryEntry(
        employee_id="TES-00003",
        display_name="Zoë Bakir",
        email="zoe.bakir@tessaro.example",
        forms=("Zoë", "Bakir", "Zoë Bakir"),
        phone="+31 6 1234 5003",
        iban="NL00XTSR0000000003",
        street="Teststraat 1",
        postcode="1000 AA",
    )
    masker = Masker(
        directory=Directory.from_entries([entry]),
        analyzer=FakeAnalyzer(),
        store=store,
        score_threshold=0.4,
    )
    request = ChatRequest.model_validate(
        {"model": "m", "messages": [user("Zoë Bakir and Zoë and café")]}
    )
    masked = await masker.mask_request(request, "c1")
    assert masked.body["messages"][0]["content"] == "<PERSON_1> and <PERSON_1> and café"
    assert await store.originals("c1", ["<PERSON_1>"]) == {"<PERSON_1>": "Zoë Bakir"}
