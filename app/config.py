"""Configuration module — all settings sourced from environment variables.

Pydantic-settings reads each field from the matching environment variable
(case-insensitive by default) and performs type coercion and validation
automatically.  The ``Config`` class is intentionally frozen so it can be
passed around safely without risk of mutation.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Application configuration, populated entirely from environment variables.

    Required variables (no default):
        - KAFKA_BOOTSTRAP_SERVERS
        - TOPIC_PREFIX
        - AWS_REGION

    All other variables are optional and fall back to sensible defaults.
    """

    model_config = SettingsConfigDict(frozen=True)

    kafka_bootstrap_servers: str = Field(description="Comma-separated list of Kafka broker host:port pairs.")
    topic_prefix: str = Field(description="Only topics whose names start with this string are scraped.")
    aws_region: str = Field(description="AWS region used when generating MSK IAM tokens.")

    kafka_security_protocol: str = Field(
        default="SASL_SSL", description="Kafka security protocol. Use PLAINTEXT for local dev / CI."
    )
    scrape_interval_seconds: int = Field(
        default=600,  # 10 minutes
        ge=1,
        description="How often (in seconds) to refresh all topic metrics.",
    )
    metrics_port: int = Field(default=8000, description="TCP port the Prometheus /metrics HTTP server listens on.")
    consumer_timeout_ms: int = Field(default=2000, description="Milliseconds to wait when polling latest message.")
    topic_discovery_timeout_s: float = Field(default=10.0, description="Seconds to wait for broker metadata responses.")
    log_level: str = Field(default="INFO", description="Python logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).")

    @property
    def topic_prefixes(self) -> list[str]:
        """
        Returns topic prefixes as a list.

        Supports:
          - "prefix_one"
          - "prefix_one;prefix_two"
        """
        return [p.strip() for p in self.topic_prefix.split(";") if p.strip()]  # pylint: disable=no-member
