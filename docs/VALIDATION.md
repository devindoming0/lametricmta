# Validation record

Date: October 22, 2026. Runtime: Python 3.12.14 on Linux.

## Passed

- **21 automated tests**: `python -m unittest discover -s tests -v`.
- Dependency consistency: `pip check` reported no broken requirements.
- MTA's current regular subway GTFS `stops.txt` confirmed `A27N/S` for 42 St–Port Authority and `R15N/S` for 49 St.
- Both official realtime feeds returned HTTP 200 without an API key and decoded successfully using the pinned bindings.
- At approximately 9:10 a.m. America/New_York, the first live diagnostic found **95 filtered predictions** across the four selected platforms: 27 at A27N, 27 at A27S, 20 at R15N, and 21 at R15S. Source ages were approximately 4.7 seconds and 14.7 seconds. This is one observation, not an accuracy or availability guarantee.
- A separate live process smoke check started the continuous service, reached readiness with both feeds live, fetched four indexed frames over HTTP, confirmed `Cache-Control: no-store, max-age=0`, and terminated through SIGTERM with exit code 0.
- The push request contract was tested with a mocked transport: HTTPS POST, app access-token header, and indexed frame JSON. Retry, unchanged-payload suppression, heartbeat and push readiness were tested separately.

## Automated coverage

Exact route/stop/direction filtering; exclusion of Q; canceled/deleted trips; deleted entities; skipped/NO_DATA stops; departure-only fallback; missing timestamps; duplicate and distinct trip instances; removed trains; countdown rounding and expiry without refetch; horizon filtering; stale/future trip timestamps; partial outage and labeled fresh cache; frozen feeds; regressed timestamps; corrupt protobuf; unsupported differential feeds; unavailable startup; grouped/per-route layouts; HTTP auth and readiness; no request-triggered MTA fetches; push retry/heartbeat/request format; and configuration validation.

## Not yet validated

- Physical LaMetric delivery, authentication, firmware behavior, app frame configuration, scrolling readability and rotation under frequent updates.
- Docker image build or Compose startup: Docker is not installed in this development environment.
- A permanent always-on home or cloud deployment.
- A 24–48 hour soak, host/clock reboot recovery and network interruption test on Devin's LAN.
- End-to-end latency or prediction accuracy against actual platform arrivals.
