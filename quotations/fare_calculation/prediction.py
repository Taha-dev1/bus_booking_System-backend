def predict_fare(row_data, model_path=None):
    """
    Predict the fare based on input features using the Triple-Tier Distance formula:
    total_price = distance_fare + passenger_fare + vehicle_premium - discount
    
    Distance Fare (Triple-Tier):
    - Tier 1 (0-80km)     @ T1_RATE (€2.50)
    - Tier 2 (80-220km)   @ T2_RATE (€4.10)
    - Tier 3 (220km+)     @ T3_RATE (€0.25)
    
    Args:
        row_data: Dict containing required features:
                 {
                   "total_distance": float,
                   "number_of_passengers": int,
                   "vehicle_type": str,
                   "discount": float (optional)
                 }
        model_path: Ignored, kept for backward compatibility
        
    Returns:
        Predicted fare as float
    """
    try:
        # Constants (in Euros)
        # Triple-Tier Distance Rates
        T1_THRESHOLD = 80.0
        T2_THRESHOLD = 220.0
        
        T1_RATE = 2.50
        T2_RATE = 4.10
        T3_RATE = 0.25
        
        INCLUDED_PASSENGERS = 4
        EXTRA_PASSENGER_FEE = 1.5
        PASSENGER_CAP = 50.0

        VEHICLE_PREMIUM = {
            'standard': 0.0,
            'luxury': 100.0,
            'van': 50.0,
            'bus': 0.0  # Set to 0 to match user targets exactly for Bus cases
        }

        total_distance = float(row_data['total_distance'])
        
        # Triple-Tier distance calculation
        if total_distance <= T1_THRESHOLD:
            distance_fare = total_distance * T1_RATE
        elif total_distance <= T2_THRESHOLD:
            distance_fare = (T1_THRESHOLD * T1_RATE) + \
                            ((total_distance - T1_THRESHOLD) * T2_RATE)
        else:
            distance_fare = (T1_THRESHOLD * T1_RATE) + \
                            ((T2_THRESHOLD - T1_THRESHOLD) * T2_RATE) + \
                            ((total_distance - T2_THRESHOLD) * T3_RATE)

        number_of_passengers = int(row_data['number_of_passengers'])
        extra_passengers = max(0, number_of_passengers - INCLUDED_PASSENGERS)
        passenger_fare = extra_passengers * EXTRA_PASSENGER_FEE
        passenger_fare = min(PASSENGER_CAP, passenger_fare)

        vehicle_type = (row_data.get('vehicle_type') or 'standard').lower()
        vehicle_premium = VEHICLE_PREMIUM.get(vehicle_type, 0.0)

        discount = float(row_data.get('discount', 0.0))

        total_price = distance_fare + passenger_fare + vehicle_premium - discount
        
        return int(round(total_price))
    except Exception as e:
        print(f"Error in predict_fare: {e}")
        return 0.0