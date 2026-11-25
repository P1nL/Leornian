import logging
import signal
import threading
from collections.abc import Callable
from uuid import UUID

from leornian.platform.config import Settings
from leornian.platform.database import Database

logger = logging.getLogger(__name__)


def relay_once(database: Database, publish: Callable[[UUID], None], seconds: int = 15) -> int:
    with database.transaction() as connection:
        rows = connection.execute(
            "SELECT o.event_id FROM platform.outbox o "
            "JOIN platform.jobs j ON j.id = o.job_id "
            "WHERE j.status = 'queued' AND (o.published_at IS NULL "
            "OR o.published_at < now() - make_interval(secs => %s)) "
            "ORDER BY o.created_at LIMIT 50 FOR UPDATE OF o SKIP LOCKED",
            (seconds,),
        ).fetchall()
        for row in rows:
            publish(row["event_id"])
            connection.execute(
                "UPDATE platform.outbox SET published_at = now(), "
                "delivery_count = delivery_count + 1 "
                "WHERE event_id = %s",
                (row["event_id"],),
            )
        return len(rows)


def relay_runs_once(database: Database, publish: Callable[[UUID], None], seconds: int = 15) -> int:
    with database.transaction() as connection:
        rows = connection.execute(
            "SELECT w.run_id FROM runtime.wakeups w JOIN runtime.runs r ON r.id = w.run_id "
            "WHERE (r.status = 'queued' OR (r.status = 'running' AND r.lease_until < now())) "
            "AND (w.published_at IS NULL OR w.published_at < now() - make_interval(secs => %s)) "
            "ORDER BY r.created_at LIMIT 50 FOR UPDATE OF w SKIP LOCKED",
            (seconds,),
        ).fetchall()
        for row in rows:
            # Wakeups request coordination only. Runtime rechecks leases and call facts.
            publish(row["run_id"])
            connection.execute(
                "UPDATE runtime.wakeups SET published_at = now(), "
                "delivery_count = delivery_count + 1 "
                "WHERE run_id = %s",
                (row["run_id"],),
            )
        return len(rows)


def relay_model_tests_once(database, publish, seconds=15):
    with database.transaction() as connection:
        rows = connection.execute(
            "SELECT id FROM platform.model_connection_tests WHERE status='queued' "
            "AND (published_at IS NULL OR published_at<now()-make_interval(secs=>%s)) "
            "ORDER BY created_at,id LIMIT 50 FOR UPDATE SKIP LOCKED",
            (seconds,),
        ).fetchall()
        for row in rows:
            publish(row["id"])
            connection.execute(
                "UPDATE platform.model_connection_tests SET published_at=now() WHERE id=%s",
                (row["id"],),
            )
        return len(rows)


def relay_materials_once(database, publish, seconds=15):
    from leornian.modules.knowledge.intake import MaterialIntake
    from leornian.modules.knowledge.source_acquisition import MaterialSources

    with database.transaction() as connection:
        rows = connection.execute(
            "SELECT id FROM knowledge.material_jobs "
            "WHERE (state='queued' OR (state IN ('parsing','processing') AND lease_until<now()) "
            "OR (state IN ('waiting_dependency','waiting_config','blocked_unknown') "
            "AND document_id IS NOT NULL)) "
            "AND next_run_at<=now() AND NOT background_deferred "
            "AND (published_at IS NULL OR published_at<now()-make_interval(secs=>%s)) "
            "ORDER BY next_run_at,updated_at,id LIMIT 50 FOR UPDATE SKIP LOCKED",
            (seconds,),
        ).fetchall()
        for row in rows:
            if not MaterialSources(connection).job_selected(row["id"]):
                MaterialIntake(connection).defer_background(row["id"])
                continue
            publish(row["id"])
            connection.execute(
                "UPDATE knowledge.material_jobs SET published_at=now() WHERE id=%s",
                (row["id"],),
            )
        return len(rows)


def relay_material_searches_once(database, publish, seconds=15):
    with database.transaction() as connection:
        rows = connection.execute(
            "SELECT id FROM knowledge.material_searches "
            "WHERE (status IN ('queued','waiting_config','waiting_dependency','blocked_unknown') "
            "OR (status='processing' AND lease_until<now())) "
            "AND error_code IS DISTINCT FROM 'node_material_review_failed' "
            "AND (published_at IS NULL OR published_at<now()-make_interval(secs=>%s)) "
            "ORDER BY published_at NULLS FIRST,created_at,id LIMIT 50 FOR UPDATE SKIP LOCKED",
            (seconds,),
        ).fetchall()
        for row in rows:
            publish(row["id"])
            connection.execute(
                "UPDATE knowledge.material_searches SET published_at=now() WHERE id=%s",
                (row["id"],),
            )
        return len(rows)


def relay_material_change_reviews_once(database, publish, seconds=15):
    with database.transaction() as connection:
        rows = connection.execute(
            "SELECT id FROM knowledge.material_change_reviews "
            "WHERE (status IN ('queued','waiting_config','blocked_unknown') "
            "OR (status='processing' AND lease_until<now())) AND next_run_at<=now() "
            "AND (published_at IS NULL OR published_at<now()-make_interval(secs=>%s)) "
            "ORDER BY published_at NULLS FIRST,next_run_at,id LIMIT 50 FOR UPDATE SKIP LOCKED",
            (seconds,),
        ).fetchall()
        for row in rows:
            publish(row["id"])
            connection.execute(
                "UPDATE knowledge.material_change_reviews SET published_at=now() WHERE id=%s",
                (row["id"],),
            )
        return len(rows)


