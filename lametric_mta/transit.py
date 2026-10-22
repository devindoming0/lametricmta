from dataclasses import dataclass
from google.transit import gtfs_realtime_pb2 as gtfs

from .config import STATIONS


@dataclass(frozen=True)
class Arrival:
    route: str
    stop_id: str
    trip_id: str
    service_date: str
    start_time: str
    timestamp: int
    prediction_timestamp: int | None = None


@dataclass(frozen=True)
class Snapshot:
    timestamp: int
    received_at: float
    arrivals: tuple[Arrival, ...]


def parse_feed(data: bytes, feed_key: str, now: float) -> Snapshot:
    """Decode one complete snapshot. Unknown NYCT extensions are safely ignored."""
    feed = gtfs.FeedMessage()
    feed.ParseFromString(data)
    if not feed.IsInitialized() or not feed.HasField("header"):
        raise ValueError("incomplete_feed")
    if feed.header.incrementality != gtfs.FeedHeader.FULL_DATASET:
        raise ValueError("unsupported_differential_feed")
    if not feed.header.HasField("timestamp") or not 0 < feed.header.timestamp <= now + 30:
        raise ValueError("invalid_feed_timestamp")
    stations = {s.stop + d: s for s in STATIONS if s.feed == feed_key for d in ("N", "S")}
    # A duplicate trip/stop is one train, even if several entities reference it.
    arrivals: dict[tuple, Arrival] = {}
    for entity in feed.entity:
        if entity.is_deleted or not entity.HasField("trip_update"):
            continue
        update = entity.trip_update
        trip = update.trip
        if not trip.trip_id or trip.schedule_relationship in (gtfs.TripDescriptor.CANCELED, gtfs.TripDescriptor.DELETED):
            continue
        for stop in update.stop_time_update:
            station = stations.get(stop.stop_id)
            if station is None or trip.route_id not in station.routes:
                continue
            if stop.schedule_relationship in (gtfs.TripUpdate.StopTimeUpdate.SKIPPED, gtfs.TripUpdate.StopTimeUpdate.NO_DATA):
                continue
            # Do not infer a prediction from delay alone or static schedules.
            timestamp = next((int(event.time) for event in (stop.arrival, stop.departure)
                              if event.HasField("time") and event.time > 0), None)
            if timestamp is None:
                continue
            prediction_time = int(update.timestamp) if update.HasField("timestamp") else None
            arrival = Arrival(trip.route_id, stop.stop_id, trip.trip_id,
                              trip.start_date, trip.start_time, timestamp, prediction_time)
            key = (arrival.route, arrival.stop_id, arrival.trip_id, arrival.service_date, arrival.start_time)
            previous = arrivals.get(key)
            if previous is None or (prediction_time or 0) >= (previous.prediction_timestamp or 0):
                arrivals[key] = arrival
    return Snapshot(int(feed.header.timestamp), now, tuple(sorted(arrivals.values(), key=lambda a: a.timestamp)))
