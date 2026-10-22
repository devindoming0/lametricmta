import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from urllib.parse import parse_qs, urlsplit

from .service import ArrivalService


def make_server(service: ArrivalService, address=None):
    class Handler(BaseHTTPRequestHandler):
        def send_json(self, code, body):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            parsed = urlsplit(self.path)
            path = parsed.path
            if path == "/healthz":
                self.send_json(200, {"status": "ok"})
                return
            if path not in ("/lametric", "/api/arrivals", "/readyz"):
                self.send_json(404, {"error": "not_found"})
                return
            token = service.settings.poll_token
            if token:
                supplied = self.headers.get("Authorization", "").removeprefix("Bearer ")
                supplied = supplied or parse_qs(parsed.query).get("token", [""])[0]
                if not hmac.compare_digest(supplied.encode(), token.encode()):
                    self.send_json(401, {"error": "unauthorized"})
                    return
            view = service.view()
            if path == "/lametric":
                # A valid frame replaces stale values on the device even during outages.
                self.send_json(200, {"frames": view["frames"]})
            elif path == "/readyz":
                self.send_json(200 if view["ready"] else 503,
                               {"ready": view["ready"], "feeds": view["feeds"], "push": view["push"]})
            else:
                self.send_json(200, view)

        def log_message(self, *_args):
            # Never log a request URL: a poll URL may contain a token.
            pass

    return ThreadingHTTPServer(address or (service.settings.host, service.settings.port), Handler)
