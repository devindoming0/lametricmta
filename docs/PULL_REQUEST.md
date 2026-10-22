# Proposed pull request

Title: Restore LaMetric subway arrivals for 42 St ACE and 49 St NRW

## Description

Add a Python service that reads MTA GTFS-Realtime feeds for A/C/E at 42 St–Port Authority and N/R/W at 49 St, then supplies indexed LaMetric frames through local push or an HTTP polling endpoint. The display removes expired predictions, labels fresh cached data after failures, and replaces stale predictions with an explicit warning.

Includes grouped and per-line layouts, direction selection, health/readiness endpoints, optional polling authentication, pinned dependencies, Docker/Compose configuration, CI, an engineering plan and a device setup guide.

Validation: 21 automated tests and `pip check` pass. Live MTA decoding and continuous-service HTTP/readiness/SIGTERM checks pass. Physical LaMetric delivery, Docker build and deployment soak testing remain pending.
