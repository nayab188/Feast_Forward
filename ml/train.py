import pandas as pd
import joblib
import json
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import LabelEncoder
from datetime import datetime, timezone
import os

def train_and_save(menu_item, csv_path, output_dir):
    df = pd.read_csv(csv_path)


    df.drop(columns=["Date"], inplace=True, errors="ignore")


    encoders = {}

    for col in ["day_of_week", "meal_period", "weather"]:
        le = LabelEncoder()
        df[col] = le.fit_transform(df[col])
        encoders[col] = le

    X = df[
        [
            "day_of_week",
            "meal_period",
            "is_holiday",
            "weather",
            "temperature",
            "sales_last_30d_avg"
        ]
    ]

    y = df["no_of_servings"]

    model = RandomForestRegressor(
        n_estimators=200,
        random_state=42
    )

    model.fit(X, y)

    os.makedirs(output_dir, exist_ok=True)

    joblib.dump(
        {
            "model": model,
            "encoders": encoders
        },
        f"{output_dir}/model.pkl"
    )

    meta = {
        "menu_item": menu_item,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "rows_used": len(df)
    }

    with open(f"{output_dir}/meta.json", "w") as f:
        json.dump(meta, f)
