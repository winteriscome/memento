"""Subconscious track — background thread consuming PulseEvents (Layer 3)."""
import json
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from queue import Empty, Queue

from memento.decay import compute_reinforce_delta, compute_decay_deltas
from memento.logging import get_logger
from memento.repository import update_decay_watermark

logger = get_logger("memento.subconscious")

class SubconsciousTrack:
    """Background thread that processes PulseEvents and runs decay cycles."""

    def __init__(self, conn_factory, pulse_queue: Queue, config: dict):
        """Initialize the subconscious track.

        Args:
            conn_factory: Callable that returns a new sqlite3 connection
            pulse_queue: Queue[dict] containing PulseEvent dicts
            config: Configuration dict with 'decay_interval' (seconds)
        """
        self.conn_factory = conn_factory
        self.pulse_queue = pulse_queue
        self.decay_interval = config.get("decay_interval", 300)
        self._shutdown_event = threading.Event()
        self._thread = None

    def start(self):
        """Start the background thread."""
        if self._thread is not None:
            raise RuntimeError("SubconsciousTrack already started")

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def shutdown(self):
        """Signal shutdown and wait for thread to finish."""
        if self._thread is None:
            return

        self._shutdown_event.set()
        self._thread.join(timeout=5.0)
        self._thread = None

    def _run(self):
        """Main loop: drain pulse events and run periodic decay cycles."""
        conn = self.conn_factory()
        last_decay_run = time.time()

        while not self._shutdown_event.is_set():
            try:
                self._drain_pulse_events(conn)

                now = time.time()
                if now - last_decay_run >= self.decay_interval:
                    self._run_decay_cycle(conn)
                    last_decay_run = now
                    self._clean_recon_buffer(conn)

            except Exception as e:
                logger.error(f"Error in subconscious run loop: {e}", exc_info=True)

            # Wait briefly to avoid tight loop (allows fast shutdown response)
            self._shutdown_event.wait(timeout=0.5)

        try:
            # Final drain before shutdown
            self._drain_pulse_events(conn)
        except Exception as e:
            logger.error(f"Error in final pulse drain: {e}", exc_info=True)
        finally:
            conn.close()

    def _drain_pulse_events(self, conn: sqlite3.Connection):
        """Consume all PulseEvents from queue and process them.

        For each PulseEvent:
        1. Look up engram from view_engrams
        2. compute_reinforce_delta(engram) → INSERT delta_ledger
        3. INSERT recon_buffer with idempotency_key (IntegrityError → skip)
        4. Commit after batch
        """
        events = []
        while True:
            try:
                event = self.pulse_queue.get_nowait()
                events.append(event)
            except Empty:
                break

        if not events:
            return

        seen_keys = set()
        deduped_events = []
        for event in events:
            key = event.get("idempotency_key")
            if not key:
                deduped_events.append(event)
                continue
                
            if key not in seen_keys:
                seen_keys.add(key)
                deduped_events.append(event)

        events = deduped_events

        now = datetime.now(timezone.utc).isoformat()

        for event in events:
            engram_id = event["engram_id"]

            # Look up engram from view_engrams
            engram = conn.execute(
                "SELECT id, strength, last_accessed, access_count, importance "
                "FROM view_engrams WHERE id=?",
                (engram_id,),
            ).fetchone()

            if not engram:
                # Engram not in view_engrams (might be forgotten or not consolidated)
                logger.debug(f"Skipping pulse event for unknown/forgotten engram: {engram_id}")
                continue

            # Convert Row to dict
            engram_dict = dict(engram)

            # Compute reinforce delta
            delta = compute_reinforce_delta(engram_dict, now=event["timestamp"])

            # Insert into delta_ledger
            conn.execute(
                "INSERT INTO delta_ledger (engram_id, delta_type, delta_value, created_at) "
                "VALUES (?, ?, ?, ?)",
                (delta["engram_id"], delta["delta_type"], delta["delta_value"], now),
            )

            # Insert into recon_buffer (with idempotency)
            try:
                coactivated_json = json.dumps(event.get("coactivated_ids", []))
                conn.execute(
                    "INSERT INTO recon_buffer "
                    "(engram_id, query_context, coactivated_ids, idempotency_key, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        engram_id,
                        event.get("query_context"),
                        coactivated_json,
                        event["idempotency_key"],
                        now,
                    ),
                )
            except sqlite3.IntegrityError:
                logger.debug(f"Duplicate idempotency_key for engram {engram_id}, skipping recon_buffer")

        conn.commit()

    def _clean_recon_buffer(self, conn: sqlite3.Connection):
        try:
            seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
            
            result = conn.execute(
                "DELETE FROM recon_buffer "
                "WHERE nexus_consumed_epoch_id IS NOT NULL "
                "AND content_consumed_epoch_id IS NOT NULL "
                "AND created_at < ?",
                (seven_days_ago,)
            )
            deleted_count = result.rowcount
            if deleted_count > 0:
                logger.info(f"Cleaned {deleted_count} expired recon_buffer entries")
                conn.commit()
        except Exception as e:
            logger.error(f"Error cleaning recon_buffer: {e}", exc_info=True)
            conn.rollback()

    def _run_decay_cycle(self, conn: sqlite3.Connection):
        """Periodic decay computation.

        1. Read decay_watermark from runtime_cursors
        2. Query view_engrams for active engrams
        3. compute_decay_deltas(engrams, watermark, now)
        4. Batch INSERT delta_ledger
        5. update_decay_watermark(conn, new_watermark)
        """
        now = datetime.now(timezone.utc).isoformat()

        # Read decay_watermark
        watermark_row = conn.execute(
            "SELECT value FROM runtime_cursors WHERE key='decay_watermark'"
        ).fetchone()

        if not watermark_row:
            # No watermark, initialize it
            update_decay_watermark(conn, now)
            return

        watermark = watermark_row["value"]

        # Query active engrams from view_engrams
        engrams = conn.execute(
            "SELECT id, strength, last_accessed, access_count, importance, rigidity "
            "FROM view_engrams"
        ).fetchall()

        if not engrams:
            return

        # Convert Rows to dicts
        engrams_list = [dict(row) for row in engrams]

        try:
            # Compute decay deltas
            deltas, new_watermark = compute_decay_deltas(engrams_list, watermark, now)

            # Batch insert deltas
            for delta in deltas:
                conn.execute(
                    "INSERT INTO delta_ledger (engram_id, delta_type, delta_value, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (delta["engram_id"], delta["delta_type"], delta["delta_value"], now),
                )

            # Update watermark
            update_decay_watermark(conn, new_watermark)
            conn.commit()
        except Exception as e:
            logger.error(f"Error computing decay deltas: {e}", exc_info=True)
            conn.rollback()
