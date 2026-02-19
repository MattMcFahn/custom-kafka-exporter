"""Application entrypoint — orchestrates the metric refresh loop.

Responsibilities:
  - Parse configuration from the environment.
  - Start the Prometheus HTTP server.
  - Run the metric refresh loop until a shutdown signal is received.
  - Set ``topic_metric_exporter_up`` to 0 on any unhandled Kafka error.
"""

import logging
import signal
import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor, as_completed

from confluent_kafka import KafkaException

from app.config import Config
from app.kafka_client import discover_topics, get_topic_timestamp
from app.log_helper import _configure_logging
from app.metrics import (
    set_exporter_healthy,
    set_exporter_unhealthy,
    start_metrics_server,
    update_topic_metrics,
)

logger = logging.getLogger(__name__)


def _install_signal_handlers(shutdown_flag: list[bool]) -> None:
    """Register SIGTERM / SIGINT handlers that flip ``shutdown_flag[0]``.

    Signal handlers can only be installed from the main thread of the main
    interpreter — Python raises ``ValueError`` otherwise.  When ``main()`` is
    called from a non-main thread (e.g. inside a pytest worker thread) we skip
    registration entirely; the daemon thread will be reaped automatically when
    the process exits.

    A mutable list is used so the closure can modify a value visible in the
    calling scope without ``nonlocal``.

    Args:
        shutdown_flag: Single-element list; element is set to True on signal.
    """
    if threading.current_thread() is not threading.main_thread():
        logger.debug(
            "Signal handlers skipped — not running on the main thread "
            "(this is expected when main() is called from a test thread)"
        )
        return

    def _handler(signum: int, _frame: types.FrameType | None) -> None:
        sig_name = signal.Signals(signum).name
        logger.info("Received signal %s — initiating graceful shutdown", sig_name)
        shutdown_flag[0] = True

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)


def refresh(config: Config) -> None:
    """Perform a single metric refresh cycle.

    Discovers topics matching the configured prefixes, retrieves the latest
    message timestamp from each in parallel, and updates the Prometheus gauges.
    Sets ``topic_metric_exporter_up`` to 1 on success or 0 on failure.

    Each topic is processed in its own thread with its own Kafka consumer to
    avoid blocking on slow/empty topics.  A thread pool of 20 workers processes
    topics concurrently.

    Args:
        config: Application configuration.
    """
    try:
        topics = discover_topics(config)
        logger.info("Topics discovered: %s", topics)
        if not topics:
            logger.warning(
                "No topics found matching prefixes %r — metrics will not be emitted",
                config.topic_prefixes,
            )
            set_exporter_healthy()
            return

        logger.info("Processing %d topics with %d workers", len(topics), 20)
        processed = 0
        with ThreadPoolExecutor(max_workers=10, thread_name_prefix="topic-worker") as executor:
            future_to_topic = {executor.submit(get_topic_timestamp, config, topic): topic for topic in topics}

            for future in as_completed(future_to_topic):
                topic = future_to_topic[future]
                try:
                    result = future.result()
                    if result.max_timestamp_ms is not None:
                        update_topic_metrics(
                            topic=result.topic,
                            timestamp_ms=result.max_timestamp_ms,
                        )
                        processed += 1
                    else:
                        logger.info("Topic %r has no retrievable timestamp; skipping metric update", topic)
                except Exception as exc:  # pylint: disable=broad-except
                    logger.error("Error processing topic %r: %s", topic, exc, exc_info=True)

        set_exporter_healthy()
        logger.info("Refresh cycle complete — %d/%d topic(s) with data", processed, len(topics))

    except KafkaException as exc:
        logger.error("Kafka error during refresh: %s", exc, exc_info=True)
        set_exporter_unhealthy()

    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Unexpected error during refresh: %s", exc, exc_info=True)
        set_exporter_unhealthy()


def main() -> None:
    """Application entrypoint.

    Loads config, starts the metrics HTTP server, then enters the refresh loop.
    The loop sleeps for ``SCRAPE_INTERVAL_SECONDS`` between cycles and exits
    cleanly on SIGTERM / SIGINT.
    """
    config = Config()

    _configure_logging(config.log_level)
    logger.info(
        "Starting kafka-topic-freshness-exporter: bootstrap=%r prefix=%r interval=%ds protocol=%s",
        config.kafka_bootstrap_servers,
        config.topic_prefix,
        config.scrape_interval_seconds,
        config.kafka_security_protocol,
    )

    start_metrics_server(config.metrics_port)

    shutdown_flag: list[bool] = [False]
    _install_signal_handlers(shutdown_flag)

    while not shutdown_flag[0]:
        cycle_start = time.monotonic()
        logger.info("Beginning refresh cycle")
        refresh(config)
        elapsed = time.monotonic() - cycle_start

        sleep_duration = max(0.0, config.scrape_interval_seconds - elapsed)
        logger.info("Refresh took %.2fs; sleeping %.2fs", elapsed, sleep_duration)

        slept = 0.0
        while slept < sleep_duration and not shutdown_flag[0]:
            time.sleep(min(1.0, sleep_duration - slept))
            slept += 1.0

    logger.info("Exporter shut down cleanly")
