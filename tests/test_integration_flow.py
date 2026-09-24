"""SPEC acceptance scenario 1, end to end.

    "Register two agents. One sends a task; the other claims and completes
    it; the sender reads the result."

Nothing here is mocked or patched.  Requests go through the real FastAPI
application (including its lifespan, so the recovery loop is running), and
every claim about stored state is read back from the real database that
``RELAY_DATABASE_URL`` points at.  ``conftest`` guarantees that URL is a
scratch database and never the development ``./agent-relay.db``.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import main
from database import DATABASE_URL, Attempt, Base, Task, db_session, engine
from storage import secret_hash


@pytest.fixture(autouse=True)
def empty_database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


def register(client: TestClient, name: str, description: str) -> tuple[dict, dict[str, str]]:
    response = client.post("/api/v1/agents", json={"name": name, "description": description})
    assert response.status_code == 201
    data = response.json()
    return data, {"Authorization": f"Bearer {data['token']}"}


def test_integration_targets_relay_database_url_not_the_dev_database():
    assert DATABASE_URL == os.environ["RELAY_DATABASE_URL"]
    assert not DATABASE_URL.endswith("/agent-relay.db")
    assert str(engine.url) == DATABASE_URL


def test_alice_sends_bob_claims_and_completes_and_alice_reads_the_result():
    with TestClient(main.app) as client:
        alice, alice_headers = register(client, "alice", "sender")
        bob, bob_headers = register(client, "bob", "Deterministic uppercase worker")
        assert alice["agent_id"] != bob["agent_id"]

        # 1. alice sends bob a task.
        sent = client.post(
            "/api/v1/tasks",
            headers=alice_headers,
            json={"to": bob["agent_id"], "input": "hello from alice"},
        )
        assert sent.status_code == 201
        task_id = sent.json()["task_id"]
        assert sent.json()["status"] == "queued"

        # It is queued in the database before anyone claims it.
        with db_session() as db:
            queued = db.get(Task, task_id)
            assert queued.status == "queued"
            assert queued.sender_id == alice["agent_id"]
            assert queued.recipient_id == bob["agent_id"]
            assert queued.attempt_count == 0
            assert queued.output is None
            assert queued.finished_at is None

        # 2. bob claims it.
        claim = client.post(
            "/api/v1/tasks/claim",
            headers=bob_headers,
            json={"worker_id": "bob-laptop-1", "wait_seconds": 0},
        )
        assert claim.status_code == 200
        claimed = claim.json()
        claim_token = claimed["claim_token"]
        assert claimed["task_id"] == task_id
        assert claimed["from"] == alice["agent_id"]
        assert claimed["input"] == "hello from alice"
        assert claimed["attempt"] == 1
        assert claimed["lease_expires_at"]

        with db_session() as db:
            processing = db.get(Task, task_id)
            assert processing.status == "processing"
            assert processing.attempt_count == 1

        # 3. bob completes it, mirroring the deterministic worker's output.
        expected_output = claimed["input"].upper()
        complete = client.post(
            f"/api/v1/tasks/{task_id}/complete",
            headers=bob_headers,
            json={"claim_token": claim_token, "output": expected_output},
        )
        assert complete.status_code == 200
        assert complete.json() == {"task_id": task_id, "status": "completed"}

        # 4. alice reads the task and sees the output and the final status.
        read = client.get(f"/api/v1/tasks/{task_id}", headers=alice_headers)
        assert read.status_code == 200
        result = read.json()
        assert result["status"] == "completed"
        assert result["output"] == expected_output
        assert result["error"] is None
        assert result["from"] == alice["agent_id"]
        assert result["to"] == bob["agent_id"]
        assert result["attempt_count"] == 1
        assert result["finished_at"] is not None

    # The same outcome is durable in the real database, not just in the
    # response bodies.
    with db_session() as db:
        stored = db.get(Task, task_id)
        assert stored.status == "completed"
        assert stored.output == expected_output
        assert stored.error is None
        assert stored.attempt_count == 1
        assert stored.finished_at is not None

        attempts = list(db.scalars(select(Attempt).where(Attempt.task_id == task_id)))
        assert len(attempts) == 1
        assert attempts[0].attempt_number == 1
        assert attempts[0].worker_id == "bob-laptop-1"
        assert attempts[0].outcome == "completed"
        assert attempts[0].finished_at is not None
        # The claim token is stored only as a hash.
        assert attempts[0].claim_token_hash == secret_hash(claim_token)
        assert claim_token not in attempts[0].claim_token_hash
