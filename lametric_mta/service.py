from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
import logging
import math
import ssl
import threading
import time
from urllib.request import HTTPSHandler, HTTPRedirectHandler, Request, build_opener, urlopen

from .config import FEEDS, STATIONS, Settings
from .transit import Snapshot, parse_feed

LOG = logging.getLogger(__name__)
MAX_FEED_BYTES = 4 * 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        # Never forward an app access token to a redirect destination.
        return None


@dataclass(frozen=True)
class FeedState:
    snapshot: Snapshot | None = None
    error: str | None = None


def fetch_feed(url: str, timeout: float) -> bytes:
    request = Request(url, headers={"User-Agent": "lametricmta/0.1 (personal arrival display)",
                                    "Accept": "application/x-protobuf"})
    with urlopen(request, timeout=timeout) as response:
        data = response.read(MAX_FEED_BYTES + 1)
    if len(data) > MAX_FEED_BYTES:
        raise ValueError("feed_too_large")
    return data


def countdown(seconds: float) -> str:
    return "<1" if seconds < 60 else str(math.ceil(seconds / 60))


class ArrivalService:
    def __init__(self, settings: Settings, fetcher=fetch_feed, clock=time.time):
        self.settings = settings
        self.fetcher = fetcher
        self.clock = clock
        self._lock = threading.Lock()
        self._feeds = {key: FeedState() for key in FEEDS}
        self._push_success: float | None = None
        self._push_error: str | None = None

    def refresh(self):
        def get(key, url):
            try:
                data = self.fetcher(url, self.settings.timeout_seconds)
                return parse_feed(data, key, self.clock()), None
            except Exception as exc:
                # Exception messages may include configured URLs; log only the class.
                return None, type(exc).__name__
        with ThreadPoolExecutor(max_workers=2) as pool:
            tasks = {key: pool.submit(get, key, url) for key, url in FEEDS.items()}
            for key, task in tasks.items():
                snapshot, error = task.result()
                with self._lock:
                    old = self._feeds[key].snapshot
                    if snapshot and old and snapshot.timestamp < old.timestamp:
                        snapshot, error = None, "regressed_feed_timestamp"
                    self._feeds[key] = FeedState(snapshot or old, error)
                if error:
                    LOG.warning("feed_refresh_failed feed=%s reason=%s", key, error)

    def view(self):
        now = self.clock()
        with self._lock:
            states = self._feeds.copy()
            push_success, push_error = self._push_success, self._push_error
        feeds = {}
        for key, state in states.items():
            snapshot = state.snapshot
            age = max(0, now - snapshot.timestamp) if snapshot else None
            fresh = bool(snapshot and now - snapshot.received_at <= self.settings.stale_seconds
                         and age <= self.settings.stale_seconds and snapshot.timestamp <= now + 30)
            feeds[key] = {"status": ("cached" if state.error else "live") if fresh else
                          ("stale" if snapshot else "unavailable"),
                          "timestamp": snapshot.timestamp if snapshot else None,
                          "age_seconds": round(age, 1) if age is not None else None,
                          "error": state.error}
        groups, frames = [], []
        for station in STATIONS:
            state = states[station.feed]
            status = feeds[station.feed]["status"]
            usable = status in ("live", "cached")
            for direction in self.settings.directions:
                stop_id = station.stop + direction
                arrivals = [a for a in state.snapshot.arrivals if a.stop_id == stop_id
                            and now <= a.timestamp <= now + self.settings.horizon_minutes * 60
                            and (a.prediction_timestamp is None or
                                 now - self.settings.stale_seconds <= a.prediction_timestamp <= now + 30)] if usable else []
                groups.append({"station": station.name, "stop_id": stop_id, "direction": direction,
                               "status": status, "routes": list(station.routes),
                               "arrivals": [{"route": a.route, "trip_id": a.trip_id, "timestamp": a.timestamp,
                                             "seconds": round(a.timestamp - now),
                                             "minutes": countdown(a.timestamp - now)} for a in arrivals]})
                prefix = ("~" if status == "cached" else "") + station.label + ("U" if direction == "N" else "D")
                route_groups = [(r, [a for a in arrivals if a.route == r]) for r in station.routes] if self.settings.display_mode == "routes" else [(None, arrivals)]
                for route, selected in route_groups:
                    label = prefix + (f" {route}" if route else "")
                    if not usable:
                        text = label + (" STALE" if status == "stale" else " NO DATA")
                    elif not selected:
                        text = label + " NO ETA"
                    else:
                        times = [("" if route else a.route) + countdown(a.timestamp - now)
                                 for a in selected[:self.settings.arrivals_per_frame]]
                        text = label + " " + " ".join(times)
                    frames.append({"index": len(frames), "text": text})
        push = {"enabled": bool(self.settings.push_url), "last_success": push_success, "error": push_error}
        source_ready = all(f["status"] == "live" for f in feeds.values())
        push_ready = not self.settings.push_url or (push_success is not None and not push_error
                       and now - push_success <= 120)
        return {"generated_at": now, "ready": source_ready and push_ready, "feeds": feeds,
                "push": push, "groups": groups, "frames": frames}

    def record_push(self, error: str | None):
        with self._lock:
            self._push_error = error
            if error is None:
                self._push_success = self.clock()

    def collect_forever(self, stop: threading.Event):
        while not stop.is_set():
            started = time.monotonic()
            self.refresh()
            stop.wait(max(0, self.settings.poll_seconds - (time.monotonic() - started)))


class Publisher:
    def __init__(self, service: ArrivalService, sender=None, monotonic=time.monotonic):
        self.service = service
        self.sender = sender or self._send
        self.monotonic = monotonic
        self._last_payload = None
        self._last_sent = float("-inf")

    def _send(self, payload):
        settings = self.service.settings
        context = ssl.create_default_context(cafile=settings.ca_bundle or None)
        if not settings.verify_tls:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        request = Request(settings.push_url, data=json.dumps(payload).encode(), method="POST",
                          headers={"Content-Type": "application/json", "Accept": "application/json",
                                   "X-Access-Token": settings.push_token})
        opener = build_opener(HTTPSHandler(context=context), NoRedirect())
        with opener.open(request, timeout=settings.timeout_seconds) as response:
            if not 200 <= response.status < 300:
                raise ValueError("push_rejected")

    def tick(self):
        payload = {"frames": self.service.view()["frames"]}
        now = self.monotonic()
        if payload == self._last_payload and now - self._last_sent < 60:
            return
        try:
            self.sender(payload)
        except Exception as exc:
            self.service.record_push(type(exc).__name__)
            LOG.warning("device_push_failed reason=%s", type(exc).__name__)
        else:
            self._last_payload, self._last_sent = payload, now
            self.service.record_push(None)

    def run(self, stop: threading.Event):
        while not stop.is_set():
            self.tick()
            stop.wait(self.service.settings.render_seconds)
