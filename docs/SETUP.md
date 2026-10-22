# Setup and activation

## 1. Verify the service before connecting the clock

Use Python 3.12 or the supplied container. From the repository root:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m lametric_mta --once
```

You should receive four indexed text frames, not an HTML page. `python -m lametric_mta --diagnose` shows source ages and filtered arrivals. Nonzero exit status means at least one source is not live; inspect diagnostics before activating the clock.

## 2. Choose local push or polling

### Recommended: private Local Push indicator app

1. Sign in to [LaMetric's developer portal](https://developer.lametric.com/) using the account associated with your TIME. If the old app is still accessible, inspect its communication mode and frame configuration first.
2. Create or update an **Indicator** app with **Local Push** communication and private visibility. Start with four text/name frames in this order: 42U, 42D, 49U, 49D. Use generic artwork if an app icon is required.
3. Publish the private version as required by the portal and install/update it on the clock through the LaMetric mobile app. Keep this app selected while testing.
4. Copy the exact **local push URL** and **app access token** from that app version. Use the clock's current LAN address and preserve the endpoint's package/version path. Reserve its DHCP address so it does not change.
5. Put these values in your local `.env` as `LAMETRIC_PUSH_URL` and `LAMETRIC_ACCESS_TOKEN`. This endpoint uses `X-Access-Token`; a device API key is a different credential.
6. Keep TLS verification enabled if the device certificate can be verified. For a private CA, supply `LAMETRIC_CA_BUNDLE` and mount that CA file into the container. If the device only supports its self-signed certificate, the documented LaMetric sample bypasses verification; this service allows the explicit `LAMETRIC_VERIFY_TLS=false` setting for that known clock on your trusted LAN.

Run:

```bash
cp .env.example .env
# Edit .env with the values above, then:
docker compose up -d --build
docker compose logs -f
```

Create `.env` before editing it; do not copy the example over an existing credential file. The application sends changed payloads and a heartbeat; no notification sound is used. A successful HTTP delivery is tracked in `/api/arrivals`, but visual confirmation on the physical clock is still required.

The container and clock must be able to communicate. Guest Wi-Fi isolation, a firewall, corporate VPN, or Docker Desktop LAN permissions can block that route. The service does not require an inbound device connection when using push.

For native Python, export the variables you need in your shell or service manager instead of expecting Python to load `.env`:

```bash
export LAMETRIC_PUSH_URL='https://CLOCK_IP:4343/api/v1/dev/widget/update/YOUR_PACKAGE/YOUR_VERSION'
export LAMETRIC_ACCESS_TOKEN='YOUR_APP_TOKEN'
python -m lametric_mta
```

The strings above are placeholders. Use the exact URL from the portal; do not guess package identifiers. Avoid entering real secrets in a shell with history enabled; prefer a service manager or local secret configuration for permanent use.

### Alternative: My Data DIY polling

This option can skip custom app creation:

1. Install [My Data DIY](https://help.lametric.com/support/solutions/articles/6000225467-my-data-diy) on the clock.
2. Run the service on a LAN host. Set `HOST=0.0.0.0` and choose a `POLL_TOKEN` if the network requires access control. Leave push URL/token blank.
3. In `compose.yaml`, replace the existing port mapping with `"8080:8080"` to expose the service on the LAN. Restrict access to your trusted LAN through the host firewall; do not forward this port from your router.
4. In the clock app, set the URL to `http://YOUR_LAN_HOST:8080/lametric` (append `?token=YOUR_POLL_TOKEN` if configured), and select the shortest suitable update interval available in your app/firmware. Start around 15 seconds when offered.
5. Confirm frames change. This URL must resolve from the clock: `localhost` would mean the clock itself, not the server.

A private Poll indicator app can use the same endpoint if you want a custom app name and icon. Align its configured frame count with the service output. For Internet-hosted polling, use an always-on host with HTTPS ingress and token authentication; hosted deployment has not been provisioned by this change.

## 3. Tune the display

| Setting | Effect |
| --- | --- |
| `DIRECTIONS=N,S` | Both directions; U means uptown and D means downtown |
| `DIRECTIONS=N` or `S` | Show only that direction |
| `DISPLAY_MODE=grouped` | Two station groups × selected directions |
| `DISPLAY_MODE=routes` | Six lines × selected directions |
| `ARRIVALS_PER_FRAME=1` | Shorter text and less scrolling |
| `ARRIVALS_PER_FRAME=2` | Default: two nearest predictions |
| `DISPLAY_REFRESH_SECONDS=5` | Local push recalculation interval; independent of source polling |

Restart the service after changing environment variables. If the private app has fixed frames, adjust/publish its configuration to match any changed direction or layout count. My Data DIY supports dynamic arrays of up to 20 frames; the provided modes have at most twelve.

Frames retain stable indexes within a configuration. During hardware testing, confirm frequent updates allow all four frames to cycle. If the clock restarts rotation on each update, increase `DISPLAY_REFRESH_SECONDS`, reduce frame length/count, or try polling.

## 4. Validate and keep running

- Compare each directional station against the MTA app, including at least one rush-hour period and an overnight period. W without a prediction should say NO ETA in route mode.
- Briefly block the host's MTA access while leaving clock connectivity intact. A failed fetch should first mark cached results with `~`, then replace them with STALE when the last source timestamp is more than 90 seconds old. Restore access and confirm recovery.
- Disconnect the clock, then restore it. Check push error/recovery in `/api/arrivals` and confirm the next update arrives.
- Reboot the host and clock. Confirm the service restarts and the reserved clock address remains valid. Keep the host awake; Compose restart policies do not wake a sleeping computer.
- Observe for 24–48 hours before treating it as the daily display. The device can retain old content if the entire service or connection dies; readiness monitoring and an always-on host reduce this risk.

Use `curl http://127.0.0.1:8080/healthz` for liveness. Inspect `/readyz` and `/api/arrivals` for source/device status, supplying a Bearer header if `POLL_TOKEN` is set. Do not configure a restart loop merely because MTA is unavailable.

Stop a Compose deployment with `docker compose down`. Logs, repository code, and `.env` remain on the host; credentials are never embedded in the image.