def relay_material_updates_once(database, publish, seconds=15):
    with database.transaction() as connection:
        rows = connection.execute(
            "SELECT id FROM knowledge.material_update_preparations "
            "WHERE (status IN ('queued','waiting_config','blocked_unknown') "
            "OR (status='processing' AND lease_until<now())) AND next_run_at<=now() "
            "AND (published_at IS NULL OR published_at<now()-make_interval(secs=>%s)) "
            "ORDER BY published_at NULLS FIRST,next_run_at,id LIMIT 50 FOR UPDATE SKIP LOCKED",
            (seconds,),
        ).fetchall()
        for row in rows:
            publish(row["id"])
            connection.execute(
                "UPDATE knowledge.material_update_preparations SET published_at=now() WHERE id=%s",
                (row["id"],),
            )
        return len(rows)


def main() -> None:
    # Composition belongs to entrypoints, not the shared relay implementation.
    from leornian.bootstrap.automatic_supply import AutomaticSupply
    from leornian.bootstrap.execution_environments import ExecutionEnvironmentWorkflow
    from leornian.bootstrap.journey import JourneyWorkflow
    from leornian.bootstrap.material_discovery import scan_material_discovery_once
    from leornian.bootstrap.material_intake import MaterialIntakeWorkflow
    from leornian.bootstrap.material_repreparations import MaterialRepreparationWorkflow
    from leornian.bootstrap.material_sources import scan_material_sources_once
    from leornian.bootstrap.model_tests import ModelTestWorkflow
    from leornian.bootstrap.proactive_teaching import ProactiveTeachingWorkflow
    from leornian.bootstrap.teaching_continuations import TeachingContinuationWorkflow
    from leornian.bootstrap.tutor import TutorWorkflow
    from leornian.entrypoints.worker import (
        check_material_source,
        create_goal,
        discover_material,
        prepare_material,
        prepare_material_update,
        review_material_change,
        search_material,
        teach,
        test_model_connection,
    )

    settings = Settings()
    database = Database(settings.database_url)
    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    logging.basicConfig(level=logging.INFO)

    def publish(event_id: UUID) -> None:
        create_goal.apply_async(args=[str(event_id)], retry=False, delivery_mode=2)

    while not stopped.is_set():
        try:
            sent = relay_once(database, publish, settings.redispatch_seconds)
            if sent:
                logger.info("Published %s deterministic goal wakeups", sent)
            teaching = relay_runs_once(
                database,
                lambda run_id: teach.apply_async(
                    args=[str(run_id)],
                    retry=False,
                    delivery_mode=2,
                ),
                settings.redispatch_seconds,
            )
            if teaching:
                logger.info("Published %s teaching coordination wakeups", teaching)
            ModelTestWorkflow(database, settings).expire_unknowns()
            MaterialIntakeWorkflow(database, settings).expire_retained_inputs()
            for observation_id in scan_material_sources_once(database, settings):
                check_material_source.apply_async(
                    args=[str(observation_id)], retry=False, delivery_mode=2,
                )
            for discovery_id in scan_material_discovery_once(database):
                discover_material.apply_async(
                    args=[str(discovery_id)], retry=False, delivery_mode=2,
                )
            relay_materials_once(
                database,
                lambda job_id: prepare_material.apply_async(
                    args=[str(job_id)],
                    retry=False,
                    delivery_mode=2,
                ),
                settings.redispatch_seconds,
            )
            relay_model_tests_once(
                database,
                lambda test_id: test_model_connection.apply_async(
                    args=[str(test_id)],
                    retry=False,
                    delivery_mode=2,
                ),
                settings.redispatch_seconds,
            )
            relay_material_searches_once(
                database,
                lambda search_id: search_material.apply_async(
                    args=[str(search_id)], retry=False, delivery_mode=2,
                ),
                settings.redispatch_seconds,
            )
            relay_material_change_reviews_once(
                database,
                lambda review_id: review_material_change.apply_async(
                    args=[str(review_id)], retry=False, delivery_mode=2,
                ),
                settings.redispatch_seconds,
            )
            relay_material_updates_once(
                database,
                lambda preparation_id: prepare_material_update.apply_async(
                    args=[str(preparation_id)], retry=False, delivery_mode=2,
                ),
                settings.redispatch_seconds,
            )
            JourneyWorkflow(database).expire_executions()
            ExecutionEnvironmentWorkflow(database).expire()
            advanced = AutomaticSupply(database, settings).reconcile_once()
            TutorWorkflow(database, settings).reconcile_deliveries()
            MaterialRepreparationWorkflow(database, settings).reconcile_once()
            ProactiveTeachingWorkflow(database).scan_due_once()
            TeachingContinuationWorkflow(database, settings).reconcile_once()
            if advanced:
                logger.info("Advanced %s automatic item supply transitions", advanced)
        except Exception:
            logger.exception("Outbox delivery failed; rows remain eligible for another scan")
        stopped.wait(1)


if __name__ == "__main__":
    main()
