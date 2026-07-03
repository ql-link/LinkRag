FROM grafana/promtail:2.9.8 AS promtail
FROM grafana/loki:2.9.8 AS loki

FROM debian:bookworm-slim

COPY --from=loki /usr/bin/loki /usr/bin/loki
COPY --from=promtail /usr/bin/promtail /usr/bin/promtail
COPY run-observability.sh /usr/local/bin/run-observability.sh
RUN chmod +x /usr/local/bin/run-observability.sh \
    && mkdir -p /loki /tmp

ENTRYPOINT ["/usr/local/bin/run-observability.sh"]
