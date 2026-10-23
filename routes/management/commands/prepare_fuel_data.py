"""
Management command to preprocess, enrich, and index the fuel station dataset offline.
Reads the raw fuel prices CSV, enriches cities with US coordinates from the static US cities dataset,
deduplicates by OPIS Truckstop ID, and exports a fast-loading enriched dataset.
"""
import csv
import json
import logging
import re
import time
from pathlib import Path
from django.core.management.base import BaseCommand
from django.conf import settings

logger = logging.getLogger(__name__)


def normalize_name(name: str) -> str:
    """Strip all punctuation and whitespace for robust phonetic/string matching."""
    return re.sub(r'[^A-Z0-9]', '', name.upper())


class Command(BaseCommand):
    help = "Preprocess and enrich the raw fuel price CSV with static US city coordinates."

    def add_arguments(self, parser):
        parser.add_argument(
            '--fuel-csv',
            type=str,
            default=str(settings.RAW_FUEL_CSV_PATH),
            help='Path to raw fuel prices CSV',
        )
        parser.add_argument(
            '--cities-csv',
            type=str,
            default=str(settings.US_CITIES_CSV_PATH),
            help='Path to US cities coordinates CSV',
        )
        parser.add_argument(
            '--output',
            type=str,
            default=str(settings.FUEL_DATA_PATH),
            help='Path to output enriched JSON file',
        )

    def handle(self, *args, **options):
        start_time = time.time()
        fuel_csv_path = Path(options['fuel_csv'])
        # Fallback to root directory if not found in data/
        if not fuel_csv_path.exists():
            root_fallback = settings.BASE_DIR / 'fuel-prices-for-be-assessment.csv'
            if root_fallback.exists():
                fuel_csv_path = root_fallback

        cities_csv_path = Path(options['cities_csv'])
        output_path = Path(options['output'])

        if not fuel_csv_path.exists():
            self.stderr.write(self.style.ERROR(f"Fuel CSV not found at {fuel_csv_path}"))
            return

        if not cities_csv_path.exists():
            self.stderr.write(self.style.ERROR(f"Cities CSV not found at {cities_csv_path}"))
            return

        self.stdout.write(self.style.NOTICE(f"Loading US cities coordinates from {cities_csv_path}..."))
        city_coords = {}
        with open(cities_csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                city = row['CITY'].strip().upper()
                state = row['STATE_CODE'].strip().upper()
                lat = float(row['LATITUDE'])
                lon = float(row['LONGITUDE'])
                city_coords[(city, state)] = (lat, lon)
                city_coords[(normalize_name(city), state)] = (lat, lon)

        # Well-known fallback for edge unincorporated postal communities in the dataset
        edge_cities = {
            ('PORT WENTWORTH', 'GA'): (32.1494, -81.1632),
            ('ELIZABETHPORT', 'NJ'): (40.6501, -74.1957),
            ('EVERGREEN', 'AL'): (31.4338, -86.9544),
            ('HENRICO', 'VA'): (37.5385, -77.3489),
            ('UNIVERSITY PARK', 'IL'): (41.4428, -87.6975),
        }
        for (c, s), coords in edge_cities.items():
            city_coords[(c, s)] = coords
            city_coords[(normalize_name(c), s)] = coords

        self.stdout.write(self.style.NOTICE(f"Indexed {len(city_coords)} US city name variations."))

        # Exclude Canadian provinces
        canadian_provinces = {'AB', 'BC', 'MB', 'NB', 'NL', 'NS', 'NT', 'NU', 'ON', 'PE', 'QC', 'SK', 'YT'}

        self.stdout.write(self.style.NOTICE(f"Processing and deduplicating {fuel_csv_path}..."))
        total_raw_rows = 0
        us_raw_rows = 0
        stations_by_id = {}

        with open(fuel_csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                total_raw_rows += 1
                state = row['State'].strip().upper()
                if state in canadian_provinces:
                    continue
                us_raw_rows += 1

                opis_id = row['OPIS Truckstop ID'].strip()
                city = row['City'].strip().upper()
                try:
                    price = float(row['Retail Price'].strip())
                    if price <= 0.0:
                        continue
                except (ValueError, TypeError):
                    continue

                coords = city_coords.get((city, state)) or city_coords.get((normalize_name(city), state))
                if not coords:
                    continue

                station_entry = {
                    'opis_id': opis_id,
                    'name': row['Truckstop Name'].strip(),
                    'address': row['Address'].strip(),
                    'city': row['City'].strip(),
                    'state': state,
                    'rack_id': row['Rack ID'].strip(),
                    'price': price,
                    'latitude': round(coords[0], 6),
                    'longitude': round(coords[1], 6),
                }

                # Deduplicate: if OPIS ID is seen again, keep the lowest retail price
                if opis_id in stations_by_id:
                    if price < stations_by_id[opis_id]['price']:
                        stations_by_id[opis_id] = station_entry
                else:
                    stations_by_id[opis_id] = station_entry

        enriched_list = list(stations_by_id.values())
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(enriched_list, f, indent=2)

        elapsed = time.time() - start_time
        self.stdout.write(self.style.SUCCESS(
            f"Successfully enriched {len(enriched_list)} unique US stations from {total_raw_rows} raw rows "
            f"({us_raw_rows} US rows) in {elapsed:.2f}s."
        ))
        self.stdout.write(self.style.SUCCESS(f"Saved output to {output_path}"))
