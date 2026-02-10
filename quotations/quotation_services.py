


import math
from decimal import Decimal
import requests
from decouple import config
import joblib  # or whatever library you use for your model
import os
from django.conf import settings
from .models import Lead
import json
MODEL_PATH = os.path.join(
    settings.BASE_DIR, 'ML_MODELS_DIR', 'best_model.joblib')

try:
    PRICE_PREDICTION_MODEL = joblib.load(MODEL_PATH)
except Exception as e:
    PRICE_PREDICTION_MODEL = None
    print(f"Failed to load price prediction model: {e}")


def distance_between_addresses(origin_address, dest_address):
    """
    Call the Google Distance Matrix API and return the distance (in KM)
    between two addresses. Returns 0.0 if there is any error.
    """
    try:
        api_key = config('GOOGLE_MAPS_API_KEY')
        url = "https://maps.googleapis.com/maps/api/distancematrix/json"
        params = {
            'origins': origin_address,
            'destinations': dest_address,
            'units': 'metric',
            'key': api_key
        }
        response = requests.get(url, params=params)
        data = response.json()
        # Uncomment for debugging:

        if 'rows' in data and data['rows']:
            elements = data['rows'][0].get('elements', [])
            if elements and elements[0].get('status') == 'OK':
                meters = elements[0]['distance']['value']
                return round(meters / 1000.0, 2)
            else:
                raise ValueError(
                    f"Distance not found or bad status for: '{origin_address}' to '{dest_address}'"
                )
        else:
            raise ValueError(f"No data returned from API for: '{origin_address}' to '{dest_address}'")
    except Exception as e:
        raise ValueError(
            f"DistanceMatrix error for '{origin_address}' to '{dest_address}': {e}"
        )


# Removed Quotation-related distance and price calculation functions.

# Keep all the Lead-related functions unchanged


def distance_between_addresses_lead(origin_address: str, dest_address: str) -> float:
    """
    Use Google Routes API to calculate driving distance (in KM) between two addresses.
    Raises ValueError on error.
    """
    try:
        api_key = config('GOOGLE_MAPS_API_KEY')
        url = f"https://routes.googleapis.com/directions/v2:computeRoutes"

        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "routes.distanceMeters",
            "Referer": "http://localhost:8000/"
        }

        body = {
            "origin": {
                "address": origin_address
            },
            "destination": {
                "address": dest_address
            },
            "travelMode": "DRIVE"
        }


        response = requests.post(url, headers=headers, json=body)
        data = response.json()

        if response.status_code != 200:
            raise ValueError(f"Routes API error: {data}")

        routes = data.get("routes", [])
        if not routes or "distanceMeters" not in routes[0]:
            raise ValueError(f"No route or distance found for: '{origin_address}' -> '{dest_address}'")

        meters = routes[0]["distanceMeters"]
        return round(meters / 1000.0, 2)

    except Exception as e:
        raise ValueError(f"Error fetching distance from Routes API: {e}")


def get_aggregated_distance_lead(lead: Lead) -> float:
    """
    Compute total journey distance (in KM) for a Lead using its outbound and return trips.
    """
    total_distance = 0.0

    # 1. Calculate Outbound Trip distance
    if lead.outbound_trip:
        trip = lead.outbound_trip
        addresses = [trip.pickup_location]
        # Add TripStops
        stops = list(trip.stops.order_by('stop_order').values_list('location', flat=True))
        addresses.extend(stops)
        addresses.append(trip.dropoff_location)

        for i in range(len(addresses) - 1):
            try:
                total_distance += distance_between_addresses_lead(addresses[i], addresses[i + 1])
            except ValueError as e:
                print(f"Warning: {e}")

    # 2. Calculate Return Trip distance
    if lead.return_trip:
        trip = lead.return_trip
        addresses = [trip.pickup_location]
        # Add TripStops
        stops = list(trip.stops.order_by('stop_order').values_list('location', flat=True))
        addresses.extend(stops)
        addresses.append(trip.dropoff_location)

        for i in range(len(addresses) - 1):
            try:
                total_distance += distance_between_addresses_lead(addresses[i], addresses[i + 1])
            except ValueError as e:
                print(f"Warning: {e}")

    return round(total_distance, 2)
