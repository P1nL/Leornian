import logging
import threading
from contextlib import contextmanager

logger = logging.getLogger(__name__)


@contextmanager
def maintain_lease(port, lease, interval):
    stopped = threading.Event()
    lost = threading.Event()

    def pulse():
        while not stopped.wait(interval):
            try:
                if not port.heartbeat(lease):
                    lost.set()
                    return
            except Exception:
                logger.exception("Lease heartbeat failed; receipt recording remains allowed")
                lost.set()
                return

    thread = threading.Thread(target=pulse, daemon=True, name="leornian-lease")
    thread.start()
    try:
        yield lost
    finally:
        stopped.set()
        thread.join(timeout=6)
