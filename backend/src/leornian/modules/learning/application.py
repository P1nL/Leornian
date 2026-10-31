from typing import Protocol
from uuid import UUID

from leornian.modules.identity.contracts import Actor
from leornian.modules.learning.contracts import Goal, GoalInput, GoalRequest
from leornian.shared_kernel.errors import BusinessError


class GoalStore(Protocol):
    def request(self, actor: Actor, key: str, data: GoalInput) -> GoalRequest: ...
    def create(self, actor: Actor, request_id: UUID) -> Goal | None: ...
    def list(self, actor: Actor) -> list[Goal]: ...
    def get(self, actor: Actor, goal_id: UUID) -> Goal | None: ...


class Learning:
    def __init__(self, store: GoalStore):
        self.store = store

    def request_goal(self, actor: Actor, key: str, data: GoalInput) -> GoalRequest:
        request = self.store.request(actor, key, data)
        if request.title != data.title or request.motivation != data.motivation:
            raise BusinessError("idempotency_conflict", "This request key has a different payload.")
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
