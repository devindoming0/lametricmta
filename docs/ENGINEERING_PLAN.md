# Engineering plan: revive LaMetric MTA

Prepared for Devin Domingo, October 22, 2026.

## Goal and scope

Restore an always-visible home display for A/C/E at 42 St–Port Authority Bus Terminal and N/R/W at 49 St, using the latest published MTA predictions. The initial repository contained only a README; there was no legacy app implementation to migrate.

Assumptions: the device is LaMetric TIME, both uptown and downtown are useful, and a home server, NAS, Raspberry Pi, or continuously running computer is available. Direction and layout are configuration choices. Q is deliberately excluded from the N/Q/R/W feed because the requested lines were N/R/W.

This version includes feed ingestion, filtering, countdowns, local push, a polling endpoint, authentication, health reporting, tests, container configuration, and an activation guide. It excludes journey planning, official service-alert interpretation, destination/headsign enrichment, walking-time advice, and multi-user accounts.

## Verified inputs

| Station | Requested routes | North / uptown stop | South / downtown stop | Feed suffix |
| --- | --- | --- | --- | --- |
| 42 St–Port Authority Bus Terminal | A, C, E | `A27N` | `A27S` | `nyct%2Fgtfs-ace` |
| 49 St | N, R, W | `R15N` | `R15S` | `nyct%2Fgtfs-nqrw` |

Each suffix is appended to `https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/`. Stop IDs and station names were checked against the current MTA regular subway GTFS archive. Both realtime endpoints returned HTTP 200 without an API key during validation. Filter by the exact directional stop and route, rather than by a station complex or a line's usual stopping pattern.

## Delivery choice

| Option | Where the service runs | Device integration | Tradeoff |
| --- | --- | --- | --- |
| **Recommended: local push** | Always-on machine on the clock's routable LAN | Private indicator app; exact portal-issued local push URL and app token | Direct delivery and independent countdown refresh; requires a home host |
| Local polling | Same LAN | My Data DIY or a private Poll indicator app points at `/lametric` | Simpler clock setup; actual refresh depends on the device's supported poll setting |
| Hosted polling | Always-on cloud container behind HTTPS | Poll app points at hosted `/lametric` | No home host, but hosting cost and another polling interval |

A cloud-only host cannot reach a private clock address without additional networking. Do not expose the device itself to the Internet. A temporary notification is not the chosen product behavior: this is a persistent indicator display.

The supplied Compose file implements the local service, not managed cloud provisioning. For cloud hosting, keep one always-on replica, disable scale-to-zero, use the platform's HTTPS ingress, set `HOST=0.0.0.0`, supply `POLL_TOKEN`, and leave push credentials empty. Keep the Python HTTP server behind the platform's proxy and access controls. GitHub Actions runs tests; it is not the arrival scheduler or runtime host.

## Architecture and code map

| Component | Responsibility | Implementation |
| --- | --- | --- |
| Configuration | Station/route allowlist, cadence, direction, host and secrets | `lametric_mta/config.py` |
| Decoder | Validate protobuf; normalize arrivals from complete snapshots | `lametric_mta/transit.py` |
| Collector | Fetch both feeds concurrently; retain independent per-feed state | `ArrivalService.refresh()` in `service.py` |
| View builder | Filter at read time; generate compact LaMetric frames and diagnostic JSON | `ArrivalService.view()` |
| Publisher | Send changed frames, retry failures, heartbeat every 60 seconds | `Publisher` in `service.py` |
| HTTP adapter | Shared cached views, authentication, readiness and liveness | `lametric_mta/web.py` |
| Runtime | Worker lifecycle and read-only CLI diagnostics | `lametric_mta/__main__.py` |
| Operations | Reproducible dependencies, container and restart policy | `requirements.txt`, `Dockerfile`, `compose.yaml` |

The collector and publisher run in separate threads. A slow clock does not block feed ingestion, and HTTP requests do not wait on a fresh upstream call. A lock protects replacement of immutable feed snapshots. There is no database or external queue; after restart, display NO DATA until the first successful fetch.

## Freshness and latency budget

