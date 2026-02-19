"""Prometheus metrics definitions and update helpers.

All metrics are module-level singletons registered once at import time.
The refresh loop calls update_topic_metrics() after each successful scrape cycle.
"""

import logging

from prometheus_client import Gauge, start_http_server

logger = logging.getLogger(__name__)

TOPIC_LAST_EVENT_TIMESTAMP = Gauge(
    "topic_last_event_timestamp_seconds",
    "Unix timestamp (seconds) of the most-recent Kafka message for this topic.",
    labelnames=["topic"],
)

EXPORTER_UP = Gauge(
    "topic_metric_exporter_up",
    "1 if the last scrape cycle completed without Kafka errors, 0 otherwise.",
)


def start_metrics_server(port: int) -> None:
    """Start the Prometheus HTTP server on the given port.

    Args:
        port: TCP port to bind. Defaults to 8000 in the application config.
    """
    start_http_server(port)
    logger.info("Prometheus metrics HTTP server started on port %d", port)


def update_topic_metrics(topic: str, timestamp_ms: int) -> None:
    """Set the freshness gauge for a single topic.

    Args:
        topic: Kafka topic name, used directly as the ``topic`` label value.
        timestamp_ms: Latest message timestamp in milliseconds.
    """
    timestamp_s = timestamp_ms / 1000.0
    TOPIC_LAST_EVENT_TIMESTAMP.labels(topic=topic).set(timestamp_s)
    logger.debug("Updated metric: topic=%r ts=%.3f", topic, timestamp_s)


def set_exporter_healthy() -> None:
    """Mark the exporter as healthy (scrape cycle succeeded)."""
    EXPORTER_UP.set(1)


def set_exporter_unhealthy() -> None:
    """Mark the exporter as unhealthy (scrape cycle failed)."""
    EXPORTER_UP.set(0)
