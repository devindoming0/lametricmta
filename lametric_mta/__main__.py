import argparse
import json
import logging
import signal
import threading

from .config import Settings
from .service import ArrivalService, Publisher
from .web import make_server


def main():
    parser = argparse.ArgumentParser(description="MTA arrivals for LaMetric TIME")
    parser.add_argument("--once", action="store_true", help="Fetch live data and print frames; never push")
    parser.add_argument("--diagnose", action="store_true", help="Fetch and print feed health plus arrivals; never push")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        settings = Settings.from_env()
    except ValueError as exc:
        parser.error(str(exc))
    service = ArrivalService(settings)
    if args.once or args.diagnose:
        service.refresh()
        view = service.view()
        print(json.dumps(view if args.diagnose else {"frames": view["frames"]}, indent=2))
        # Diagnostics do not require a reachable clock because they never send to it.
        return 0 if all(f["status"] == "live" for f in view["feeds"].values()) else 1
    server = make_server(service)
    stop = threading.Event()
    workers = [threading.Thread(target=service.collect_forever, args=(stop,), daemon=True)]
    if settings.push_url:
        if not settings.verify_tls:
            logging.warning("LaMetric TLS verification disabled by explicit configuration")
        workers.append(threading.Thread(target=Publisher(service).run, args=(stop,), daemon=True))
    for worker in workers:
        worker.start()
    logging.info("service_started host=%s port=%s push=%s", settings.host, settings.port, bool(settings.push_url))

    def terminate(_signal, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, terminate)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
        for worker in workers:
            worker.join(timeout=settings.timeout_seconds + 1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