- Fetch each MTA feed every **15 seconds** by default. This is 11,520 combined feed requests per day for one running instance.
- Recompute push frames every **5 seconds**. Send only changed content or a 60-second heartbeat. Retry a failed device delivery at the next render tick.
- HTTP frames recompute countdowns on every request. A polling device adds its own interval to the delay.
- Reject feed timestamps missing, nonpositive, or more than 30 seconds in the future. Preserve the previous snapshot if a new timestamp moves backward.
- Suppress predictions once the feed timestamp or time since the last successful fetch exceeds **90 seconds**. Repeatedly fetching a frozen feed does not make it fresh.

For healthy local push, the design target is roughly a 20-second scheduling budget after MTA publishes a change: up to 15 seconds for collection plus up to 5 seconds for rendering, **plus network time**. This is an engineering target, not a measured end-to-end guarantee. MTA's linked subway reference describes 30-second publication for the feed documented there; actual ACE/NQRW cadence and source accuracy must be observed. Polling faster cannot improve a prediction MTA has not changed. Frame rotation and scrolling add time before a person sees a particular line.

## Prediction correctness

1. Parse GTFS-Realtime with the maintained Python bindings. Validate required protobuf fields and require FULL_DATASET semantics.
2. Retain TripUpdates matching the configured stop and route. Honor canceled/deleted trips, deleted entities, and SKIPPED/NO_DATA stops.
3. Prefer explicit arrival time; use explicit departure time only when no positive arrival time exists. Do not convert a past arrival into a future arrival by substituting a later departure.
4. Do not derive predictions from delay-only updates or static schedules. Ignore unknown NYCT extensions for this MVP; train assignment/track enrichment is deferred.
5. Deduplicate by route, directional stop, trip ID, service date, and start time. Two different trains in the same minute remain distinct.
6. Replace the whole feed snapshot on success so removed trains disappear. On fetch/decode failure, retain only the still-fresh previous snapshot and mark it cached.
7. At render time, exclude past predictions, predictions beyond the configured 60-minute horizon, and explicitly timestamped trip predictions older than the freshness threshold or too far in the future.
8. Sort chronologically and round displayed minutes up, with `<1` below 60 seconds. Absolute Unix timestamps avoid local-date and daylight-saving countdown calculations.

Missing realtime information is not proof of a cancellation, suspension, or good service. The display says NO ETA rather than inventing an operating status. Official alert interpretation is a separate feature.

## Display contract

Default grouped mode has four stable indexed frames: 42U, 42D, 49U, 49D. Each shows the two earliest trains across that group's requested routes. This optimizes glance time and can omit a route whose next train is farther away. Route mode has twelve frames: A/C/E, then N/R/W, per direction. Each includes its own NO ETA state. Limiting directions reduces frame count.

Configure the private indicator app with the same number and order of text frames as the selected mode. The HTTP fallback also works with My Data DIY, which documents dynamic frame arrays. `ARRIVALS_PER_FRAME=1` reduces scrolling; two is the starting default. Keep text-only frames initially, then consider icons after verifying readability. No official MTA logo assets are bundled.

## Failure behavior and observability

| Condition | Clock behavior | Diagnostic behavior |
| --- | --- | --- |
| No initial snapshot | `42U NO DATA` | Feed unavailable; readiness 503 |
| Fresh feed, no prediction | `42U NO ETA` | Live feed with empty arrivals |
| Fetch fails, cache still fresh | `~42U A3 E6` | Cached state, error class; readiness 503 |
| Frozen or expired feed | `42U STALE` | Predictions suppressed; readiness 503 |
| One source fails | Only that station group degrades | Other feed remains independent |
| Clock unreachable | Retry at the next render tick | Push error class and last success; readiness 503 |
| Service or clock connection stops entirely | Device may retain its last accepted frame | External monitoring must detect loss of delivery |

The final row is a device limitation: a process that has stopped cannot push a warning. The app has no guaranteed display expiry. A 60-second heartbeat helps diagnose connectivity; it cannot invalidate an offline display. Use container restart policy, an awake host, and external readiness monitoring for unattended use. A cloud or LAN poll client may also retain its last result during a complete outage.

