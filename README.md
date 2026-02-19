# Kafka Topic Freshness Exporter

A lightweight, stateless Prometheus exporter that tracks **topic freshness** by reading
the most-recent message timestamp from each matching Kafka topic and exposing it as a gauge.

Designed for AWS MSK (IAM authentication), but works equally well against any Kafka cluster.

---

## What It Does

For each Kafka topic matching `TOPIC_PREFIX` (e.g. `prefix-*`):

1. Lists all partitions.
2. Fetches the high-water-mark offset per partition.
3. Seeks to `high_watermark - 1` and polls once — **no consumer group, no offset commit**.
4. Extracts the Kafka log-append timestamp of that message.
5. Takes the maximum timestamp across all partitions.
6. Exposes the result as a [Prometheus gauge](https://prometheus.io/docs/concepts/metric_types/#gauge):

```
topic_last_event_timestamp_seconds{topic="pub-payments-orders"} 1718000000.123
```

Prometheus / Grafana then computes:

```promql
time() - topic_last_event_timestamp_seconds
```

to tell you **how many seconds ago** a topic last received a message — instantly surfacing
silent pipeline failures.

---

## Metrics

### `topic_last_event_timestamp_seconds`

Unix timestamp (seconds, float) of the most-recent Kafka event for the topic.

| Label   | Description           | Example               |
|---------|-----------------------|-----------------------|
| `topic` | Full Kafka topic name | `pub-payments-orders` |

### `topic_metric_exporter_up`

`1.0` if the last scrape cycle completed without errors; `0.0` otherwise.
Use this to alert if the exporter itself is broken.

---

## Configuration

All configuration is via environment variables.

| Variable                    | Required | Default    | Description                                            |
|-----------------------------|----------|------------|--------------------------------------------------------|
| `KAFKA_BOOTSTRAP_SERVERS`   | ✅       | —          | Comma-separated `host:port` list                       |
| `TOPIC_PREFIX`              | ✅       | —          | Only topics starting with this prefix are scraped      |
| `AWS_REGION`                | ✅       | —          | AWS region (used for MSK IAM token generation)         |
| `KAFKA_SECURITY_PROTOCOL`   | ❌       | `SASL_SSL` | `SASL_SSL` for MSK IAM; `PLAINTEXT` for local dev      |
| `SCRAPE_INTERVAL_SECONDS`   | ❌       | `30`       | How often to refresh metrics                           |
| `METRICS_PORT`              | ❌       | `8000`     | Port the `/metrics` HTTP server listens on             |
| `CONSUMER_TIMEOUT_MS`       | ❌       | `3000`     | Poll timeout when fetching the latest message          |
| `TOPIC_DISCOVERY_TIMEOUT_S` | ❌       | `10.0`     | Timeout for broker metadata calls                      |
| `LOG_LEVEL`                 | ❌       | `INFO`     | Python logging level (`DEBUG`, `INFO`, `WARNING`, …)   |

---

## Running Locally

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) + Docker Compose
- [uv](https://docs.astral.sh/uv/getting-started/installation/)

### 1 — Start the full local stack

```bash
docker compose up -d
```

This starts:

| Service      | URL / Port              | Purpose                             |
|--------------|-------------------------|-------------------------------------|
| `broker`     | `localhost:9092`        | Kafka broker (KRaft mode)           |
| `kafka-setup`| —                       | One-shot topic creation             |
| `kafbat-ui`  | http://localhost:8080   | Kafka UI (browse topics / messages) |
| `exporter`   | http://localhost:8000   | This service                        |
| `prometheus` | http://localhost:9090   | Prometheus (scrapes exporter)       |
| `grafana`    | http://localhost:3000   | Grafana (auto-provisioned dashboard) |

> Grafana default credentials: **admin / admin**. The *Topic Pipeline Freshness* dashboard is
> pre-provisioned under **Dashboards → Topic Pipeline Freshness**.

### 2 — Run the exporter directly (without Docker)

```bash
docker compose up -d broker kafka-setup   # broker only

export KAFKA_BOOTSTRAP_SERVERS=localhost:9092
export TOPIC_PREFIX=pub-
export AWS_REGION=us-east-1
export KAFKA_SECURITY_PROTOCOL=PLAINTEXT

uv run -m app
```

Access metrics at http://localhost:8000/metrics.

### 3 — Produce test messages

Use the Kafbat UI at http://localhost:8080 or the CLI:

```bash
docker exec -it broker kafka-console-producer \
  --bootstrap-server broker:29092 \
  --topic pub-payments-orders
```

---

## Running Tests

Tests require a live Kafka broker. Start one first:

```bash
docker compose up -d broker kafka-setup
```

Then:

```bash
uv run pytest --log-cli-level=DEBUG -s -vv --cov-report term-missing --cov=app tests
```

---

## Deployment (Kubernetes / Helm)

A Helm chart is provided under `charts/kafka-topic-freshness-exporter/`.

### Build & push the image

```bash
docker build -t <AWS_ACCOUNT_ID>.dkr.ecr.<AWS_REGION>.amazonaws.com/<REPO>:latest .
docker push <AWS_ACCOUNT_ID>.dkr.ecr.<AWS_REGION>.amazonaws.com/<REPO>:latest
```

### Install the chart

```bash
helm upgrade --install cdc-freshness-exporter charts/kafka-custom-metrics-exporter \
  --set image.repository=<AWS_ACCOUNT_ID>.dkr.ecr.<AWS_REGION>.amazonaws.com/<REPO> \
  --set image.tag=latest \
  --set env.kafkaBootstrapServers=<MSK_BOOTSTRAP_ENDPOINT> \
  --set env.topicPrefix=pub- \
  --set env.awsRegion=us-east-1
```

The chart includes a `ServiceMonitor` for the Prometheus Operator (enabled by default). Ensure
the Prometheus Operator is installed and its `ServiceMonitor` CRD is available.

### IAM permissions

The pod needs the following MSK IAM action:

```json
{
  "Effect": "Allow",
  "Action": "kafka-cluster:*",
  "Resource": "arn:aws:kafka:<REGION>:<ACCOUNT>:cluster/<CLUSTER_NAME>/*"
}
```

Attach this policy to the pod's IAM role via IRSA (IAM Roles for Service Accounts).

---

## Example PromQL

```promql
# Topics silent for more than 5 minutes
time() - topic_last_event_timestamp_seconds > 300

# Staleness in minutes, per topic
(time() - topic_last_event_timestamp_seconds) / 60

# Is the exporter itself healthy?
topic_metric_exporter_up == 0
```

### Grafana Alerting

```yaml
# Alert: topic silent > 5 min
expr: time() - topic_last_event_timestamp_seconds > 300
for: 1m
labels:
  severity: critical
annotations:
  summary: "Topic {{ $labels.topic }} is stale"
  description: "No events received in {{ $value | humanizeDuration }}"
```

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                         Kubernetes Pod                           │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │                  kafka-metrics-exporter                     │  │
│  │                                                            │  │
│  │  config.py ──► main.py ──► kafka_client.py                 │  │
│  │                  │              │                          │  │
│  │                  │     discover_topics()                   │  │
│  │                  │     get_topic_timestamp()               │  │
│  │                  ▼              │                          │  │
│  │             metrics.py ◄────────┘                          │  │
│  │          update_topic_metrics()                            │  │
│  │          /metrics  (port 8000)                             │  │
│  └────────────────────────────────────────────────────────────┘  │
│                          │                                       │
└──────────────────────────┼───────────────────────────────────────┘
                           │ scrape every 30s
                    ┌──────┴──────┐
                    │ Prometheus  │
                    └──────┬──────┘
                           │
                    ┌──────┴──────┐
                    │   Grafana   │
                    └─────────────┘
```

---

## CI / CD

GitHub Actions pipeline (`.github/workflows/ci.yml`):

| Job                 | Trigger          | What it does                                           |
|---------------------|------------------|--------------------------------------------------------|
| `pre-commit`        | All pushes / PRs | black, isort, pylint, trailing-whitespace              |
| `unit-tests`        | After pre-commit | pytest on `test_config.py` + `test_metrics.py`        |
| `integration-tests` | After unit tests | Docker Compose Kafka + `test_main.py`                  |
| `docker-build`      | After int tests  | Validates the Dockerfile builds cleanly                |
| `docker-push`       | Merge to main    | Builds and pushes to ECR (requires secrets below)      |

### Required GitHub Secrets (for ECR push)

| Secret         | Description                                  |
|----------------|----------------------------------------------|
| `AWS_ROLE_ARN` | IAM role ARN to assume via OIDC              |
| `AWS_REGION`   | AWS region for ECR                           |
| `ECR_REPOSITORY` | ECR repository name (without account/region prefix) |
