"""BTS-based geolocation for GSM billing records.

Resolves billing records to geographic coordinates using:
1. Direct coordinates from billing data (T-Mobile BTS X/Y)
2. BTS database lookup by CID/LAC
3. Sector positioning using azimuth data
4. Location clustering for home/work detection
5. Trip detection between clusters (inter-city travel)
6. Border crossing / foreign travel detection (roaming + gap analysis)
"""

from __future__ import annotations

import logging
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime as _dt
from typing import Any, Dict, List, Optional, Set, Tuple

from .parsers.base import BillingRecord

log = logging.getLogger(__name__)


@dataclass
class GeoPoint:
    """Geographic point with metadata."""

    lat: float = 0.0
    lon: float = 0.0
    accuracy_m: int = 1000  # estimated accuracy in meters
    azimuth: Optional[float] = None
    lac: int = 0
    cid: int = 0
    city: str = ""
    street: str = ""
    source: str = ""  # 'billing', 'bts_db', 'estimated'

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def is_valid(self) -> bool:
        return self.lat != 0.0 or self.lon != 0.0


@dataclass
class GeoRecord:
    """Billing record with resolved geographic location."""

    datetime: str = ""
    date: str = ""
    time: str = ""
    record_type: str = ""
    callee: str = ""
    duration_seconds: int = 0
    point: Optional[GeoPoint] = None
    raw_row: int = 0
    roaming: bool = False
    roaming_country: str = ""
    weekday: int = -1  # 0=Mon..6=Sun, derived from date

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "datetime": self.datetime,
            "date": self.date,
            "time": self.time,
            "record_type": self.record_type,
            "callee": self.callee,
            "duration_seconds": self.duration_seconds,
            "raw_row": self.raw_row,
        }
        if self.point:
            d["point"] = self.point.to_dict()
        return d


@dataclass
class LocationCluster:
    """Cluster of geo points representing a frequently visited location."""

    lat: float = 0.0
    lon: float = 0.0
    radius_m: int = 500
    record_count: int = 0
    unique_days: int = 0
    first_seen: str = ""
    last_seen: str = ""
    hours_active: List[int] = field(default_factory=list)
    hour_counts: Dict[int, int] = field(default_factory=dict)
    weekday_counts: Dict[int, int] = field(default_factory=dict)
    label: str = ""  # 'dom', 'praca', 'frequent', etc.
    city: str = ""
    street: str = ""
    cells: List[Dict[str, Any]] = field(default_factory=list)
    cluster_idx: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PathSegment:
    """Movement path segment between two geo points."""

    from_point: GeoPoint = field(default_factory=GeoPoint)
    to_point: GeoPoint = field(default_factory=GeoPoint)
    from_datetime: str = ""
    to_datetime: str = ""
    distance_m: float = 0.0
    duration_seconds: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "from_point": self.from_point.to_dict(),
            "to_point": self.to_point.to_dict(),
            "from_datetime": self.from_datetime,
            "to_datetime": self.to_datetime,
            "distance_m": round(self.distance_m),
            "duration_seconds": self.duration_seconds,
        }


@dataclass
class Trip:
    """Detected inter-city movement between clusters."""

    from_cluster_idx: int = 0
    to_cluster_idx: int = 0
    from_city: str = ""
    to_city: str = ""
    depart_datetime: str = ""
    arrive_datetime: str = ""
    distance_km: float = 0.0
    duration_minutes: float = 0.0
    speed_kmh: float = 0.0          # actual observed speed
    travel_mode: str = ""           # 'car', 'plane', 'bts_hop', 'unknown'
    est_car_minutes: float = 0.0    # estimated car drive time
    est_flight_minutes: float = 0.0 # estimated total flight time (incl. airport)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BorderCrossing:
    """Detected border crossing / foreign travel event."""

    last_domestic_datetime: str = ""
    first_return_datetime: str = ""
    last_domestic_city: str = ""
    first_return_city: str = ""
    absence_hours: float = 0.0
    roaming_countries: List[str] = field(default_factory=list)
    roaming_records: int = 0
    roaming_confirmed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GeoAnalysis:
    """Complete geolocation analysis result."""

    geo_records: List[GeoRecord] = field(default_factory=list)
    clusters: List[LocationCluster] = field(default_factory=list)
    path: List[PathSegment] = field(default_factory=list)
    trips: List[Trip] = field(default_factory=list)
    border_crossings: List[BorderCrossing] = field(default_factory=list)
    home_cluster: Optional[LocationCluster] = None
    work_cluster: Optional[LocationCluster] = None
    total_records: int = 0
    geolocated_records: int = 0
    unique_cells: int = 0
    center_lat: float = 0.0
    center_lon: float = 0.0
    bounds: Dict[str, float] = field(default_factory=dict)
    debug: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        # Only include geolocated records (those with valid point)
        # to avoid sending 20k+ empty records in the JSON response
        geolocated = [r.to_dict() for r in self.geo_records
                      if r.point and r.point.is_valid]
        return {
            "geo_records": geolocated,
            "clusters": [c.to_dict() for c in self.clusters],
            "path": [p.to_dict() for p in self.path],
            "trips": [t.to_dict() for t in self.trips],
            "border_crossings": [bc.to_dict() for bc in self.border_crossings],
            "home_cluster": self.home_cluster.to_dict() if self.home_cluster else None,
            "work_cluster": self.work_cluster.to_dict() if self.work_cluster else None,
            "total_records": self.total_records,
            "geolocated_records": self.geolocated_records,
            "unique_cells": self.unique_cells,
            "center_lat": self.center_lat,
            "center_lon": self.center_lon,
            "bounds": self.bounds,
            "debug": self.debug,
        }


