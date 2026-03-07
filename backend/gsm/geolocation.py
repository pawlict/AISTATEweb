"""BTS-based geolocation for GSM billing records.

Resolves billing records to geographic coordinates using:
1. Direct coordinates from billing data (T-Mobile BTS X/Y)
2. BTS database lookup by CID/LAC
3. Sector positioning using azimuth data
4. Location clustering for home/work detection
"""

from __future__ import annotations

import logging
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
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
    label: str = ""  # 'dom', 'praca', 'frequent', etc.
    city: str = ""
    street: str = ""
    cells: List[Dict[str, Any]] = field(default_factory=list)

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
class GeoAnalysis:
    """Complete geolocation analysis result."""

    geo_records: List[GeoRecord] = field(default_factory=list)
    clusters: List[LocationCluster] = field(default_factory=list)
    path: List[PathSegment] = field(default_factory=list)
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

# Tighter bounds for Poland (used for auto-detection preference)
_PL_LAT_MIN, _PL_LAT_MAX = 49.0, 55.5
_PL_LON_MIN, _PL_LON_MAX = 14.0, 24.5


def _is_plausible_wgs84(lat: float, lon: float) -> bool:
    """Check if (lat, lon) falls within European bounds."""
    return _LAT_MIN <= lat <= _LAT_MAX and _LON_MIN <= lon <= _LON_MAX


def _is_in_poland(lat: float, lon: float) -> bool:
    """Check if (lat, lon) falls within Poland bounds."""
    return _PL_LAT_MIN <= lat <= _PL_LAT_MAX and _PL_LON_MIN <= lon <= _PL_LON_MAX


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
        GeoAnalysis with geo_records, clusters, path, home/work.
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
        )

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

    # Path reconstruction
    analysis.path = _build_path(geo_records)

    log.info(
        "Geolocation complete: %d clusters, %d path segments, "
        "home=%s, work=%s",
        len(analysis.clusters), len(analysis.path),
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
    bts_x = extra.get("bts_x", "")
    bts_y = extra.get("bts_y", "")
    if bts_x and bts_y:
        try:
            val_x = float(str(bts_x).replace(",", "."))
            val_y = float(str(bts_y).replace(",", "."))
            if val_x == 0.0 and val_y == 0.0:
                pass  # skip zero coords
            else:
                # Auto-detect coordinate order.
                # Polish geodetic convention: X = northing (lat), Y = easting (lon).
                # Programming convention: X = east (lon), Y = north (lat).
                # We try both and pick whichever places the point in Europe.
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
        except (ValueError, TypeError):
            pass

    # 2. BTS database lookup by CID/LAC
    if bts_db and record.location_cell_id and record.location_lac:
        try:
            lac_int = int(record.location_lac)
            cid_int = int(record.location_cell_id)
            station = bts_db.lookup_best(lac_int, cid_int)
            if station:
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
        cells_in_cluster: Dict[Tuple[int, int], int] = Counter()
        first = ""
        last = ""
        city = ""
        street = ""

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
                except (ValueError, IndexError):
                    pass
            if gr.point:
                cells_in_cluster[(gr.point.lac, gr.point.cid)] += 1
                if not city and gr.point.city:
                    city = gr.point.city
                if not street and gr.point.street:
                    street = gr.point.street

        cluster = LocationCluster(
            lat=center_lat,
            lon=center_lon,
            record_count=len(cluster_recs),
            unique_days=len(dates),
            first_seen=first,
            last_seen=last,
            hours_active=sorted(set(hours)),
            city=city,
            street=street,
            cells=[
                {"lac": lac, "cid": cid, "count": cnt}
                for (lac, cid), cnt in cells_in_cluster.most_common(10)
            ],
        )
        clusters.append(cluster)

    # Sort by record count
    clusters.sort(key=lambda c: -c.record_count)
    return clusters[:20]


def _detect_home_work(analysis: GeoAnalysis) -> None:
    """Detect home and work locations from clusters.

    Home: cluster with most activity during 22:00-07:00 hours.
    Work: cluster with most activity during 09:00-17:00 hours on weekdays.
    """
    if not analysis.clusters:
        return

    night_hours = {22, 23, 0, 1, 2, 3, 4, 5, 6}
    work_hours = {9, 10, 11, 12, 13, 14, 15, 16}

    best_home = None
    best_home_score = 0
    best_work = None
    best_work_score = 0

    for cluster in analysis.clusters:
        night_count = sum(1 for h in cluster.hours_active if h in night_hours)
        work_count = sum(1 for h in cluster.hours_active if h in work_hours)

        # Home score: night hours * record count * unique days
        home_score = night_count * cluster.record_count * cluster.unique_days
        if home_score > best_home_score:
            best_home_score = home_score
            best_home = cluster

        # Work score: work hours * record count * unique days
        work_score = work_count * cluster.record_count * cluster.unique_days
        if work_score > best_work_score:
            best_work_score = work_score
            best_work = cluster

    if best_home:
        best_home.label = "dom"
        analysis.home_cluster = best_home

    if best_work and best_work != best_home:
        best_work.label = "praca"
        analysis.work_cluster = best_work


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
        from datetime import datetime
        fmt = "%Y-%m-%d %H:%M:%S"
        t1 = datetime.strptime(dt1, fmt)
        t2 = datetime.strptime(dt2, fmt)
        return max(0, int((t2 - t1).total_seconds()))
    except (ValueError, TypeError):
        return 0
