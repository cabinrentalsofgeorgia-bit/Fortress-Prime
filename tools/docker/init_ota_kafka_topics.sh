#!/usr/bin/env bash
# Create OTA booking topics on the fortress-event-broker Redpanda container.
# Run on a host with Docker and the broker container up:
#   ./tools/docker/init_ota_kafka_topics.sh
#
# Inside the container, use the internal listener (127.0.0.1:9092), not the RoCE-advertised address.

set -uo pipefail

CONTAINER="${FORTRESS_EVENT_BROKER_CONTAINER:-fortress-event-broker}"
BROKERS="${FORTRESS_RPK_BROKERS:-127.0.0.1:9092}"

topics=(
  ota.booking.created
  ota.booking.modified
  ota.booking.cancelled
  inventory.availability.changed
)

for t in "${topics[@]}"; do
  if docker exec "$CONTAINER" rpk topic create "$t" --brokers "$BROKERS" -p 1 -r 1 2>/dev/null; then
    echo "created topic: $t"
  else
    echo "topic exists or create not needed: $t"
  fi
done