# ---------------------------------------------------------------------------
# Coordinate helpers
# ---------------------------------------------------------------------------

# Valid WGS84 range for European BTS (generous bounding box)
_LAT_MIN, _LAT_MAX = 35.0, 72.0   # Europe: from southern Greece to northern Norway
_LON_MIN, _LON_MAX = -12.0, 45.0  # Europe: from Atlantic coast to Ural


def _is_plausible_wgs84(lat: float, lon: float) -> bool:
    """Check if (lat, lon) falls within European bounds."""
    return _LAT_MIN <= lat <= _LAT_MAX and _LON_MIN <= lon <= _LON_MAX


def _ddmmss_to_decimal(val: float) -> Optional[float]:
    """Convert DDMMSS integer to decimal degrees.

    Polish telecom BTS coordinates use DDMMSS format:
        190813 → 19°08'13" → 19.13694°
        513507 → 51°35'07" → 51.58528°
    """
    ival = int(round(abs(val)))
    sign = -1 if val < 0 else 1

    ss = ival % 100
    mm = (ival // 100) % 100
    dd = ival // 10000

    if mm > 59 or ss > 59 or dd > 180:
        return None

    return sign * (dd + mm / 60.0 + ss / 3600.0)


def _parse_bts_value(raw) -> Optional[float]:
    """Parse a raw BTS coordinate value to decimal degrees.

    Supports:
    - WGS84 decimal degrees (e.g., 19.0813 or 51.3507)
    - DDMMSS integer format (e.g., 190813 → 19°08'13" → 19.1369°)

    Rejects sentinel/null values used in billing (-1, 0, 999, etc.).
    """
    try:
        val = float(str(raw).replace(",", "."))
    except (ValueError, TypeError):
        return None

    # Reject common sentinel/null placeholder values in billing data
    # T-Mobile uses -1 for "unknown", other operators may use 0, 999, etc.
    if val in (0.0, -1.0, 1.0, 999.0, -999.0, 9999.0, -9999.0):
        return None

    # Already valid decimal degrees (fits in WGS84 range)
    if -180.0 <= val <= 180.0:
        return val

    # Try DDMMSS integer format (common in Polish telecom billing)
    return _ddmmss_to_decimal(val)


def _detect_coord_order(
    val_x: float, val_y: float,
) -> Tuple[Optional[float], Optional[float]]:
    """Auto-detect whether (val_x, val_y) is (lat, lon) or (lon, lat).

    Polish geodetic convention: X = northing (latitude), Y = easting (longitude).
    Programming/math convention: X = east (longitude), Y = north (latitude).

    Returns (lat, lon) or (None, None) if neither ordering is valid.
    """
    # Try Polish geodetic convention first: X = lat, Y = lon
    if _is_plausible_wgs84(val_x, val_y):
        return val_x, val_y

    # Try programming convention: X = lon, Y = lat
    if _is_plausible_wgs84(val_y, val_x):
        return val_y, val_x

    # Neither ordering works — coordinates outside Europe
    log.debug("Coordinate out of range: val_x=%s, val_y=%s", val_x, val_y)
    return None, None


# ---------------------------------------------------------------------------
# Core geolocation
# ---------------------------------------------------------------------------

def geolocate_records(
    records: List[BillingRecord],
    bts_db=None,
) -> GeoAnalysis:
    """Resolve billing records to geographic coordinates and analyze.

    Args:
        records: Parsed billing records.
        bts_db: Optional BTSDatabase instance for CID/LAC lookup.

    Returns:
        GeoAnalysis with geo_records, clusters, path, trips,
        border_crossings, home/work.
    """
    analysis = GeoAnalysis(total_records=len(records))

    if not records:
        log.info("Geolocation: no records to process")
        return analysis

    log.info("Geolocation: processing %d records, bts_db=%s",
             len(records), "available" if bts_db else "NONE")

    # Debug counters
    has_direct_coords = 0
    has_lac_cid = 0
    no_location_data = 0
    resolved_billing = 0
    resolved_bts_db = 0
    lookup_miss = 0
    coord_rejected = 0  # coords outside valid range
    sample_lac_cid: List[str] = []
    sample_raw_bts: List[str] = []  # raw BTS X/Y values for debugging

    geo_records: List[GeoRecord] = []
    seen_cells: Set[Tuple[int, int]] = set()

    for r in records:
        gr = GeoRecord(
            datetime=r.datetime,
            date=r.date,
            time=r.time,
            record_type=r.record_type,
            callee=r.callee or r.caller,
            duration_seconds=r.duration_seconds,
            raw_row=r.raw_row,
            roaming=r.roaming,
            roaming_country=r.roaming_country or "",
        )

        # Derive weekday from date
        if r.date:
            try:
                gr.weekday = _dt.strptime(r.date, "%Y-%m-%d").weekday()
            except (ValueError, TypeError):
                pass

        # Track what data each record has
        extra = r.extra or {}
        has_bts_xy = bool(extra.get("bts_x") and extra.get("bts_y"))
        has_lac = bool(r.location_lac)
        has_cid = bool(r.location_cell_id)

        if has_bts_xy:
            has_direct_coords += 1
            if len(sample_raw_bts) < 3:
                sample_raw_bts.append(
                    f"BTS_X={extra.get('bts_x')},BTS_Y={extra.get('bts_y')}"
                )
        if has_lac and has_cid:
            has_lac_cid += 1
            if len(sample_lac_cid) < 5:
                sample_lac_cid.append(f"LAC={r.location_lac},CID={r.location_cell_id}")
        if not has_bts_xy and not (has_lac and has_cid):
            no_location_data += 1

        point = _resolve_point(r, bts_db)
        if point and point.is_valid:
            gr.point = point
            analysis.geolocated_records += 1
            if point.source == "billing":
                resolved_billing += 1
            elif point.source == "bts_db":
                resolved_bts_db += 1
            if point.lac and point.cid:
                seen_cells.add((point.lac, point.cid))
        elif has_bts_xy:
            coord_rejected += 1
        elif has_lac and has_cid:
            lookup_miss += 1

        geo_records.append(gr)

    analysis.geo_records = geo_records
    analysis.unique_cells = len(seen_cells)

    # Log diagnostic summary
    if sample_raw_bts:
        log.info("Raw BTS X/Y samples: %s", "; ".join(sample_raw_bts))
    log.info(
        "Geolocation results: %d/%d resolved "
        "(direct_coords=%d, bts_db=%d, no_data=%d, lookup_miss=%d, coord_rejected=%d)",
        analysis.geolocated_records, len(records),
        has_direct_coords, resolved_bts_db,
        no_location_data, lookup_miss, coord_rejected,
    )
    if has_lac_cid and resolved_bts_db == 0 and has_direct_coords == 0:
        log.warning(
            "Geolocation: %d records had LAC/CID but 0 matched BTS database! "
            "Sample: %s  — check if BTS database (OpenCelliD) is loaded.",
            has_lac_cid, "; ".join(sample_lac_cid),
        )

    # Collect sample coordinates for debug
    sample_coords: List[str] = []
    for gr in geo_records:
        if gr.point and gr.point.is_valid and len(sample_coords) < 3:
            sample_coords.append(
                f"lat={gr.point.lat:.6f},lon={gr.point.lon:.6f},src={gr.point.source}"
            )

    if sample_coords:
        log.info("Geolocation sample coords: %s", "; ".join(sample_coords))

    # Store debug info for frontend
    analysis.debug = {
        "has_direct_coords": has_direct_coords,
        "has_lac_cid": has_lac_cid,
        "no_location_data": no_location_data,
        "resolved_billing": resolved_billing,
        "resolved_bts_db": resolved_bts_db,
        "lookup_miss": lookup_miss,
        "coord_rejected": coord_rejected,
        "sample_lac_cid": sample_lac_cid,
        "sample_raw_bts": sample_raw_bts,
        "sample_coords": sample_coords,
    }

    # Compute center and bounds
    valid_points = [gr.point for gr in geo_records if gr.point and gr.point.is_valid]
    if valid_points:
        lats = [p.lat for p in valid_points]
        lons = [p.lon for p in valid_points]
        analysis.center_lat = sum(lats) / len(lats)
        analysis.center_lon = sum(lons) / len(lons)
        analysis.bounds = {
            "min_lat": min(lats),
            "max_lat": max(lats),
            "min_lon": min(lons),
            "max_lon": max(lons),
        }

    # Cluster analysis
    analysis.clusters = _cluster_locations(geo_records)

    # Home/work detection
    _detect_home_work(analysis)

    # Path reconstruction (fine-grained, within-cluster)
    analysis.path = _build_path(geo_records)

    # Trip detection (inter-city movements between clusters)
    analysis.trips = _detect_trips(geo_records, analysis.clusters)

    # Border crossing / foreign travel detection
    analysis.border_crossings = _detect_border_crossings(geo_records, analysis.clusters)

    log.info(
        "Geolocation complete: %d clusters, %d path segments, %d trips, "
        "%d border crossings, home=%s, work=%s",
        len(analysis.clusters), len(analysis.path),
        len(analysis.trips), len(analysis.border_crossings),
        bool(analysis.home_cluster), bool(analysis.work_cluster),
    )

    return analysis


def _resolve_point(
    record: BillingRecord,
    bts_db=None,
) -> Optional[GeoPoint]:
    """Resolve a single billing record to a geographic point."""
    extra = record.extra or {}

    # 1. Direct coordinates from billing (T-Mobile BTS X/Y)
    #    T-Mobile Poland uses DDMMSS integer format:
    #    BTS X = 190813 → 19°08'13" = 19.1369° (longitude for Łask)
    #    BTS Y = 513507 → 51°35'07" = 51.5853° (latitude for Łask)
    bts_x = extra.get("bts_x", "")
    bts_y = extra.get("bts_y", "")
    if bts_x and bts_y:
        val_x = _parse_bts_value(bts_x)
        val_y = _parse_bts_value(bts_y)

        if val_x is not None and val_y is not None:
            # Auto-detect coordinate order (handles both Polish geodetic
            # convention X=lat,Y=lon and programming convention X=lon,Y=lat)
            lat, lon = _detect_coord_order(val_x, val_y)

            if lat is not None and lon is not None:
                azimuth = None
                az_str = extra.get("azimuth", "")
                if az_str:
                    try:
                        azimuth = float(str(az_str).replace(",", "."))
                    except (ValueError, TypeError):
                        pass

                lac_int = 0
                cid_int = 0
                try:
                    lac_int = int(record.location_lac) if record.location_lac else 0
                    cid_int = int(record.location_cell_id) if record.location_cell_id else 0
                except (ValueError, TypeError):
                    pass

                return GeoPoint(
                    lat=lat,
                    lon=lon,
                    accuracy_m=200 if azimuth is not None else 500,
                    azimuth=azimuth,
                    lac=lac_int,
                    cid=cid_int,
                    city=extra.get("bts_city", ""),
                    street=extra.get("bts_street", ""),
                    source="billing",
                )

    # 2. BTS database lookup by CID/LAC
    if bts_db and record.location_cell_id and record.location_lac:
        try:
            lac_int = int(record.location_lac)
            cid_int = int(record.location_cell_id)
            # Skip sentinel LAC/CID values
            if lac_int <= 0 or cid_int <= 0:
                return None
            station = bts_db.lookup_best(lac_int, cid_int)
            if station and _is_plausible_wgs84(station.lat, station.lon):
                return GeoPoint(
                    lat=station.lat,
                    lon=station.lon,
                    accuracy_m=200 if station.azimuth is not None else 500,
                    azimuth=station.azimuth,
                    lac=lac_int,
                    cid=cid_int,
                    city=station.city,
                    street=station.street,
                    source="bts_db",
                )
        except (ValueError, TypeError):
            pass

    return None


# ---------------------------------------------------------------------------
# Clustering (DBSCAN-like, simplified)
# ---------------------------------------------------------------------------

def _cluster_locations(
    geo_records: List[GeoRecord],
    eps_m: float = 500,
    min_records: int = 3,
) -> List[LocationCluster]:
    """Cluster geolocated records by proximity.

    Uses a simplified grid-based approach (faster than full DBSCAN).
    Collects frequency-weighted hour_counts and weekday_counts for
    proper home/work scoring.
    """
    valid = [gr for gr in geo_records if gr.point and gr.point.is_valid]
    if not valid:
        return []

    # Grid-based clustering: ~500m grid cells
    grid_size = eps_m / 111000  # degrees (approx)
    cells: Dict[Tuple[int, int], List[GeoRecord]] = defaultdict(list)

    for gr in valid:
        gx = int(gr.point.lat / grid_size)
        gy = int(gr.point.lon / grid_size)
        cells[(gx, gy)].append(gr)

    # Merge adjacent grid cells
    clusters: List[LocationCluster] = []
    visited: Set[Tuple[int, int]] = set()

    for key, recs in sorted(cells.items(), key=lambda x: -len(x[1])):
        if key in visited:
            continue
        if len(recs) < min_records:
            continue

        # Collect this cell + neighbors
        cluster_recs: List[GeoRecord] = list(recs)
        visited.add(key)

        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                nkey = (key[0] + dx, key[1] + dy)
                if nkey != key and nkey in cells and nkey not in visited:
                    cluster_recs.extend(cells[nkey])
                    visited.add(nkey)

        if len(cluster_recs) < min_records:
            continue

        # Compute cluster properties
        lats = [gr.point.lat for gr in cluster_recs]
        lons = [gr.point.lon for gr in cluster_recs]
        center_lat = sum(lats) / len(lats)
        center_lon = sum(lons) / len(lons)

        dates = set()
        hours: List[int] = []
        hour_counts: Dict[int, int] = Counter()
        weekday_counts: Dict[int, int] = Counter()
        cells_in_cluster: Dict[Tuple[int, int], int] = Counter()
        first = ""
        last = ""
        # Track city frequency to pick most common (not just first)
        city_counter: Dict[str, int] = Counter()
        street_counter: Dict[str, int] = Counter()

        for gr in cluster_recs:
            if gr.date:
                dates.add(gr.date)
                if not first or gr.date < first:
                    first = gr.date
                if not last or gr.date > last:
                    last = gr.date
            if gr.time:
                try:
                    h = int(gr.time.split(":")[0])
                    hours.append(h)
                    hour_counts[h] += 1
                except (ValueError, IndexError):
                    pass
            if gr.weekday >= 0:
                weekday_counts[gr.weekday] += 1
            if gr.point:
                cells_in_cluster[(gr.point.lac, gr.point.cid)] += 1
                if gr.point.city:
                    city_counter[gr.point.city] += 1
                if gr.point.street:
                    street_counter[gr.point.street] += 1

        # Pick most common city/street
        city = city_counter.most_common(1)[0][0] if city_counter else ""
        street = street_counter.most_common(1)[0][0] if street_counter else ""

        cluster = LocationCluster(
            lat=center_lat,
            lon=center_lon,
            record_count=len(cluster_recs),
            unique_days=len(dates),
            first_seen=first,
            last_seen=last,
            hours_active=sorted(set(hours)),
            hour_counts=dict(hour_counts),
            weekday_counts=dict(weekday_counts),
            city=city,
            street=street,
            cells=[
                {"lac": lac, "cid": cid, "count": cnt}
                for (lac, cid), cnt in cells_in_cluster.most_common(10)
            ],
        )
        clusters.append(cluster)

    # Sort by record count, assign indices
    clusters.sort(key=lambda c: -c.record_count)
    clusters = clusters[:30]  # cap at 30
    for i, c in enumerate(clusters):
        c.cluster_idx = i

    return clusters


def _detect_home_work(analysis: GeoAnalysis) -> None:
    """Detect home and work locations from clusters.

    Home: cluster with highest frequency-weighted night activity (22:00-07:00)
          multiplied by unique_days.  Requires at least 3 unique days.
    Work: cluster with highest frequency-weighted work-hour activity (8:00-16:00)
          on weekdays (Mon-Fri), multiplied by unique_days and weekday ratio.
          Must not be the same as home.  Requires at least 3 unique days.
    """
    if not analysis.clusters:
        return

    night_hours = {22, 23, 0, 1, 2, 3, 4, 5, 6}
    work_hours = {8, 9, 10, 11, 12, 13, 14, 15, 16}

    best_home = None
    best_home_score = 0
    best_work = None
    best_work_score = 0

    for cluster in analysis.clusters:
        # Home: frequency-weighted night records × unique days
        night_freq = sum(cluster.hour_counts.get(h, 0) for h in night_hours)
        home_score = night_freq * max(1, cluster.unique_days)
        if home_score > best_home_score and cluster.unique_days >= 3:
            best_home_score = home_score
            best_home = cluster

        # Work: frequency-weighted work-hour records × weekday ratio × unique days
        work_freq = sum(cluster.hour_counts.get(h, 0) for h in work_hours)
        weekday_records = sum(cluster.weekday_counts.get(d, 0) for d in range(5))
        total_records = sum(cluster.weekday_counts.values()) or 1
        weekday_ratio = weekday_records / total_records
        work_score = work_freq * max(1, cluster.unique_days) * weekday_ratio
        if work_score > best_work_score and cluster.unique_days >= 3:
            best_work_score = work_score
            best_work = cluster

    if best_home:
        best_home.label = "dom"
        analysis.home_cluster = best_home

    if best_work and best_work != best_home:
        best_work.label = "praca"
        analysis.work_cluster = best_work


# ---------------------------------------------------------------------------
# Trip detection (inter-city travel)
# ---------------------------------------------------------------------------

def _detect_trips(
    geo_records: List[GeoRecord],
    clusters: List[LocationCluster],
    min_distance_km: float = 5.0,
) -> List[Trip]:
    """Detect inter-city trips as cluster-to-cluster transitions.

    Algorithm:
    1. Assign each geolocated record to its nearest cluster.
    2. Walk chronologically — when cluster changes and distance > min_distance_km,
       record a Trip.
    3. Collapse consecutive same-cluster records to avoid noise.
    4. Infer travel mode: car, plane, or BTS hop (false positive).
    5. Filter out BTS hops (unrealistic speed with very short duration).
    """
    if not clusters or len(clusters) < 2:
        return []

    valid = [gr for gr in geo_records
             if gr.point and gr.point.is_valid and gr.datetime]
    if len(valid) < 2:
        return []

    valid.sort(key=lambda gr: gr.datetime)

    def _nearest_cluster_idx(p: GeoPoint) -> int:
        best_idx = 0
        best_dist = float("inf")
        for i, c in enumerate(clusters):
            d = _haversine(p.lat, p.lon, c.lat, c.lon)
            if d < best_dist:
                best_dist = d
                best_idx = i
        return best_idx

    raw_trips: List[Trip] = []
    prev_idx = _nearest_cluster_idx(valid[0].point)
    prev_record = valid[0]

    for gr in valid[1:]:
        idx = _nearest_cluster_idx(gr.point)
        if idx != prev_idx:
            # Cluster changed — check if it's a meaningful trip
            dist = _haversine(
                clusters[prev_idx].lat, clusters[prev_idx].lon,
                clusters[idx].lat, clusters[idx].lon,
            )
            if dist >= min_distance_km * 1000:
                dur_sec = _time_diff_seconds(prev_record.datetime, gr.datetime)
                dist_km = dist / 1000
                dur_min = dur_sec / 60 if dur_sec > 0 else 0.01
                speed = (dist_km / (dur_min / 60)) if dur_min > 0 else 0

                # Estimate realistic travel times
                est_car = _estimate_car_time(dist_km)
                est_flight = _estimate_flight_time(dist_km)

                # Infer travel mode
                mode = _infer_travel_mode(dist_km, dur_min, speed)

                raw_trips.append(Trip(
                    from_cluster_idx=prev_idx,
                    to_cluster_idx=idx,
                    from_city=clusters[prev_idx].city or f"Lokalizacja #{prev_idx + 1}",
                    to_city=clusters[idx].city or f"Lokalizacja #{idx + 1}",
                    depart_datetime=prev_record.datetime,
                    arrive_datetime=gr.datetime,
                    distance_km=round(dist_km, 1),
                    duration_minutes=round(dur_min, 1),
                    speed_kmh=round(speed, 0),
                    travel_mode=mode,
                    est_car_minutes=round(est_car, 0),
                    est_flight_minutes=round(est_flight, 0),
                ))
            prev_idx = idx
        prev_record = gr

    # Filter out BTS hops (false positives)
    trips = [t for t in raw_trips if t.travel_mode != "bts_hop"]
    filtered = len(raw_trips) - len(trips)

    log.info(
        "Trip detection: %d trips (%d BTS hops filtered) between %d clusters "
        "(min distance %.1f km)",
        len(trips), filtered, len(clusters), min_distance_km,
    )
    return trips


def _infer_travel_mode(
    distance_km: float,
    duration_min: float,
    speed_kmh: float,
) -> str:
    """Infer travel mode based on distance, duration and speed.

    Returns: 'bts_hop', 'car', 'plane', or 'unknown'.

    BTS hop detection:
    - Very short duration (< 10 min) with unrealistic speed (> 200 km/h)
      for the distance — this is BTS tower switching, not real travel.
    - Duration < 3 min for any distance > 5 km — physically impossible
      by any transport mode in that timeframe.

    Car detection:
    - Speed between 20-160 km/h (average, including stops/traffic).
    - Or duration roughly matches estimated car time (within 3x factor).

    Plane detection:
    - Distance > 200 km AND speed > 200 km/h.
    - Or distance > 400 km and duration is much shorter than car time.
    """
    # BTS hop: unrealistically fast for short durations
    if duration_min < 3 and distance_km > 5:
        return "bts_hop"
    if duration_min < 10 and speed_kmh > 300:
        return "bts_hop"
    if duration_min < 15 and speed_kmh > 500:
        return "bts_hop"

    # Plane: long distance with high speed
    est_car = _estimate_car_time(distance_km)
    if distance_km > 200 and speed_kmh > 200:
        return "plane"
    if distance_km > 400 and duration_min < est_car * 0.4:
        return "plane"

    # Car: reasonable speed range or duration matches estimate
    if 10 <= speed_kmh <= 200:
        return "car"
    if duration_min > 0 and est_car > 0:
        ratio = duration_min / est_car
        if 0.3 <= ratio <= 4.0:
            return "car"

    return "unknown"


def _estimate_car_time(distance_km: float) -> float:
    """Estimate car travel time in minutes.

    Uses tiered average speeds:
    - Short trips (<30 km): ~40 km/h (city/suburban driving)
    - Medium trips (30-150 km): ~70 km/h (mix of city and highway)
    - Long trips (>150 km): ~90 km/h (mostly highway)
    """
    if distance_km <= 0:
        return 0
    if distance_km < 30:
        return (distance_km / 40) * 60
    if distance_km < 150:
        return (distance_km / 70) * 60
    return (distance_km / 90) * 60


def _estimate_flight_time(distance_km: float) -> float:
    """Estimate total flight travel time in minutes.

    Includes:
    - Airport overhead: ~90 min (check-in + security + boarding + taxi + deplane)
    - Flight time: distance / 700 km/h (average jet cruise)
    - Minimum 120 min total for any flight.

    For distances < 200 km, flights are impractical — returns 0.
    """
    if distance_km < 200:
        return 0
    flight_min = (distance_km / 700) * 60
    total = 90 + flight_min  # airport overhead + flight
    return max(120, total)


# ---------------------------------------------------------------------------
# Border crossing / foreign travel detection
# ---------------------------------------------------------------------------

def _detect_border_crossings(
    geo_records: List[GeoRecord],
    clusters: List[LocationCluster],
) -> List[BorderCrossing]:
    """Detect border crossings using roaming data and activity gaps.

    Strategy A (roaming-based): Track domestic → roaming → domestic transitions.
    Strategy B (gap-based):     Detect long gaps (> 48h) with no records.
    Results from both strategies are merged and deduplicated.
    """
    if not geo_records:
        return []

    sorted_records = sorted(
        [gr for gr in geo_records if gr.datetime],
        key=lambda gr: gr.datetime,
    )
    if not sorted_records:
        return []

    crossings: List[BorderCrossing] = []

    # ── Strategy A: Roaming-based ──
    roaming_any = any(gr.roaming for gr in sorted_records)
    if roaming_any:
        in_roaming = False
        last_domestic: Optional[GeoRecord] = None
        roaming_countries: List[str] = []
        roaming_count = 0

        for gr in sorted_records:
            if gr.roaming:
                if not in_roaming:
                    # Transition: domestic → roaming
                    in_roaming = True
                    roaming_countries = []
                    roaming_count = 0
                if gr.roaming_country and gr.roaming_country not in roaming_countries:
                    roaming_countries.append(gr.roaming_country)
                roaming_count += 1
            else:
                if in_roaming:
                    # Transition: roaming → domestic
                    in_roaming = False
                    absence = _time_diff_seconds(
                        last_domestic.datetime if last_domestic else "",
                        gr.datetime,
                    )
                    crossings.append(BorderCrossing(
                        last_domestic_datetime=last_domestic.datetime if last_domestic else "",
                        first_return_datetime=gr.datetime,
                        last_domestic_city=_city_for_record(last_domestic, clusters) if last_domestic else "",
                        first_return_city=_city_for_record(gr, clusters),
                        absence_hours=round(absence / 3600, 1),
                        roaming_countries=list(roaming_countries),
                        roaming_records=roaming_count,
                        roaming_confirmed=True,
                    ))
                last_domestic = gr

        # If still in roaming at end of data
        if in_roaming and last_domestic:
            last_roaming = sorted_records[-1]
            absence = _time_diff_seconds(
                last_domestic.datetime, last_roaming.datetime,
            )
            crossings.append(BorderCrossing(
                last_domestic_datetime=last_domestic.datetime,
                first_return_datetime="",  # not yet returned
                last_domestic_city=_city_for_record(last_domestic, clusters),
                first_return_city="",
                absence_hours=round(absence / 3600, 1),
                roaming_countries=list(roaming_countries),
                roaming_records=roaming_count,
                roaming_confirmed=True,
            ))

    # ── Strategy B: Gap-based (fallback when no roaming data) ──
    if not roaming_any and len(sorted_records) >= 2:
        gap_threshold_hours = 48
        for i in range(1, len(sorted_records)):
            prev = sorted_records[i - 1]
            curr = sorted_records[i]
            gap_sec = _time_diff_seconds(prev.datetime, curr.datetime)
            gap_hours = gap_sec / 3600

            if gap_hours >= gap_threshold_hours:
                crossings.append(BorderCrossing(
                    last_domestic_datetime=prev.datetime,
                    first_return_datetime=curr.datetime,
                    last_domestic_city=_city_for_record(prev, clusters),
                    first_return_city=_city_for_record(curr, clusters),
                    absence_hours=round(gap_hours, 1),
                    roaming_countries=[],
                    roaming_records=0,
                    roaming_confirmed=False,
                ))

    # Sort by departure time
    crossings.sort(key=lambda bc: bc.last_domestic_datetime)

    log.info("Border crossing detection: %d crossings (roaming_data=%s)",
             len(crossings), "yes" if roaming_any else "no (gap-based)")
    return crossings


def _city_for_record(
    gr: GeoRecord,
    clusters: List[LocationCluster],
) -> str:
    """Get city name for a GeoRecord — from its point or nearest cluster."""
    if gr.point and gr.point.city:
        return gr.point.city
    if gr.point and gr.point.is_valid and clusters:
        best_idx = 0
        best_dist = float("inf")
        for i, c in enumerate(clusters):
            d = _haversine(gr.point.lat, gr.point.lon, c.lat, c.lon)
            if d < best_dist:
                best_dist = d
                best_idx = i
        if best_dist < 5000 and clusters[best_idx].city:
            return clusters[best_idx].city
    return ""


# ---------------------------------------------------------------------------
# Path reconstruction
# ---------------------------------------------------------------------------

def _build_path(geo_records: List[GeoRecord]) -> List[PathSegment]:
    """Build movement path from chronologically ordered geo records."""
    valid = [gr for gr in geo_records if gr.point and gr.point.is_valid]
    if len(valid) < 2:
        return []

    # Sort by datetime
    valid.sort(key=lambda gr: gr.datetime)

    path: List[PathSegment] = []
    prev = valid[0]

    for curr in valid[1:]:
        if not prev.point or not curr.point:
            prev = curr
            continue

        dist = _haversine(prev.point.lat, prev.point.lon,
                          curr.point.lat, curr.point.lon)

        # Only add segment if there's meaningful movement (> 200m)
        if dist > 200:
            # Parse time difference
            dur = _time_diff_seconds(prev.datetime, curr.datetime)

            segment = PathSegment(
                from_point=prev.point,
                to_point=curr.point,
                from_datetime=prev.datetime,
                to_datetime=curr.datetime,
                distance_m=dist,
                duration_seconds=dur,
            )
            path.append(segment)

        prev = curr

    return path


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two points in meters (Haversine formula)."""
    R = 6371000  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (math.sin(dphi / 2) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def _time_diff_seconds(dt1: str, dt2: str) -> int:
    """Calculate time difference in seconds between two datetime strings."""
    try:
        fmt = "%Y-%m-%d %H:%M:%S"
        t1 = _dt.strptime(dt1, fmt)
        t2 = _dt.strptime(dt2, fmt)
        return max(0, int((t2 - t1).total_seconds()))
    except (ValueError, TypeError):
        return 0
