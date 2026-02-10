# predictor/services.py

import os
import pandas as pd
import joblib
from django.conf import settings

class PricePredictionService:
    """Service for loading the ML model and making predictions"""
    
    _instance = None
    _model_loaded = False
    
    
    def __new__(cls):
        """Singleton pattern to ensure model is loaded only once"""
        if cls._instance is None:
            cls._instance = super(PricePredictionService, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize the service and load the model"""
        if not self._model_loaded:
            self._load_model()
            PricePredictionService._model_loaded = True
    
    def _load_model(self):
        """Load the model and all its components from the joblib file"""
        model_path = os.path.join(settings.ML_MODELS_DIR, 'best_price_prediction_model.joblib')
        try:
            components = joblib.load(model_path)
            self.model = components['model']
            self.feature_scaler = components['feature_scaler']
            self.price_scaler = components['price_scaler']
            self.label_encoder = components['label_encoder']
            self.categorical_columns = components['categorical_columns']
            self.model_name = components['model_name']
            self.r2_score = components['r2_score']
        except Exception as e:
            print(f"Error loading model: {str(e)}")
            raise
    
    def predict(self, passengers, distance, total_time, stops, trip_type):
        """
        Make a price prediction based on input parameters
        
        Args:
            passengers (int): Number of passengers
            distance (float): Distance in km
            total_time (float): Total time in hours
            stops (int): Number of stops
            trip_type (str): One of 'Multi', 'One', or 'return'
            
        Returns:
            float: Predicted price
        """
        # Create a DataFrame with the input data
        input_data = pd.DataFrame({
            'Passengers': [passengers],
            'Distance_(km)': [distance],
            'Total_time (h)': [total_time],
            'stops': [stops],
            'Trip_Type': [trip_type]
        })
        
        # Process input data
        input_encoded = input_data.copy()
        
        # Apply label encoding for categorical columns
        for col in self.categorical_columns:
            if col in input_data.columns:
                input_encoded[col] = self.label_encoder.transform(input_data[col])
        
        # Scale features
        input_scaled = self.feature_scaler.transform(input_encoded)
        
        # Make prediction (normalized)
        pred_normalized = self.model.predict(input_scaled)
        
        # Convert back to original scale
        pred_original = self.price_scaler.inverse_transform(pred_normalized.reshape(-1, 1))
        
        return float(pred_original[0][0])
    
    def get_model_info(self):
        """Return information about the loaded model"""
        return {
            'model_name': self.model_name,
            'r2_score': self.r2_score,
            'categorical_features': self.categorical_columns
        }