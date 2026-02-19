"""
Simple fixtures for simple tests
"""

import os
import time
from logging import getLogger
from typing import Generator

import pytest
from confluent_kafka import Producer
from confluent_kafka.admin import AdminClient

logger = getLogger(__name__)


KAFKA_BOOTSTRAP = "127.0.0.1:9092"


def _delivery_report(err, msg) -> None:
    """Callback message to force error"""
    if err is not None:
        logger.error("Delivery failed with error %s, message: %s", err, msg)
        raise RuntimeError(f"Delivery failed: {err}")


def produce_message(topic: str, value: str) -> None:
    """Make a nice message on a nice topic. :)"""
    producer = Producer(
        {
            "bootstrap.servers": KAFKA_BOOTSTRAP,
            "broker.address.family": "v4",  # Force IPv4 to avoid IPv6 connection attempts
        },
    )
    producer.produce(topic, value=value.encode("utf-8"), callback=_delivery_report)
    producer.flush(timeout=10)


@pytest.fixture(scope="session", autouse=True)
def kafka_env() -> Generator[None, None, None]:
    """
    Configure environment variables required by exporter.

    NOTE: This assumes Kafka is already running!
    """
    os.environ["KAFKA_BOOTSTRAP_SERVERS"] = KAFKA_BOOTSTRAP
    os.environ["TOPIC_PREFIX"] = "some-prefix-;one-table"
    os.environ["AWS_REGION"] = "us-east-1"
    os.environ["KAFKA_SECURITY_PROTOCOL"] = "PLAINTEXT"
    os.environ["LOG_LEVEL"] = "DEBUG"

    logger.info("TEST ENVIRONMENT CONFIGURATION")
    logger.info("=" * 60)
    logger.info("KAFKA_BOOTSTRAP_SERVERS: %s", os.environ["KAFKA_BOOTSTRAP_SERVERS"])
    logger.info("TOPIC_PREFIX: %s", os.environ["TOPIC_PREFIX"])
    logger.info("AWS_REGION: %s", os.environ["AWS_REGION"])
    logger.info("LOG_LEVEL: %s", os.environ["LOG_LEVEL"])
    logger.info("=" * 60)

    yield

    logger.info("Test session complete")


@pytest.fixture
def seed_topics() -> None:
    """
    Produce one message to each test topic.
    Wait for Kafka to be ready first.
    """
    logger.info("SEED_TOPICS: Starting to seed test topics")
    logger.info("=" * 60)

    max_retries = 30
    for attempt in range(max_retries):
        try:
            admin = AdminClient(
                {
                    "bootstrap.servers": KAFKA_BOOTSTRAP,
                    "broker.address.family": "v4",
                }
            )
            metadata = admin.list_topics(timeout=5)
            logger.info("Kafka is ready! Found %d topics", len(metadata.topics))
            break
        except Exception as e:  # pylint: disable=broad-exception-caught
            if attempt < max_retries - 1:
                logger.warning("Waiting for Kafka... attempt %d/%d: %s", attempt + 1, max_retries, e)
                time.sleep(2)
            else:
                logger.error("Kafka did not become ready after %d attempts", max_retries)
                raise

    topics = [
        "one-table-one",
        "some-prefix-table-two",
        "other-prefix-table",
    ]

    logger.info("Producing messages to %d topics...", len(topics))
    for topic in topics:
        message = f"test-{time.time()}"
        logger.info("  Producing to topic '%s': %s", topic, message)
        try:
            produce_message(topic, message)
            logger.info("  ✓ Successfully produced to '%s'", topic)
        except Exception as e:
            logger.error("  ✗ Failed to produce to '%s': %s", topic, e)
            raise

    logger.info("Waiting for messages to be committed...")
    time.sleep(1)
    logger.info("Test topics seeded successfully")
