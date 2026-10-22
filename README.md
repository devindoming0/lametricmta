# LaMetric MTA

A personal subway arrival display for **A/C/E at 42 St–Port Authority Bus Terminal** and **N/R/W at 49 St**. Python 3.12, direct MTA GTFS-Realtime feeds, no MTA API key, no database.

Read the [engineering plan](docs/ENGINEERING_PLAN.md), [device setup guide](docs/SETUP.md), and [validation record](docs/VALIDATION.md).

## What the clock shows

Four frames by default, in this order. These examples are illustrative:

| Frame | Meaning |
| --- | --- |
| `42U A3 E6` | 42 St, uptown: A in 3 min; E in 6 min |
| `42D C2 E5` | 42 St, downtown: C in 2 min; E in 5 min |
| `49U W4 R8` | 49 St, uptown: W in 4 min; R in 8 min |
| `49D N<1 R7` | 49 St, downtown: N in under 1 min; R in 7 min |

`~` marks a temporarily cached result after a failed fetch. `STALE` replaces predictions after 90 seconds. `NO ETA` means the fresh feed has no usable predictions within the next 60 minutes; it does **not** mean service is suspended. `NO DATA` means no usable feed has arrived yet. The service never substitutes the static timetable.

Grouped mode shows the next two trains across the selected routes; a route with a later arrival can be absent from that frame. Use `DISPLAY_MODE=routes` for twelve frames showing each line separately. `DIRECTIONS=S` or `N` halves the frame count. Minutes round up; predictions strictly before the current time disappear. Text may scroll on the physical display.

## Run without a device

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m lametric_mta --once
python -m lametric_mta --diagnose
```

`--once` prints live LaMetric JSON. `--diagnose` includes feed timestamps and all filtered arrivals. Both are read-only diagnostics: they never send anything to the clock, and exit nonzero if either feed is unavailable or stale.

## Run continuously

```bash
python -m lametric_mta
```

The native command reads environment variables, **not `.env` files automatically**. It binds to `127.0.0.1:8080` by default. See [.env.example](.env.example) for supported settings.

Docker Compose loads `.env` and restarts the service automatically:

```bash
cp .env.example .env
# Edit .env: optionally configure your clock's push URL and app access token.
docker compose up -d --build
docker compose logs -f
```

Compose exposes the HTTP endpoint only on the host's loopback interface. Push still reaches a clock on the same routable LAN. On Docker Desktop, allow local network access if prompted. For a polling clock, see the explicit LAN binding instructions in [SETUP.md](docs/SETUP.md).

## HTTP endpoints

| Path | Response |
| --- | --- |
| `/lametric` | `{ "frames": [...] }`; HTTP 200 with useful outage text even when MTA is down |
| `/api/arrivals` | Predictions, frames, per-feed health, and device push status |
| `/healthz` | Process liveness, without an upstream call |
| `/readyz` | HTTP 200 only when both feeds are live and a configured push target has a recent successful delivery; otherwise 503 |

HTTP reads use shared in-memory snapshots; they never trigger additional MTA fetches. Responses disable caching. Optional `POLL_TOKEN` authentication accepts `Authorization: Bearer …` or `?token=…` on all data endpoints. `/healthz` remains unauthenticated. Query tokens are supported for polling clients that cannot set headers; configure proxy logs to omit query strings.

## Status

The staged implementation has passed automated tests and a live MTA smoke check. It has **not** been installed on Devin's LaMetric or deployed to a permanent host. Device credentials, app configuration, frame readability, and a home-network soak test remain the activation steps. Docker files are supplied but were not built in the development environment.
