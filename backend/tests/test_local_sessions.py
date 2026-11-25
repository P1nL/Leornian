from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from leornian.entrypoints.api import create_app
from leornian.modules.identity.application import Identity
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.learning.contracts import GoalInput
from leornian.platform.config import Settings
from leornian.shared_kernel.errors import BusinessError

pytestmark = pytest.mark.integration


def client(database):
    return TestClient(create_app(Settings(database_url=database.url)))


def headers(session):
    return {"Authorization": f"Bearer {session.token}"}


def test_refresh_renews_only_current_session_and_preserves_identity(database, workflow, session):
    original = workflow.snapshot(session.token)
    digest = Identity.digest(session.token)
    with database.transaction() as c:
        c.execute(
            "UPDATE identity.sessions SET expires_at = now() + interval '1 hour' "
            "WHERE token_digest = %s", (digest,),
        )
    response = client(database).post("/v1/local-sessions/refresh", headers=headers(session))
    assert response.status_code == 200
    renewed = response.json()
    assert renewed["token"] == session.token
    assert renewed["actor"]["id"] == str(session.actor.id)
    assert datetime.fromisoformat(renewed["expires_at"].replace("Z", "+00:00")) > (
        datetime.now(UTC) + timedelta(days=6)
    )
    assert workflow.snapshot(session.token) == original
    with database.transaction(snapshot=True) as c:
        assert c.execute(
            "SELECT count(*) AS n FROM identity.sessions WHERE actor_id = %s",
            (session.actor.id,),
        ).fetchone()["n"] == 1


@pytest.mark.parametrize("state", ["expired", "revoked", "inactive"])
def test_refresh_cannot_restore_invalid_authority(database, session, state):
    digest = Identity.digest(session.token)
    with database.transaction() as c:
        if state == "expired":
            c.execute(
                "UPDATE identity.sessions SET expires_at = now() - interval '1 hour' "
                "WHERE token_digest = %s", (digest,),
            )
        elif state == "revoked":
            c.execute(
                "UPDATE identity.sessions SET revoked_at = now() WHERE token_digest = %s",
                (digest,),
            )
        else:
            c.execute("UPDATE identity.learners SET active = false WHERE id = %s",
                      (session.actor.id,))
        before = c.execute(
            "SELECT expires_at, revoked_at FROM identity.sessions WHERE token_digest = %s",
            (digest,),
        ).fetchone()
    assert client(database).post(
        "/v1/local-sessions/refresh", headers=headers(session)
    ).status_code == 401
    with database.transaction(snapshot=True) as c:
        assert c.execute(
            "SELECT expires_at, revoked_at FROM identity.sessions WHERE token_digest = %s",
            (digest,),
        ).fetchone() == before


def test_refresh_does_not_shorten_a_longer_existing_lease(database, workflow, session):
    until = datetime.now(UTC) + timedelta(days=8)
    with database.transaction() as c:
        c.execute("UPDATE identity.sessions SET expires_at = %s WHERE token_digest = %s",
                  (until, Identity.digest(session.token)))
    assert workflow.refresh_session(session.token).expires_at == until


def test_logout_revokes_current_token_and_is_idempotent(database, workflow, session):
    other = workflow.create_session("Other local identity")
    api = client(database)
    for _ in range(2):
        assert api.delete("/v1/local-sessions/current", headers=headers(session)).status_code == 204
    assert api.post("/v1/local-sessions/refresh", headers=headers(session)).status_code == 401
    assert api.get("/v1/snapshot", headers=headers(session)).status_code == 401
    assert workflow.snapshot(other.token).actor.id == other.actor.id


def test_local_recovery_issues_new_session_without_reviving_old_bindings(
    database, workflow, session,
):
    accepted = workflow.submit(
        session.token, str(uuid4()), GoalInput(title="Original learner goal")
    )
    digest = Identity.digest(session.token)
    with database.transaction() as c:
        c.execute(
            "UPDATE identity.sessions SET expires_at = now() - interval '1 hour' "
            "WHERE token_digest = %s", (digest,),
        )
        before = c.execute(
            "SELECT expires_at, revoked_at FROM identity.sessions WHERE token_digest = %s",
            (digest,),
        ).fetchone()
        replacement = Identity(PgIdentityStore(c)).recover_local_session(session.actor.id)
    assert replacement.actor == session.actor
    assert replacement.token != session.token
    assert workflow.job(replacement.token, accepted.job_id).id == accepted.job_id
    with pytest.raises(BusinessError) as problem:
        workflow.snapshot(session.token)
    assert problem.value.code == "unauthorized"
    with database.transaction(snapshot=True) as c:
        assert c.execute(
            "SELECT expires_at, revoked_at FROM identity.sessions WHERE token_digest = %s",
            (digest,),
        ).fetchone() == before
        assert c.execute(
            "SELECT count(*) AS n FROM identity.learners WHERE id = %s",
            (session.actor.id,),
        ).fetchone()["n"] == 1


def test_local_recovery_rejects_inactive_identity(database, session):
    with database.transaction() as c:
        c.execute("UPDATE identity.learners SET active = false WHERE id = %s",
                  (session.actor.id,))
    with database.transaction() as c, pytest.raises(BusinessError):
        Identity(PgIdentityStore(c)).recover_local_session(session.actor.id)


def test_no_anonymous_or_actor_selected_refresh_api(database, session):
    api = client(database)
    assert api.post("/v1/local-sessions/refresh").status_code == 401
    assert api.delete("/v1/local-sessions/current").status_code == 401
    assert api.post(
        "/v1/local-sessions", json={"actor_id": str(session.actor.id)}
    ).status_code == 422
    assert api.post(
        "/v1/local-sessions/refresh", headers={"Authorization": "Bearer invalid"}
    ).status_code == 401
