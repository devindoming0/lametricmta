import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import MagicMock, patch
from google.transit import gtfs_realtime_pb2 as gtfs
from lametric_mta.config import Settings
from lametric_mta.service import ArrivalService, Publisher
from lametric_mta.transit import parse_feed
from lametric_mta.web import make_server

NOW = 10_000


def feed(timestamp=NOW, rows=()):
    message = gtfs.FeedMessage()
    message.header.gtfs_realtime_version = "2.0"
    message.header.timestamp = timestamp
    for index, row in enumerate(rows):
        route, stop_id, arrival_time, *opts = row
        options = opts[0] if opts else {}
        entity = message.entity.add(id=str(index))
        entity.is_deleted = options.get("deleted", False)
        update = entity.trip_update
        update.trip.trip_id = options.get("trip_id", str(index))
        update.trip.route_id = route
        update.trip.start_date = options.get("date", "20261022")
        update.trip.start_time = options.get("start_time", "12:00:00")
        update.trip.schedule_relationship = options.get("trip_relationship", gtfs.TripDescriptor.SCHEDULED)
        if "prediction_timestamp" in options:
            update.timestamp = options["prediction_timestamp"]
        stop = update.stop_time_update.add(stop_id=stop_id)
        stop.schedule_relationship = options.get("stop_relationship", gtfs.TripUpdate.StopTimeUpdate.SCHEDULED)
        if arrival_time is not None:
            stop.arrival.time = arrival_time
        if "departure" in options:
            stop.departure.time = options["departure"]
    return message.SerializeToString()


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.now = NOW
        self.data = {"ace": feed(rows=[("A", "A27N", NOW + 180), ("E", "A27S", NOW + 59)]),
                     "nqrw": feed(rows=[("N", "R15N", NOW + 300), ("W", "R15S", NOW + 600)])}
        self.fail = set()
        self.service = self.make_service()
        self.service.refresh()

    def make_service(self, **kwargs):
        def fetcher(url, timeout):
            key = "ace" if url.endswith("ace") else "nqrw"
            if key in self.fail:
                raise TimeoutError("secret URL must never appear in response")
            return self.data[key]
        return ArrivalService(Settings(**kwargs), fetcher=fetcher, clock=lambda: self.now)

    def test_exact_stations_routes_and_directions(self):
        self.data["ace"] = feed(rows=[("A", "A27N", NOW + 30), ("C", "A28N", NOW + 40), ("B", "A27N", NOW + 50)])
        self.data["nqrw"] = feed(rows=[("Q", "R15N", NOW + 30), ("R", "R15S", NOW + 120)])
        self.service.refresh()
        groups = self.service.view()["groups"]
        self.assertEqual([a["route"] for a in groups[0]["arrivals"]], ["A"])
        self.assertEqual(groups[2]["arrivals"], [])
        self.assertEqual(groups[3]["arrivals"][0]["route"], "R")

    def test_canceled_deleted_skipped_and_no_data_excluded(self):
        bad = [{"trip_relationship": gtfs.TripDescriptor.CANCELED},
               {"trip_relationship": gtfs.TripDescriptor.DELETED}, {"deleted": True},
               {"stop_relationship": gtfs.TripUpdate.StopTimeUpdate.SKIPPED},
               {"stop_relationship": gtfs.TripUpdate.StopTimeUpdate.NO_DATA}]
        self.data["ace"] = feed(rows=[("A", "A27N", NOW + 60, o) for o in bad])
        self.service.refresh()
        self.assertEqual(self.service.view()["groups"][0]["arrivals"], [])

    def test_departure_fallback_and_missing_time(self):
        snapshot = parse_feed(feed(rows=[("C", "A27N", None, {"departure": NOW + 60}), ("E", "A27N", None)]), "ace", NOW)
        self.assertEqual(len(snapshot.arrivals), 1)
        self.assertEqual(snapshot.arrivals[0].timestamp, NOW + 60)

    def test_past_arrival_not_replaced_with_later_departure(self):
        self.data["ace"] = feed(rows=[("A", "A27N", NOW - 1, {"departure": NOW + 60})])
        self.service.refresh()
        self.assertEqual(self.service.view()["groups"][0]["arrivals"], [])

    def test_dedup_uses_trip_instance_not_only_arrival_minute(self):
        options = {"trip_id": "same"}
        self.data["ace"] = feed(rows=[("A", "A27N", NOW + 60, options), ("A", "A27N", NOW + 60, options),
                                      ("A", "A27N", NOW + 60, {"trip_id": "other"})])
        self.service.refresh()
        self.assertEqual(len(self.service.view()["groups"][0]["arrivals"]), 2)

    def test_trip_date_and_start_time_keep_distinct_instances(self):
        rows = [("A", "A27N", NOW + 60, {"trip_id": "same", "date": "20261022"}),
                ("A", "A27N", NOW + 60, {"trip_id": "same", "date": "20261023"}),
                ("A", "A27N", NOW + 60, {"trip_id": "same", "start_time": "13:00:00"})]
        self.assertEqual(len(parse_feed(feed(rows=rows), "ace", NOW).arrivals), 3)

    def test_refresh_replaces_removed_train(self):
        self.data["ace"] = feed(rows=[])
        self.service.refresh()
        self.assertEqual(self.service.view()["groups"][0]["arrivals"], [])

    def test_expiration_and_countdown_recomputed_without_fetch(self):
        self.assertEqual(self.service.view()["frames"][1]["text"], "42D E<1")
        self.now += 60
        view = self.service.view()
        self.assertEqual(view["frames"][0]["text"], "42U A2")
        self.assertEqual(view["frames"][1]["text"], "42D NO ETA")

    def test_horizon_and_stale_trip_prediction(self):
        self.data["ace"] = feed(rows=[("A", "A27N", NOW + 3601),
                                      ("C", "A27N", NOW + 60, {"prediction_timestamp": NOW - 91}),
                                      ("E", "A27N", NOW + 60, {"prediction_timestamp": NOW + 31})])
        self.service.refresh()
        self.assertEqual(self.service.view()["groups"][0]["arrivals"], [])

    def test_one_feed_failure_retains_only_fresh_labeled_cache(self):
        self.fail.add("ace")
        self.service.refresh()
        view = self.service.view()
        self.assertEqual(view["feeds"]["ace"]["status"], "cached")
        self.assertEqual(view["feeds"]["nqrw"]["status"], "live")
        self.assertTrue(view["frames"][0]["text"].startswith("~42U"))
        self.assertFalse(view["ready"])
        self.assertNotIn("secret", json.dumps(view))
        self.now += 91
        self.assertEqual(self.service.view()["frames"][0]["text"], "42U STALE")
        self.assertEqual(self.service.view()["groups"][0]["arrivals"], [])

    def test_frozen_old_feed_is_stale_even_after_successful_fetch(self):
        self.now += 91
        self.service.refresh()
        self.assertEqual(self.service.view()["feeds"]["ace"]["status"], "stale")

    def test_regressed_feed_keeps_previous_snapshot(self):
        self.data["ace"] = feed(timestamp=NOW - 1)
        self.service.refresh()
        self.assertEqual(self.service.view()["feeds"]["ace"]["error"], "regressed_feed_timestamp")
        self.assertEqual(self.service.view()["frames"][0]["text"], "~42U A3")

    def test_bad_protobuf_does_not_destroy_healthy_feed(self):
        self.data["ace"] = b"broken"
        self.service.refresh()
        self.assertEqual(self.service.view()["feeds"]["ace"]["status"], "cached")
        self.assertEqual(self.service.view()["feeds"]["nqrw"]["status"], "live")

    def test_differential_missing_and_future_timestamp_rejected(self):
        message = gtfs.FeedMessage.FromString(feed())
        message.header.incrementality = gtfs.FeedHeader.DIFFERENTIAL
        with self.assertRaises(ValueError):
            parse_feed(message.SerializeToString(), "ace", NOW)
        message.header.incrementality = gtfs.FeedHeader.FULL_DATASET
        message.header.ClearField("timestamp")
        with self.assertRaises(ValueError):
            parse_feed(message.SerializeToString(), "ace", NOW)
        with self.assertRaises(ValueError):
            parse_feed(feed(timestamp=NOW + 31), "ace", NOW)

    def test_direction_selection_and_route_mode(self):
        service = self.make_service(directions=("S",), display_mode="routes")
        service.refresh()
        frames = service.view()["frames"]
        self.assertEqual(len(frames), 6)
        self.assertEqual(frames[0]["text"], "42D A NO ETA")
        self.assertEqual(frames[2]["text"], "42D E <1")

    def test_grouped_keeps_earliest_trains_sorted(self):
        self.data["ace"] = feed(rows=[("E", "A27N", NOW + 181), ("A", "A27N", NOW + 61), ("C", "A27N", NOW + 60)])
        self.service.refresh()
        self.assertEqual(self.service.view()["frames"][0]["text"], "42U C1 A2")

    def test_unavailable_at_startup(self):
        self.assertEqual(self.make_service().view()["frames"][0]["text"], "42U NO DATA")

    def test_push_changes_heartbeat_and_failure_retry(self):
        sent, failures, elapsed = [], [True], [0]
        def sender(payload):
            if failures[0]:
                raise TimeoutError()
            sent.append(payload)
        publisher = Publisher(self.service, sender=sender, monotonic=lambda: elapsed[0])
        publisher.tick()
        self.assertEqual(self.service.view()["push"]["error"], "TimeoutError")
        failures[0] = False
        publisher.tick()
        publisher.tick()
        self.assertEqual(len(sent), 1)
        self.assertIsNone(self.service.view()["push"]["error"])
        elapsed[0] = 61
        publisher.tick()
        self.assertEqual(len(sent), 2)
        self.now += 91
        publisher.tick()
        self.assertEqual(sent[-1]["frames"][0]["text"], "42U STALE")

    def test_push_request_contract_and_readiness(self):
        service = self.make_service(push_url="https://192.168.1.50:4343/api/v1/dev/widget/update/test/1", push_token="test-app-token")
        service.refresh()
        self.assertFalse(service.view()["ready"])
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.status = 200
        with patch("lametric_mta.service.build_opener", return_value=opener):
            Publisher(service).tick()
        request = opener.open.call_args.args[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.get_header("X-access-token"), "test-app-token")
        frames = json.loads(request.data)["frames"]
        self.assertEqual([f["index"] for f in frames], [0, 1, 2, 3])
        self.assertTrue(service.view()["ready"])
        service.record_push("TimeoutError")
        self.assertFalse(service.view()["ready"])

    def test_http_contract_auth_readiness_and_no_request_fanout(self):
        service = self.make_service(poll_token="test-token")
        service.refresh()
        server = make_server(service, ("127.0.0.1", 0))
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            self.assertEqual(urlopen(base + "/healthz").status, 200)
            with self.assertRaises(HTTPError) as error:
                urlopen(base + "/lametric")
            self.assertEqual(error.exception.code, 401)
            with urlopen(base + "/lametric?token=test-token") as response:
                self.assertEqual(list(json.load(response)), ["frames"])
                self.assertIn("no-store", response.headers["Cache-Control"])
            with urlopen(Request(base + "/readyz", headers={"Authorization": "Bearer test-token"})) as response:
                self.assertTrue(json.load(response)["ready"])
            self.fail.add("ace")
            with urlopen(base + "/api/arrivals?token=test-token") as response:
                self.assertEqual(json.load(response)["feeds"]["ace"]["status"], "live")
            service.refresh()
            with self.assertRaises(HTTPError) as error:
                urlopen(base + "/readyz?token=test-token")
            self.assertEqual(error.exception.code, 503)
            with self.assertRaises(HTTPError) as error:
                urlopen(base + "/missing")
            self.assertEqual(error.exception.code, 404)
        finally:
            server.shutdown()
            server.server_close()
            worker.join()


class SettingsTests(unittest.TestCase):
    def test_reject_invalid_settings(self):
        for overrides in ({"poll_seconds": 0}, {"poll_seconds": float("nan")}, {"directions": ("E",)},
                          {"directions": ("N", "N")}, {"arrivals_per_frame": 5}, {"display_mode": "bad"},
                          {"push_url": "https://example.test"}, {"push_url": "http://clock", "push_token": "token"},
                          {"push_url": "https://clock?token=secret", "push_token": "token"}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                Settings(**overrides)


if __name__ == "__main__":
    unittest.main()
