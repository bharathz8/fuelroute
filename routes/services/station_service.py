"""
Fuel Station Service.
Loads, normalizes, indexes, and filters fuel station data along a route corridor.
Uses an in-memory spatial grid index for sub-millisecond route-corridor queries.
"""
import json
import logging
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any
from django.conf import settings

logger = logging.getLogger(__name__)

EARTH_RADIUS_MILES = 3958.7613


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two points in miles."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_MILES * c


@dataclass
class FuelStation:
    """Represents an enriched fuel station."""
    opis_id: str
    name: str
    address: str
    city: str
    state: str
    rack_id: str
    price: float
    latitude: float
    longitude: float
    # Populated when mapped to a specific route
    distance_along_route: float = 0.0
    corridor_offset_miles: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'station_id': self.opis_id,
            'station_name': self.name,
            'address': self.address,
            'city': self.city,
            'state': self.state,
            'price_per_gallon': round(self.price, 3),
            'distance_from_start_miles': round(self.distance_along_route, 1),
            'corridor_offset_miles': round(self.corridor_offset_miles, 2),
            'latitude': round(self.latitude, 5),
            'longitude': round(self.longitude, 5),
        }


class StationService:
    """
    Manages fuel stations in memory with a fast spatial grid index.
    Thread-safe and initialized once at application startup.
    """

    _instance = None

    def __init__(self, data_path: Optional[Path] = None):
        self.data_path = Path(data_path or getattr(settings, 'FUEL_DATA_PATH', 'data/enriched_fuel_stations.json'))
        self.stations: List[FuelStation] = []
        self.stations_by_id: Dict[str, FuelStation] = {}
        # Spatial grid mapping (lat_bucket, lon_bucket) -> list of stations
        # Bucket size is 0.5 degrees (~35 miles latitude)
        self.grid: Dict[Tuple[int, int], List[FuelStation]] = {}
        self.city_lookup: Dict[Tuple[str, str], Tuple[float, float]] = {}
        self.is_loaded: bool = False

        self.load_data()

    @classmethod
    def get_instance(cls) -> 'StationService':
        """Singleton accessor."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def load_data(self) -> None:
        """Loads enriched stations and indexes them in the spatial grid."""
        if not self.data_path.exists():
            logger.warning("Enriched stations file %s not found. Attempting to generate...", self.data_path)
            self._try_generate_data()

        if not self.data_path.exists():
            logger.error("Failed to load or generate station data at %s", self.data_path)
            return

        try:
            with open(self.data_path, 'r', encoding='utf-8') as f:
                records = json.load(f)

            self.stations = []
            self.stations_by_id = {}
            self.grid = {}
            self.city_lookup = {}

            for r in records:
                station = FuelStation(
                    opis_id=str(r['opis_id']),
                    name=r['name'],
                    address=r.get('address', ''),
                    city=r['city'],
                    state=r['state'],
                    rack_id=str(r.get('rack_id', '')),
                    price=float(r['price']),
                    latitude=float(r['latitude']),
                    longitude=float(r['longitude']),
                )
                self.stations.append(station)
                self.stations_by_id[station.opis_id] = station

                # Populate spatial grid bucket
                bucket = (int(station.latitude * 2.0), int(station.longitude * 2.0))
                self.grid.setdefault(bucket, []).append(station)

                # Populate offline city coordinate lookup
                city_key = (station.city.strip().upper(), station.state.strip().upper())
                self.city_lookup[city_key] = (station.latitude, station.longitude)

            self.is_loaded = True
            logger.info("Loaded and indexed %d fuel stations across %d spatial cells.", len(self.stations), len(self.grid))
        except Exception as exc:
            logger.error("Failed loading enriched fuel station dataset: %s", exc, exc_info=True)

    def _try_generate_data(self) -> None:
        """Helper to generate enriched station JSON if missing."""
        try:
            from django.core.management import call_command
            call_command('prepare_fuel_data')
        except Exception as exc:
            logger.warning("Auto prepare_fuel_data failed: %s", exc)

    def lookup_city_coordinates(self, query: str) -> Optional[Tuple[float, float]]:
        """
        Attempts to resolve 'City, ST' queries offline from our station city index.
        """
        clean = query.strip().upper()
        # Match "City, ST" format
        match = re.match(r'^([^,]+),\s*([A-Z]{2})$', clean)
        if match:
            city, state = match.group(1).strip(), match.group(2).strip()
            return self.city_lookup.get((city, state))
        return None

    def find_candidate_stations_along_route(
        self,
        geometry_coords: List[List[float]],
        total_route_distance: float,
        corridor_miles: float = 25.0
    ) -> List[FuelStation]:
        """
        Efficiently filters stations within corridor_miles of the route.
        Assigns each candidate station its approximate distance from route start.
        Returns candidates sorted in ascending order of distance along route.
        """
        if not geometry_coords or len(geometry_coords) < 2:
            return []

        # 1. Sample route polyline every ~2 miles to reduce coordinate checks
        # OSRM coordinates are in [lon, lat] format
        sampled_points: List[Tuple[float, float, float]] = []  # (lat, lon, cum_dist)
        cum_dist = 0.0
        first_pt = geometry_coords[0]
        sampled_points.append((first_pt[1], first_pt[0], 0.0))
        last_sampled_dist = 0.0

        for i in range(1, len(geometry_coords)):
            prev_lon, prev_lat = geometry_coords[i - 1]
            curr_lon, curr_lat = geometry_coords[i]
            seg_dist = haversine_miles(prev_lat, prev_lon, curr_lat, curr_lon)
            cum_dist += seg_dist

            if cum_dist - last_sampled_dist >= 2.0:
                sampled_points.append((curr_lat, curr_lon, cum_dist))
                last_sampled_dist = cum_dist

        # Always include final point
        last_pt = geometry_coords[-1]
        sampled_points.append((last_pt[1], last_pt[0], cum_dist))

        # 2. Collect candidate stations from grid cells near sampled points
        # Corridor tolerance in degrees (approx 1 deg lat = 69 miles)
        # Check adjacent 3x3 buckets
        potential_stations: Dict[str, FuelStation] = {}
        for lat, lon, _ in sampled_points:
            b_lat = int(lat * 2.0)
            b_lon = int(lon * 2.0)
            for d_lat in (-1, 0, 1):
                for d_lon in (-1, 0, 1):
                    for st in self.grid.get((b_lat + d_lat, b_lon + d_lon), []):
                        potential_stations[st.opis_id] = st

        # 3. For each potential station, calculate minimum distance to sampled route points
        candidates: List[FuelStation] = []
        for station in potential_stations.values():
            min_dist_to_route = float('inf')
            best_cum_dist = 0.0

            for r_lat, r_lon, r_dist in sampled_points:
                # Fast degree check before expensive haversine
                d_lat = abs(station.latitude - r_lat)
                d_lon = abs(station.longitude - r_lon)
                if d_lat > 0.45 or d_lon > 0.60:
                    continue

                dist = haversine_miles(station.latitude, station.longitude, r_lat, r_lon)
                if dist < min_dist_to_route:
                    min_dist_to_route = dist
                    best_cum_dist = r_dist

            if min_dist_to_route <= corridor_miles:
                # Discard stations that fall before start or past destination along the route
                if 0.0 < best_cum_dist < total_route_distance:
                    # Create a route-positioned station instance
                    route_station = FuelStation(
                        opis_id=station.opis_id,
                        name=station.name,
                        address=station.address,
                        city=station.city,
                        state=station.state,
                        rack_id=station.rack_id,
                        price=station.price,
                        latitude=station.latitude,
                        longitude=station.longitude,
                        distance_along_route=best_cum_dist,
                        corridor_offset_miles=min_dist_to_route,
                    )
                    candidates.append(route_station)

        # 4. Sort candidates by progress along the route
        candidates.sort(key=lambda s: s.distance_along_route)

        logger.debug(
            "Found %d candidate stations within %s-mile corridor out of %d checked.",
            len(candidates), corridor_miles, len(potential_stations)
        )
        return candidates
