import os
import joblib
import time

def predict_demand(restaurant_id, menu_item, features):
    """
    restaurant_id : int
    menu_item     : str
    features      : dict with keys:
        - day_of_week
        - meal_period
        - is_holiday
        - weather
        - temperature
        - sales_last_30d_avg
    """

    model_path = f"ml/storage/user_{restaurant_id}/{menu_item}/model.pkl"

    if not os.path.exists(model_path):
        return {
            "error": "This menu item has not been trained yet."
        }

    # Load trained model + encoders
    bundle = joblib.load(model_path)
    model = bundle["model"]
    encoders = bundle["encoders"]

    try:
        day_encoded = encoders["day_of_week"].transform(
            [features["day_of_week"]]
        )[0]

        meal_encoded = encoders["meal_period"].transform(
            [features["meal_period"]]
        )[0]

        weather_encoded = encoders["weather"].transform(
            [features["weather"]]
        )[0]

    except Exception:
        return {
            "error": "Invalid input values for prediction."
        }

    # Prepare input in SAME ORDER as training
    X = [[
        day_encoded,
        meal_encoded,
        int(features["is_holiday"]),
        weather_encoded,
        float(features["temperature"]),
        float(features["sales_last_30d_avg"])
    ]]

    predicted_servings = int(model.predict(X)[0])

    return {
        "id": f"{menu_item}_{int(time.time())}",
        "menu_item": menu_item,
        "demand": predicted_servings
    }
