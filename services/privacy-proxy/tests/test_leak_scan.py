"""The leak scan: every personal value in the dataset, in every place, never leaves (AC-13).

In `just check` it runs with the in memory analyzer fake (which finds nothing, so the
directory and the proxy's own patterns carry it alone). With `PRESIDIO_LIVE=1` the
`presidio` marked test runs the same corpus against the real analyzer (`just leak-scan`).
"""

import json
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from tessaro_dataset import Dataset, export_directory

from .conftest import Json, Proxy, ProxyFactory, everything_in, make_settings, tool_call, user

BATCH = 60
LIVE = os.environ.get("PRESIDIO_LIVE") == "1"


@dataclass(frozen=True)
class Corpus:
    """The values that must never leave, and the writings of them to put in messages."""

    secrets: tuple[str, ...]
    writings: tuple[str, ...]


def _group4(value: str) -> str:
    return " ".join(value[i : i + 4] for i in range(0, len(value), 4))


def build_corpus(dataset: Dataset) -> Corpus:
    """Every directory form, phone, IBAN, street and postcode, plus common re-writings."""
    secrets: set[str] = set()
    writings: set[str] = set()
    for entry in export_directory(dataset).entries:
        values = (*entry.forms, entry.phone, entry.iban, entry.street, entry.postcode)
        secrets.update(values)
        writings.update(values)
        writings.update(f.upper() for f in entry.forms)
        writings.update(f.lower() for f in entry.forms)
        writings.update(
            (
                entry.phone.replace(" ", ""),
                _group4(entry.iban),
                entry.postcode.replace(" ", ""),
                entry.street.upper(),
            )
        )
    return Corpus(secrets=tuple(sorted(secrets)), writings=tuple(sorted(writings)))


def _turn(index: int, values: tuple[str, ...]) -> Iterator[Json]:
    for n, value in enumerate(values):
        call_id = f"call-{index}-{n}"
        yield user(f"Can you check something for {value}? Thanks.")
        yield {
            "role": "assistant",
            "content": None,
            "tool_calls": [tool_call("lookup", {"query": value, "limit": 3}, call_id=call_id)],
        }
        yield {
            "role": "tool",
            "tool_call_id": call_id,
            "content": json.dumps({"employee": value, "status": "ok"}, ensure_ascii=False),
        }


def _leaks(payload: str, corpus: Corpus) -> list[str]:
    compact = re.sub(r"[\s-]", "", payload)
    found = [
        value
        for value in corpus.secrets
        if re.search(rf"(?<!\w){re.escape(value)}(?!\w)", payload, re.IGNORECASE)
    ]
    found += [
        value
        for value in corpus.secrets
        if value.startswith(("+31", "NL")) and re.sub(r"\s", "", value) in compact
    ]
    return found


async def _scan(proxy: Proxy, corpus: Corpus) -> None:
    history: list[Json] = []
    batches = [corpus.writings[i : i + BATCH] for i in range(0, len(corpus.writings), BATCH)]
    for index, batch in enumerate(batches):
        messages = [*history[-30:], *_turn(index, batch)]
        response = await proxy.chat(messages)
        assert response.status_code == 200, response.text
        history = messages
    assert len(proxy.upstream.bodies) == len(batches)
    for body in proxy.upstream.bodies:
        assert _leaks(everything_in(body), corpus) == []


async def test_the_corpus_is_big_and_holds_the_traps(dataset: Dataset) -> None:
    """covers: AC-13 (the scan really covers everyone, including the Dutch name trap)"""
    corpus = build_corpus(dataset)
    assert len(corpus.writings) > 500
    assert {"Daan de Wit", "daan.dewit@tessaro.example", "TES-01005"} <= set(corpus.secrets)
    # The detector itself works: unmasked writings show up as leaks of every secret.
    assert set(_leaks(json.dumps(corpus.writings, ensure_ascii=False), corpus)) >= set(
        corpus.secrets
    )


async def test_leak_scan_with_the_fake_analyzer(proxy: Proxy, dataset: Dataset) -> None:
    """covers: AC-13, AC-2, AC-3, AC-4 (directory and patterns alone catch everything)"""
    await _scan(proxy, build_corpus(dataset))


@pytest.mark.presidio
@pytest.mark.skipif(not LIVE, reason="set PRESIDIO_LIVE=1 with the analyzer running (just up)")
async def test_leak_scan_with_the_real_analyzer(
    make_proxy: ProxyFactory, dataset: Dataset, directory_file: Path
) -> None:
    """covers: AC-13, AC-3 (the real Presidio analyzer, plus names it alone must catch)"""
    url = os.environ.get("PRESIDIO_ANALYZER_URL", "http://localhost:5002")
    settings = make_settings(directory_file, presidio_analyzer_url=url)
    proxy = make_proxy(app_settings=settings, live_analyzer=True)
    await _scan(proxy, build_corpus(dataset))
    outsider = "Please email Margaret Thompson at margaret.thompson@example.org about it."
    proxy.upstream.requests.clear()
    await proxy.chat([user(outsider)], conversation="outsider")
    sent = everything_in(proxy.upstream.bodies[0])
    assert "Margaret" not in sent
    assert "margaret.thompson@example.org" not in sent
