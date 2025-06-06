import os
import joblib
import pandas as pd  # ✅ Use pandas for correct input format
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, 'hemodialysis_predictor.pkl')

# Load model only once
_model = joblib.load(MODEL_PATH)

# Define the feature names in the exact order used during model training
FEATURE_COLUMNS = [
    'pre_dialysis_bp', 'during_dialysis_bp', 'post_dialysis_bp',
    'heart_rate', 'creatinine', 'urea', 'potassium', 'hemoglobin',
    'hematocrit', 'albumin', 'kt_v', 'urine_output', 'dry_weight',
    'fluid_removal_rate', 'dialysis_duration'
]


def prepare_features(data):
    # Map incoming keys to model feature names exactly
    feature_map = {
        'age': 'Age',
        'gender': 'Gender',
        'weight': 'Weight',
        'diabetes': 'Diabetes',
        'hypertension': 'Hypertension',
        'pre_dialysis_bp': 'Pre-Dialysis Blood Pressure',
        'during_dialysis_bp': 'During-Dialysis Blood Pressure',
        'post_dialysis_bp': 'Post-Dialysis Blood Pressure',
        'heart_rate': 'Heart Rate',
        'creatinine': 'Creatinine',
        'urea': 'Urea',
        'potassium': 'Potassium',
        'hemoglobin': 'Hemoglobin',
        'hematocrit': 'Hematocrit',
        'albumin': 'Albumin',
        'dialysis_duration': 'Dialysis Duration (hours)',
        'dialysis_frequency': 'Dialysis Frequency (per week)',
        'urr': 'URR',
        'urine_output': 'Urine Output (ml/day)',
        'dry_weight': 'Dry Weight (kg)',
        'fluid_removal_rate': 'Fluid Removal Rate (ml/hour)',
        'disease_severity': 'Disease Severity',
        'kt_v': 'Kt/V Category',
        # For one-hot encoded features, use 0 or 1 flags as needed
        'kidney_failure_cause_hypertension': 'Kidney Failure Cause_Hypertension',
        'kidney_failure_cause_other': 'Kidney Failure Cause_Other',
        'dialysate_composition_standard': 'Dialysate Composition_Standard',
        'vascular_access_type_fistula': 'Vascular Access Type_Fistula',
        'vascular_access_type_graft': 'Vascular Access Type_Graft',
        'dialyzer_type_low_flux': 'Dialyzer Type_Low-flux',
    }

    # Initialize dictionary with keys = model features, default 0 or None
    prepared = {col: 0 for col in feature_map.values()}

    # Fill prepared dict from data using the map
    for input_key, model_key in feature_map.items():
        if input_key in data:
            prepared[model_key] = data[input_key]

    return prepared
def encode_categorical_features(data):
    # Encode Gender
    gender_map = {
        'male': 1,
        'female': 0
    }
    if 'gender' in data:
        data['gender'] = gender_map.get(data['gender'].lower(), 0)  # default 0 if unknown

    # Encode Diabetes (if string)
    diabetes_map = {
        'yes': 1,
        'no': 0
    }
    if 'diabetes' in data:
        data['diabetes'] = diabetes_map.get(str(data['diabetes']).lower(), 0)

    # Encode Hypertension similarly
    hypertension_map = {
        'yes': 1,
        'no': 0
    }
    if 'hypertension' in data:
        data['hypertension'] = hypertension_map.get(str(data['hypertension']).lower(), 0)

    # Similarly for Disease Severity if categorical strings used
    severity_map = {
        'mild': 0,
        'moderate': 1,
        'severe': 2
    }
    if 'disease_severity' in data:
        data['disease_severity'] = severity_map.get(str(data['disease_severity']).lower(), 0)

    # Add other encodings if needed

    return data
def predict_hemodialysis(data):
    try:
        data = encode_categorical_features(data)
        prepared_features = prepare_features(data)
        input_df = pd.DataFrame([prepared_features])
        prediction = _model.predict(input_df)
        probability = _model.predict_proba(input_df) if hasattr(_model, 'predict_proba') else None

        return {
            "prediction": prediction[0],
            "probability": probability[0].tolist() if probability is not None else None
        }
    except Exception as e:
        raise ValueError(f"Prediction failed: {e}")