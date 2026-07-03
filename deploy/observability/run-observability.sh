#!/bin/sh
set -eu

/usr/bin/loki -config.file=/etc/loki/loki-config.yml &
LOKI_PID=$!

/usr/bin/promtail -config.file=/etc/promtail/promtail-config.yml &
PROMTAIL_PID=$!

shutdown() {
  kill -TERM "$PROMTAIL_PID" "$LOKI_PID" 2>/dev/null || true
  wait "$PROMTAIL_PID" 2>/dev/null || true
  wait "$LOKI_PID" 2>/dev/null || true
}

trap shutdown INT TERM

while true; do
  if ! kill -0 "$LOKI_PID" 2>/dev/null; then
    wait "$LOKI_PID"
    exit $?
  fi
  if ! kill -0 "$PROMTAIL_PID" 2>/dev/null; then
    wait "$PROMTAIL_PID"
    exit $?
  fi
  sleep 2
done
