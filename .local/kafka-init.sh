#!/bin/bash

set -euxo pipefail
echo "Waiting for Kafka..."
echo "Trying to create topics..."

kafka-topics \
  --create --if-not-exists \
  --bootstrap-server broker:29092 \
  --partitions 3 \
  --replication-factor 1 \
  --topic one-table-one

kafka-topics \
  --create --if-not-exists \
  --bootstrap-server broker:29092 \
  --partitions 3 \
  --replication-factor 1 \
  --topic some-prefix-table-two

kafka-topics \
  --create --if-not-exists \
  --bootstrap-server broker:29092 \
  --partitions 3 \
  --replication-factor 1 \
  --topic other-prefix-table

kafka-topics \
  --create --if-not-exists \
  --bootstrap-server broker:29092 \
  --partitions 3 \
  --replication-factor 1 \
  --topic empty-topic

echo "Done"
