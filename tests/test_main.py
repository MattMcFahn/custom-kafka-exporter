"""
Simple tests for a simple dev.
"""

import logging
import threading
import time
from urllib.request import urlopen

from app.main import main

logger = logging.getLogger(__name__)

EXPORTER_PORT = 8000


def scrape_metrics() -> str:
    """Simple scrape"""
    with urlopen(f"http://localhost:{EXPORTER_PORT}/metrics") as response:
        return response.read().decode("utf-8")


def test_main(seed_topics) -> None:  # pylint: disable=unused-argument
    """
    Validate:
    - Topics matching prefix are exported
    - Non-matching topics are ignored
    - Exporter health metric is set
    """
    logger.info("TEST: Starting test_prefix_filtering")
    logger.info("=" * 60)

    # First, test that we can connect BEFORE starting the exporter
    logger.info("Pre-flight check: Testing Kafka connectivity...")
    logger.info("Starting exporter thread...")

    # TODO: Just waiting 10 seconds for completion is a terrible pattern.
    #  Ideally "main" should be refactored to a single iteration runner
    thread = threading.Thread(target=main, daemon=True)
    thread.start()
    time.sleep(3)

    # Wait for exporter to start
    logger.info("Waiting for exporter to start...")

    logger.info("Scraping final metrics for validation...")
    metrics = scrape_metrics()

    logger.info("METRICS OUTPUT:")
    logger.info("=" * 60)
    for line in metrics.split("\n"):
        if line and not line.startswith("#"):
            logger.info(line)
    logger.info("=" * 60)

    # Parse and display Topic metrics specifically
    topic_lines = [line for line in metrics.split("\n") if "topic_last_event" in line and not line.startswith("#")]
    logger.info("Topic Metrics Found:")
    if topic_lines:
        for line in topic_lines:
            logger.info("  %s", line)
    else:
        logger.warning("  (none)")

    # Check exporter health first
    if "topic_metric_exporter_up 1.0" not in metrics:
        logger.error("=" * 60)
        logger.error("✗ FAIL: Exporter is not healthy!")
        logger.error("=" * 60)
        logger.error("topic_metric_exporter_up is not 1.0 - this means refresh() is failing")
        logger.error("")
        logger.error("The error should be logged above. Look for lines containing:")
        logger.error("  - 'Kafka error during refresh'")
        logger.error("  - 'Unexpected error during refresh'")
        logger.error("  - 'Failed to discover topics'")
        logger.error("  - Exception stack traces")
        logger.error("=" * 60)
        raise AssertionError("Exporter health check failed: topic_metric_exporter_up is not 1.0")

    # Should include matching topic
    assert 'topic_last_event_timestamp_seconds{topic="one-table-one"}' in metrics
    assert 'topic_last_event_timestamp_seconds{topic="some-prefix-table-two"}' in metrics
    assert "topic_metric_exporter_up 1.0" in metrics
    assert not "some-prefix-table-one" in metrics
    assert "other-prefix-table" not in metrics