Logs record feed identifiers and exception classes, never app tokens or request URLs. `/api/arrivals` exposes feed age, arrival timestamps, and push success time. `/healthz` reports process liveness; `/readyz` requires live sources plus recent delivery if push is enabled. Use liveness for automatic restarts and readiness for an operational alert; upstream failure alone should not cause a restart loop.

## Configuration and secrets

Real credentials belong in an ignored `.env` or host secret store. The app access token for the local widget endpoint is distinct from a device API key used for other LaMetric APIs. Native Python does not load `.env` automatically; Compose does. MTA subway feed access uses no secret.

Push is HTTPS with verification enabled by default and redirects disabled, preventing token forwarding. A trusted device CA can be supplied with `LAMETRIC_CA_BUNDLE`; the official LaMetric sample uses a self-signed-certificate bypass, available here only through explicit configuration. Enable that only for the known device on a trusted LAN. The HTTP poll API supports a separate optional token. Prefer a Bearer header; for clients requiring a query token, omit query strings from ingress logs.

## Implementation and activation milestones

| Milestone | Deliverable | Acceptance | State |
| --- | --- | --- | --- |
| 1. Source validation | Verified stop/feed mapping | Decode both live feeds without a key | Completed |
| 2. Core service | Filtering, frames, cache/freshness, HTTP | Automated correctness and failure tests | Completed |
| 3. Packaging | Docker/Compose, CI and setup instructions | Local Python tests pass; container files supplied | Staged; container build pending |
| 4. Device activation | Private app or DIY polling installed | All selected frames update on the physical clock | Requires device setup |
| 5. Soak and tune | Always-on deployment | 24–48 hours across rush hour, overnight, reboot and brief outage | Pending |
| 6. Optional extensions | Alerts, walking buffers, icons, remote hosting | Separate requirements and tests | Future scope |

Suggested activation effort: 30–60 minutes for app setup and local connection, then 24–48 hours of observation. This estimate assumes a host is already available and healthy. Hosting selection and new hardware acquisition are outside that estimate.

During the soak test, compare predictions against the MTA app at the **same directional platform**, observe which frame layouts are readable, confirm W's missing overnight/weekend predictions remain NO ETA, interrupt upstream access and verify STALE, restore access, and reboot both host and clock. Confirm updating the app does not repeatedly restart rotation at frame 0. If it does, increase display refresh time or use polling while preserving the 15-second source cadence.

## Rollback and next decisions

The implementation is proposed on the `codex/revive-mta-display` review branch. The physical device has not been changed or deployed. To roll back a later local deployment, stop the container, select the clock app, and restore the previous image/configuration. Keep credentials outside images and Git. No destructive data migration is involved.

Activation needs: a chosen always-on host and, for push, the portal-issued app URL/token plus installation on the clock. Those are deployment inputs; they are not required to inspect or test this code. Start with the current defaults, then choose one or both directions and grouped versus per-line display after the hardware check.

## Primary references

- [MTA developer resources](https://www.mta.info/developers): official static/realtime links and extension documentation.
- [MTA realtime portal](https://api.mta.info/): feed catalog and current access requirements.
- [MTA regular subway GTFS archive](https://rrgtfsfeeds.s3.amazonaws.com/gtfs_subway.zip): `stops.txt` used for station verification.
- [MTA subway GTFS-Realtime reference](https://new.mta.info/document/134521): directional stop IDs and published feed behavior; older document, so do not treat its examples as current route coverage guarantees.
- [GTFS-Realtime reference](https://gtfs.org/documentation/realtime/reference/): snapshot and schedule-relationship semantics.
- [GTFS Python bindings](https://gtfs.org/documentation/realtime/language-bindings/python/): decoder integration.
- [LaMetric first indicator app](https://lametric-documentation.readthedocs.io/en/latest/guides/first-steps/first-lametric-indicator-app.html): local push URL, token and payload.
- [LaMetric indicator app support](https://help.lametric.com/support/solutions/articles/6000011972-indicator-app): private app and communication settings.
- [LaMetric My Data DIY](https://help.lametric.com/support/solutions/articles/6000225467-my-data-diy): polling without building a new device app.
