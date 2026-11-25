from typing import Protocol
from uuid import UUID

from leornian.modules.identity.contracts import Actor
from leornian.modules.learning.contracts import Goal, GoalInput, GoalRequest
from leornian.shared_kernel.errors import BusinessError


class GoalStore(Protocol):
    def request(self, actor: Actor, key: str, data: GoalInput) -> GoalRequest: ...
    def get_request(self, actor: Actor, key: str) -> GoalRequest | None: ...
    def create(self, actor: Actor, request_id: UUID) -> Goal | None: ...
    def list(self, actor: Actor) -> list[Goal]: ...
    def get(self, actor: Actor, goal_id: UUID) -> Goal | None: ...
    def rename(
        self, actor: Actor, goal_id: UUID, title: str, motivation: str | None = None,
    ) -> Goal | None: ...
    def delete(self, actor: Actor, goal_id: UUID) -> bool: ...


class Learning:
    def __init__(self, store: GoalStore):
        self.store = store

    def request_goal(self, actor: Actor, key: str, data: GoalInput) -> GoalRequest:
        request = self.store.request(actor, key, data)
        if (
            request.title != data.title or request.motivation != data.motivation
            or request.material_scope != data.material_scope
        ):
            raise BusinessError("idempotency_conflict", "This request key has a different payload.")
        return request

    def goal_request(self, actor: Actor, key: str) -> GoalRequest:
        request = self.store.get_request(actor, key)
        if request is None:
            raise BusinessError("not_found", "Goal request not found.")
        return request

    def create_goal(self, actor: Actor, request_id: UUID) -> Goal:
        goal = self.store.create(actor, request_id)
        if goal is None:
            raise BusinessError("not_found", "Goal request not found.")
        return goal

    def list_goals(self, actor: Actor) -> list[Goal]:
        return self.store.list(actor)

    def get_goal(self, actor: Actor, goal_id: UUID) -> Goal:
        goal = self.store.get(actor, goal_id)
        if goal is None:
            raise BusinessError("not_found", "Learning goal not found.")
        return goal

    def rename_goal(self, actor, goal_id, title, motivation=None):
        goal = self.store.rename(actor, goal_id, title, motivation) if motivation is not None else (
            self.store.rename(actor, goal_id, title)
        )
        if goal is None:
            raise BusinessError("not_found", "Learning goal not found.")
        return goal

    def delete_goal(self, actor, goal_id):
        if not self.store.delete(actor, goal_id):
            raise BusinessError("not_found", "Learning goal not found.")
