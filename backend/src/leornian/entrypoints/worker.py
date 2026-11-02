from uuid import UUID

from celery import Celery

from leornian.agent_runtime.gateway import ChatCompletionsGateway
from leornian.agent_runtime.loop import AgentLoop
from leornian.bootstrap.services import GoalWorkflow
from leornian.bootstrap.tutor import TutorWorkflow
from leornian.platform.config import Settings
from leornian.platform.database import Database

settings = Settings()
app = Celery("leornian", broker=settings.broker_url)
app.conf.update(
    task_default_queue="leornian",
    task_serializer="json",
    accept_content=["json"],
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_connection_timeout=5,
    broker_transport_options={"visibility_timeout": 3600, "socket_timeout": 5},
)


@app.task(name="leornian.learning.create_goal")
def create_goal(event_id: str) -> None:
    GoalWorkflow(Database(settings.database_url)).process_goal(UUID(event_id))


@app.task(name="leornian.tutor.teach")
def teach(run_id: str) -> None:
    AgentLoop(
        TutorWorkflow(Database(settings.database_url), settings),
        ChatCompletionsGateway(settings),
    ).run(UUID(run_id))
