from uuid import UUID

from celery import Celery

from leornian.agent_runtime.gateway import ChatCompletionsGateway
from leornian.agent_runtime.loop import AgentLoop
from leornian.bootstrap.material_change_reviews import MaterialChangeReviewWorkflow
from leornian.bootstrap.material_discovery import MaterialDiscoveryWorkflow
from leornian.bootstrap.material_intake import MaterialIntakeWorkflow
from leornian.bootstrap.material_search import MaterialSearchWorkflow
from leornian.bootstrap.material_sources import MaterialSourceWorkflow
from leornian.bootstrap.material_updates import MaterialUpdateWorkflow
from leornian.bootstrap.model_tests import ModelTestWorkflow
from leornian.bootstrap.services import GoalWorkflow
from leornian.bootstrap.tutor import TutorWorkflow
from leornian.platform.config import Settings
from leornian.platform.database import Database

settings = Settings()
app = Celery("leornian", broker=settings.broker_url)
app.conf.update(
    task_default_queue="leornian.foreground",
    task_routes={"leornian.knowledge.*": {"queue": "leornian.materials"}},
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


@app.task(name="leornian.platform.test_model_connection")
def test_model_connection(test_id: str) -> None:
    ModelTestWorkflow(Database(settings.database_url), settings).execute(UUID(test_id))


@app.task(name="leornian.knowledge.prepare_material")
def prepare_material(job_id: str) -> None:
    MaterialIntakeWorkflow(Database(settings.database_url), settings).execute(UUID(job_id))


@app.task(name="leornian.knowledge.search_material")
def search_material(search_id: str) -> None:
    MaterialSearchWorkflow(Database(settings.database_url), settings).execute(UUID(search_id))


@app.task(name="leornian.knowledge.review_material_change")
def review_material_change(review_id: str) -> None:
    MaterialChangeReviewWorkflow(Database(settings.database_url), settings).execute(UUID(review_id))


@app.task(name="leornian.knowledge.prepare_material_update")
def prepare_material_update(preparation_id: str) -> None:
    MaterialUpdateWorkflow(Database(settings.database_url), settings).execute(UUID(preparation_id))


@app.task(name="leornian.knowledge.check_material_source")
def check_material_source(observation_id: str) -> None:
    MaterialSourceWorkflow(Database(settings.database_url), settings).execute(UUID(observation_id))


@app.task(name="leornian.knowledge.discover_material")
def discover_material(discovery_id: str) -> None:
    MaterialDiscoveryWorkflow(Database(settings.database_url), settings).execute(UUID(discovery_id))
