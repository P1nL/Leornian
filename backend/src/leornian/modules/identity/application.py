import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from leornian.modules.identity.contracts import Actor, Session
from leornian.shared_kernel.errors import BusinessError


class IdentityStore(Protocol):
    def create(self, session: Session, digest: str) -> None: ...
    def issue_session(self, session: Session, digest: str) -> None: ...
    def renew_session(self, digest: str, expires_at: datetime) -> tuple[Actor, datetime] | None: ...
    def revoke_session(self, digest: str) -> None: ...
    def authenticate(self, digest: str) -> Actor | None: ...
    def active(self, actor: Actor) -> bool: ...
    def get_actor(self, actor_id: UUID) -> Actor | None: ...


class Identity:
    def __init__(self, store: IdentityStore):
        self.store = store

    def create_local_session(self, display_name: str) -> Session:
        session = Session(
            token=secrets.token_urlsafe(32),
            actor=Actor(id=uuid4(), display_name=display_name),
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        self.store.create(session, self.digest(session.token))
        return session

    def renew_local_session(self, token: str) -> Session:
        renewed = self.store.renew_session(
            self.digest(token), datetime.now(UTC) + timedelta(days=7)
        )
        if renewed is None:
            raise BusinessError("unauthorized", "Session is missing, expired, or revoked.")
        actor, expires_at = renewed
        return Session(token=token, actor=actor, expires_at=expires_at)

    def revoke_local_session(self, token: str) -> None:
        self.store.revoke_session(self.digest(token))

    def recover_local_session(self, actor_id: UUID) -> Session:
        """Issue a replacement only from explicitly authorized local maintenance, never HTTP."""
        session = Session(
            token=secrets.token_urlsafe(32),
            actor=self.get_actor(actor_id),
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        self.store.issue_session(session, self.digest(session.token))
        return session

    def authenticate(self, token: str) -> Actor:
        return self.authenticate_digest(self.digest(token))

    def authenticate_digest(self, digest: str) -> Actor:
        actor = self.store.authenticate(digest)
        if actor is None:
            raise BusinessError("unauthorized", "Session is missing, expired, or revoked.")
        return actor

    def require_active(self, actor: Actor) -> None:
        if not self.store.active(actor):
            raise BusinessError("unauthorized", "Learner is inactive.")

    def get_actor(self, actor_id: UUID) -> Actor:
        actor = self.store.get_actor(actor_id)
        if actor is None:
            raise BusinessError("unauthorized", "Learner is inactive.")
        return actor

    @staticmethod
    def digest(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()
