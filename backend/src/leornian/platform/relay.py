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


def main() -> None:
    # Composition belongs to entrypoints, not the shared relay implementation.
    from leornian.bootstrap.automatic_supply import AutomaticSupply
    from leornian.bootstrap.journey import JourneyWorkflow
    from leornian.bootstrap.tutor import TutorWorkflow
    from leornian.entrypoints.worker import create_goal, teach

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
            JourneyWorkflow(database).expire_executions()
            advanced = AutomaticSupply(database, settings).reconcile_once()
            TutorWorkflow(database, settings).reconcile_deliveries()
            if advanced:
                logger.info("Advanced %s automatic item supply transitions", advanced)
        except Exception:
            logger.exception("Outbox delivery failed; rows remain eligible for another scan")
        stopped.wait(1)


if __name__ == "__main__":
    main()
