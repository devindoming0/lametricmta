from dataclasses import dataclass
import os
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Station:
    stop: str
    label: str
    name: str
    routes: tuple[str, ...]
    feed: str


STATIONS = (
    Station("A27", "42", "42 St-Port Authority Bus Terminal", ("A", "C", "E"), "ace"),
    Station("R15", "49", "49 St", ("N", "R", "W"), "nqrw"),
)
FEEDS = {
    key: "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-" + key
    for key in ("ace", "nqrw")
}


@dataclass(frozen=True)
class Settings:
    poll_seconds: float = 15
    render_seconds: float = 5
    stale_seconds: float = 90
    timeout_seconds: float = 5
    horizon_minutes: int = 60
    directions: tuple[str, ...] = ("N", "S")
    display_mode: str = "grouped"
    arrivals_per_frame: int = 2
    host: str = "127.0.0.1"
    port: int = 8080
    poll_token: str = ""
    push_url: str = ""
    push_token: str = ""
    verify_tls: bool = True
    ca_bundle: str = ""

    def __post_init__(self):
        for name in ("poll_seconds", "render_seconds", "stale_seconds", "timeout_seconds"):
            value = getattr(self, name)
            if not 0 < value <= 3600:
                raise ValueError(f"{name} must be between 0 and 3600")
        if self.poll_seconds < 5 or self.render_seconds < 1:
            raise ValueError("poll_seconds must be >= 5; render_seconds must be >= 1")
        if self.stale_seconds < self.poll_seconds:
            raise ValueError("stale_seconds must be >= poll_seconds")
        if self.display_mode not in ("grouped", "routes"):
            raise ValueError("DISPLAY_MODE must be grouped or routes")
        if not self.directions or len(set(self.directions)) != len(self.directions) or any(
            d not in ("N", "S") for d in self.directions
        ):
            raise ValueError("DIRECTIONS must contain N, S, or N,S")
        if not 1 <= self.arrivals_per_frame <= 3 or not 1 <= self.horizon_minutes <= 120:
            raise ValueError("ARRIVALS_PER_FRAME must be 1..3; HORIZON_MINUTES must be 1..120")
        if not 1 <= self.port <= 65535:
            raise ValueError("PORT must be 1..65535")
        if bool(self.push_url) != bool(self.push_token):
            raise ValueError("Set both LAMETRIC_PUSH_URL and LAMETRIC_ACCESS_TOKEN, or neither")
        if self.push_url:
            url = urlsplit(self.push_url)
            if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise ValueError("LAMETRIC_PUSH_URL must be an HTTPS URL without credentials, query or fragment")
        if any(c in self.push_token + self.poll_token for c in "\r\n"):
            raise ValueError("Tokens must not contain newlines")

    @classmethod
    def from_env(cls):
        tls = os.getenv("LAMETRIC_VERIFY_TLS", "true").lower()
        if tls not in ("true", "false"):
            raise ValueError("LAMETRIC_VERIFY_TLS must be true or false")
        return cls(
            poll_seconds=float(os.getenv("MTA_POLL_SECONDS", "15")),
            render_seconds=float(os.getenv("DISPLAY_REFRESH_SECONDS", "5")),
            stale_seconds=float(os.getenv("STALE_AFTER_SECONDS", "90")),
            timeout_seconds=float(os.getenv("HTTP_TIMEOUT_SECONDS", "5")),
            horizon_minutes=int(os.getenv("HORIZON_MINUTES", "60")),
            directions=tuple(d.strip() for d in os.getenv("DIRECTIONS", "N,S").split(",")),
            display_mode=os.getenv("DISPLAY_MODE", "grouped"),
            arrivals_per_frame=int(os.getenv("ARRIVALS_PER_FRAME", "2")),
            host=os.getenv("HOST", "127.0.0.1"),
            port=int(os.getenv("PORT", "8080")),
            poll_token=os.getenv("POLL_TOKEN", ""),
            push_url=os.getenv("LAMETRIC_PUSH_URL", ""),
            push_token=os.getenv("LAMETRIC_ACCESS_TOKEN", ""),
            verify_tls=tls == "true",
            ca_bundle=os.getenv("LAMETRIC_CA_BUNDLE", ""),
        )
