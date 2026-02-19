#!/usr/bin/env bash

set -euo pipefail

CONTAINER_NAME="kafka-setup"
TIMEOUT=120

echo "Waiting for '${CONTAINER_NAME}' to complete..."

START_TIME=$(date +%s)

# Wait for container to exist
while ! docker inspect "$CONTAINER_NAME" >/dev/null 2>&1; do
  if [ $(( $(date +%s) - START_TIME )) -gt $TIMEOUT ]; then
    echo "Timeout waiting for container to be created"
    exit 1
  fi
  sleep 2
done

# Wait for container to finish execution
while true; do
  RUNNING=$(docker inspect -f '{{.State.Running}}' "$CONTAINER_NAME")

  if [ "$RUNNING" = "false" ]; then
    break
  fi

  if [ $(( $(date +%s) - START_TIME )) -gt $TIMEOUT ]; then
    echo "Timeout waiting for container to finish"
    exit 1
  fi

  sleep 2
done

# Check exit code
EXIT_CODE=$(docker inspect -f '{{.State.ExitCode}}' "$CONTAINER_NAME")

if [ "$EXIT_CODE" != "0" ]; then
  echo "'${CONTAINER_NAME}' failed with exit code ${EXIT_CODE}"
  docker logs "$CONTAINER_NAME"
  exit 1
fi

echo "'${CONTAINER_NAME}' completed successfully."
