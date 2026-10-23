"""
Live verification script for FuelRoute Docker instance.
Tests:
- Philadelphia -> Washington DC (short route, 0 stops)
- New York -> Chicago (medium route, 1 stop)
- Seattle -> Miami (long cross-country route, multi-stop)
- Rate limiting verification (burst requests)
"""
import requests
import json

BASE_URL = "http://localhost:8000"

def test_routes():
    routes = [
        ("Philadelphia -> Washington DC", {"start": "Philadelphia, PA", "finish": "Washington, DC"}),
        ("New York -> Chicago", {"start": "New York, NY", "finish": "Chicago, IL"}),
        ("Seattle -> Miami", {"start": "Seattle, WA", "finish": "Miami, FL"}),
    ]

    for name, payload in routes:
        print(f"\n==========================================")
        print(f"Testing Route: {name}")
        print(f"==========================================")
        res = requests.post(f"{BASE_URL}/api/v1/routes/optimize/", json=payload, timeout=30)
        print(f"HTTP Status: {res.status_code}")
        if res.status_code == 200:
            data = res.json()
            route = data["route"]
            summary = data["fuel_summary"]
            stops = data["fuel_stops"]
            print(f"Resolved Start: {route['start_resolved']}")
            print(f"Resolved Finish: {route['finish_resolved']}")
            print(f"Distance: {route['distance_miles']} miles")
            print(f"Duration: {route['duration_minutes']} minutes")
            print(f"Candidate Stations: {data['meta']['candidate_station_count']}")
            print(f"Fuel Stops Count: {len(stops)}")
            print(f"Total Fuel Consumed: {summary['total_gallons_consumed']} gal")
            print(f"Total Fuel Purchased: {summary['total_gallons_purchased']} gal")
            print(f"Total Fuel Cost: ${summary['total_fuel_cost']}")
            for idx, stop in enumerate(stops, 1):
                print(f"  Stop #{idx}: {stop['station_name']} ({stop['city']}, {stop['state']})")
                print(f"    Location on route: {stop['distance_from_start_miles']} mi | Retail: ${stop['price_per_gallon']}/gal | Gallons: {stop['gallons_purchased']} | Cost: ${stop['cost']}")
        else:
            print(f"Error Response: {res.text}")

def test_rate_limiting():
    print(f"\n==========================================")
    print("Testing Rate Limiting (Burst 25 requests)")
    print(f"==========================================")
    hit_429 = False
    for i in range(25):
        res = requests.post(f"{BASE_URL}/api/v1/routes/optimize/", json={"start": "Philadelphia, PA", "finish": "Washington, DC"}, timeout=10)
        if res.status_code == 429:
            hit_429 = True
            print(f"Request #{i+1} successfully throttled with HTTP 429!")
            print(f"Response: {res.text}")
            print(f"Retry-After header: {res.headers.get('Retry-After')}")
            break
    if not hit_429:
        print("Note: Rate limit was not reached within 25 requests.")

if __name__ == "__main__":
    test_routes()
    test_rate_limiting()
