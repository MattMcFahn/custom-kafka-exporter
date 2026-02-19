"""
Kafka interaction layer — topic discovery and per-partition timestamp retrieval.

Uses confluent-kafka with optional AWS MSK IAM authentication. The client never
joins a consumer group and never commits offsets; it only inspects end offsets
to read the single most-recent message per partition.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from aws_msk_iam_sasl_signer import MSKAuthTokenProvider
from confluent_kafka import Consumer, KafkaException, TopicPartition
from confluent_kafka.admin import AdminClient

from app.config import Config

logger = logging.getLogger(__name__)

_MSK_IAM_PROTOCOL = "SASL_SSL"
_MSK_IAM_MECHANISM = "OAUTHBEARER"


@dataclass(frozen=True)
class TopicTimestamp:
    """Holds the freshness result for a single Kafka topic."""

    topic: str
    max_timestamp_ms: Optional[int]


def _build_consumer_config(config: Config) -> dict:
    """Build the confluent-kafka consumer configuration dictionary.

    When the security protocol is SASL_SSL (MSK IAM), OAUTHBEARER is used
    together with the aws-msk-iam-sasl-signer-python callback.
    For PLAINTEXT (local / CI), no SASL config is added.
    """
    base: dict = {
        "bootstrap.servers": config.kafka_bootstrap_servers,
        "group.id": "kafka-metrics-exporter-no-commit",
        "group.instance.id": None,
        "enable.auto.commit": False,
        "auto.offset.reset": "latest",
        "enable.auto.offset.store": False,
        "partition.assignment.strategy": "range",
        "allow.auto.create.topics": False,
        "socket.timeout.ms": config.consumer_timeout_ms,
        "session.timeout.ms": max(config.consumer_timeout_ms * 2, 6000),
    }

    def oauth_cb(oauth_config: str) -> tuple[str, float]:
        """
        Callback to generate a new OAuth token for MSK IAM auth.

        This callback is invoked by confluent-kafka when:
        - Initially connecting to the broker
        - The current token is about to expire

        Args:
            oauth_config: OAuth configuration string (unused for MSK IAM)

        Returns:
            Tuple of (token, expiry_time_in_seconds)
        """
        logger.debug("Generating MSK IAM authentication token...")
        try:
            # Generate a signed token using AWS credentials
            token, expiry_ms = MSKAuthTokenProvider.generate_auth_token(region=config.aws_region)
            logger.debug(
                "MSK IAM token generated",
                token_length=len(token),
                expires_in_ms=expiry_ms,
            )
            return token, expiry_ms / 1000.0
        except Exception as e:
            logger.error(
                "Failed to generate MSK IAM token",
                error=str(e),
            )
            raise

    # TODO: Review this
    if config.kafka_security_protocol == _MSK_IAM_PROTOCOL:
        logger.debug("Configuring MSK IAM SASL/OAUTHBEARER authentication")

        base["security.protocol"] = _MSK_IAM_PROTOCOL
        base["sasl.mechanism"] = _MSK_IAM_MECHANISM
        base["oauth_cb"] = oauth_cb
    else:
        logger.debug("Configuring plaintext (no auth) Kafka connection")
        base["security.protocol"] = config.kafka_security_protocol

    return base


def _build_admin_config(config: Config) -> dict:
    """Build the confluent-kafka AdminClient configuration dictionary."""
    base: dict = {
        "bootstrap.servers": config.kafka_bootstrap_servers,
        "socket.timeout.ms": int(config.topic_discovery_timeout_s * 1000),
        "broker.address.family": "v4",
    }

    def oauth_cb(oauth_config: str) -> tuple[str, float]:
        """
        Callback to generate a new OAuth token for MSK IAM auth.

        This callback is invoked by confluent-kafka when:
        - Initially connecting to the broker
        - The current token is about to expire

        Args:
            oauth_config: OAuth configuration string (unused for MSK IAM)

        Returns:
            Tuple of (token, expiry_time_in_seconds)
        """
        logger.debug("Generating MSK IAM authentication token...")
        try:
            # Generate a signed token using AWS credentials
            token, expiry_ms = MSKAuthTokenProvider.generate_auth_token(region=config.aws_region)
            logger.debug(
                "MSK IAM token generated",
                token_length=len(token),
                expires_in_ms=expiry_ms,
            )
            return token, expiry_ms / 1000.0
        except Exception as e:
            logger.error(
                "Failed to generate MSK IAM token",
                error=str(e),
            )
            raise

    if config.kafka_security_protocol == _MSK_IAM_PROTOCOL:
        base["security.protocol"] = _MSK_IAM_PROTOCOL
        base["sasl.mechanism"] = _MSK_IAM_MECHANISM
        base["oauth_cb"] = oauth_cb
    else:
        base["security.protocol"] = config.kafka_security_protocol

    return base


def discover_topics(config: Config) -> list[str]:
    """Return all topic names that match the configured prefix.

    Args:
        config: Application configuration.

    Returns:
        Sorted list of matching topic names.

    Raises:
        KafkaException: If the broker metadata call fails entirely.
    """
    admin_config = _build_admin_config(config)
    admin = AdminClient(admin_config)

    logger.debug("Fetching topic metadata from broker")
    metadata = admin.list_topics(timeout=config.topic_discovery_timeout_s)

    matching = sorted(
        topic for topic in metadata.topics if any(topic.startswith(prefix) for prefix in config.topic_prefixes)
    )
    logger.info("Discovered %d topic(s) matching prefixes %r", len(matching), config.topic_prefixes)
    return matching


def get_topic_timestamp(config: Config, topic: str) -> TopicTimestamp:  # pylint:disable=too-many-locals
    """Retrieve the maximum message timestamp across all partitions of a topic."""
    consumer_config = _build_consumer_config(config)
    consumer_config["broker.address.family"] = "v4"
    consumer = Consumer(consumer_config)

    timestamps: list[int] = []

    try:
        metadata = consumer.list_topics(topic=topic, timeout=config.topic_discovery_timeout_s)
        topic_meta = metadata.topics.get(topic)

        if topic_meta is None or topic_meta.error is not None:
            logger.warning("Could not retrieve metadata for topic %r: %s", topic, topic_meta)
            return TopicTimestamp(topic=topic, max_timestamp_ms=None)

        partition_ids = list(topic_meta.partitions.keys())
        logger.info("Topic %r has %d partition(s)", topic, len(partition_ids))

        if not partition_ids:
            return TopicTimestamp(topic=topic, max_timestamp_ms=None)

        # assign all partitions at once
        tps = []
        for pid in partition_ids:
            tp = TopicPartition(topic, pid)
            try:
                low, high = consumer.get_watermark_offsets(tp, timeout=config.topic_discovery_timeout_s)
            except KafkaException as exc:
                logger.warning("Could not get watermarks for %s[%d]: %s", topic, pid, exc)
                continue

            if high <= low:
                logger.debug("Partition %s[%d] is empty (low=%d, high=%d)", topic, pid, low, high)
                continue

            # safe seek to last offset
            tp.offset = high - 1
            tps.append(tp)

        if not tps:
            return TopicTimestamp(topic=topic, max_timestamp_ms=None)

        consumer.assign(tps)

        # poll each partition once
        for _ in range(len(tps)):
            msg = consumer.poll(timeout=config.consumer_timeout_ms / 1000.0)
            if msg is None or msg.error() is not None:
                continue
            _, ts_value = msg.timestamp()
            if ts_value >= 0:
                timestamps.append(ts_value)

    finally:
        consumer.close()

    max_ts = max(timestamps) if timestamps else None
    logger.info("Topic %r: max timestamp across partitions = %s ms", topic, max_ts)
    return TopicTimestamp(topic=topic, max_timestamp_ms=max_ts)
