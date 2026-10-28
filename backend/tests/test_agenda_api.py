"""API-level tests for saving a meeting's agenda (Lab 6)."""

import uuid

from sqlalchemy import select

from app.models import Meeting

AGENDA = {
    "items": [
        {"topic": "  New Pro pricing ", "owner": "Олена", "minutes": 15},
        {"topic": "Customer feedback", "owner": " "},
    ],
    "action_items": [{"task": "Compare competitors", "owner": "Taras", "due": "2026-10-30"}],
}
SUGGESTION = {
    "title": "Pricing sync",
    "starts_at": "2026-11-02T10:00:00+02:00",
    "duration_minutes": 45,
    "items": [{"topic": "New Pro pricing", "owner": "Олена", "minutes": 15}],
    "action_items": [],
    "language": "uk",
}


async def _meeting_id(client, meeting_payload) -> str:
    response = await client.post("/api/v1/meetings", json=meeting_payload)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _stored(session, meeting_id: str) -> Meeting:
    return await session.scalar(select(Meeting).where(Meeting.id == uuid.UUID(meeting_id)))


async def test_new_meeting_has_no_agenda(client, meeting_payload):
    meeting_id = await _meeting_id(client, meeting_payload)

    response = await client.get(f"/api/v1/meetings/{meeting_id}")

    assert response.json()["agenda"] is None


async def test_save_typed_agenda_strips_and_returns_it(client, session, meeting_payload):
    meeting_id = await _meeting_id(client, meeting_payload)

    response = await client.put(f"/api/v1/meetings/{meeting_id}/agenda", json=AGENDA)

    assert response.status_code == 200, response.text
    agenda = response.json()["agenda"]
    assert agenda["items"] == [
        {"topic": "New Pro pricing", "owner": "Олена", "minutes": 15},
        {"topic": "Customer feedback", "owner": None, "minutes": None},
    ]
    assert agenda["action_items"][0]["due"] == "2026-10-30"
    stored = await _stored(session, meeting_id)
    assert stored.ai_suggestion is None and stored.ai_model is None


async def test_save_keeps_the_suggestion_next_to_the_agenda(client, session, meeting_payload):
    meeting_id = await _meeting_id(client, meeting_payload)
    payload = AGENDA | {
        "ai_suggestion": SUGGESTION,
        "ai_model": "anthropic.claude-opus-5-5",
        "ai_prompt_version": "agenda-v1",
    }

    response = await client.put(f"/api/v1/meetings/{meeting_id}/agenda", json=payload)

    assert response.status_code == 200, response.text
    # The suggestion is the quality signal, not something the browser reads back.
    assert "ai_suggestion" not in response.json()
    stored = await _stored(session, meeting_id)
    assert stored.ai_suggestion["title"] == "Pricing sync"
    assert stored.ai_suggestion["items"][0]["owner"] == "Олена"
    assert (stored.ai_model, stored.ai_prompt_version) == ("anthropic.claude-opus-5-5", "agenda-v1")
    assert len(stored.agenda["items"]) == 2  # what the user saved, not what was suggested


async def test_typed_resave_keeps_the_earlier_suggestion(client, session, meeting_payload):
    meeting_id = await _meeting_id(client, meeting_payload)
    url = f"/api/v1/meetings/{meeting_id}/agenda"
    await client.put(
        url,
        json=AGENDA
        | {"ai_suggestion": SUGGESTION, "ai_model": "fake", "ai_prompt_version": "agenda-v1"},
    )

    response = await client.put(url, json={"items": [{"topic": "Only this"}]})

    assert response.status_code == 200, response.text
    stored = await _stored(session, meeting_id)
    assert stored.agenda["items"] == [{"topic": "Only this", "owner": None, "minutes": None}]
    assert stored.ai_suggestion["title"] == "Pricing sync"
    assert stored.ai_model == "fake"


async def test_suggestion_without_its_model_is_rejected(client, meeting_payload):
    meeting_id = await _meeting_id(client, meeting_payload)

    response = await client.put(
        f"/api/v1/meetings/{meeting_id}/agenda", json=AGENDA | {"ai_suggestion": SUGGESTION}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_invalid_suggestion_is_rejected(client, meeting_payload):
    meeting_id = await _meeting_id(client, meeting_payload)
    bad = SUGGESTION | {"items": [{"topic": "x", "minutes": 0}]}

    response = await client.put(
        f"/api/v1/meetings/{meeting_id}/agenda",
        json=AGENDA | {"ai_suggestion": bad, "ai_model": "fake", "ai_prompt_version": "agenda-v1"},
    )

    assert response.status_code == 422


async def test_blank_topic_is_rejected_with_its_field(client, meeting_payload):
    meeting_id = await _meeting_id(client, meeting_payload)

    response = await client.put(
        f"/api/v1/meetings/{meeting_id}/agenda", json={"items": [{"topic": "   "}]}
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "items.0.topic"


async def test_too_many_minutes_is_rejected(client, meeting_payload):
    meeting_id = await _meeting_id(client, meeting_payload)

    response = await client.put(
        f"/api/v1/meetings/{meeting_id}/agenda", json={"items": [{"topic": "x", "minutes": 481}]}
    )

    assert response.status_code == 422


async def test_another_users_meeting_is_not_found(client, other_client, meeting_payload):
    meeting_id = await _meeting_id(client, meeting_payload)

    response = await other_client.put(f"/api/v1/meetings/{meeting_id}/agenda", json=AGENDA)

    assert response.status_code == 404


async def test_unknown_meeting_is_not_found(client):
    response = await client.put(f"/api/v1/meetings/{uuid.uuid4()}/agenda", json=AGENDA)

    assert response.status_code == 404


async def test_show_agendas_lists_saved_agendas_with_their_suggestion(client, meeting_payload):
    from app.lambda_handler import handler

    first = await _meeting_id(client, meeting_payload)
    await _meeting_id(client, meeting_payload | {"name": "No agenda"})
    second = await _meeting_id(client, meeting_payload | {"name": "Pricing sync"})
    await client.put(f"/api/v1/meetings/{first}/agenda", json={"items": [{"topic": "Typed"}]})
    await client.put(
        f"/api/v1/meetings/{second}/agenda",
        json=AGENDA
        | {"ai_suggestion": SUGGESTION, "ai_model": "fake", "ai_prompt_version": "agenda-v1"},
    )

    # The same call `make aws-agendas` makes; it runs in its own thread and loop.
    rows = handler({"action": "show-agendas", "limit": 10}, None)

    assert [row["name"] for row in rows] == ["Pricing sync", "Sprint planning"]  # newest first
    assert rows[0]["ai_model"] == "fake"
    assert rows[0]["ai_suggestion"]["items"][0]["topic"] == "New Pro pricing"
    assert rows[0]["agenda"]["items"][0]["topic"] == "New Pro pricing"
    assert rows[1]["ai_suggestion"] is None
    assert rows[0]["updated_at"].endswith(("+02:00", "+03:00"))  # Europe/Kyiv
