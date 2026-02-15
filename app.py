from flask import Flask, render_template, request, redirect, session
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
import os
from werkzeug.utils import secure_filename
import pandas as pd
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'feast_forward_nayab'


def get_db():
    return sqlite3.connect('database.db')

with get_db() as con:
    cur = con.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS users(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS restaurants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS feature_settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    restaurant_id INTEGER NOT NULL,
                    grocery_management BOOLEAN DEFAULT 0,
                    staff_management BOOLEAN DEFAULT 0,
                    combo_creation BOOLEAN DEFAULT 0,
                    FOREIGN KEY (restaurant_id) REFERENCES restaurants(id) ON DELETE CASCADE
                )''')
    cur.execute("""CREATE TABLE IF NOT EXISTS predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prediction_uid TEXT,
                    restaurant_id INTEGER,
                    menu_item TEXT,
                    predicted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    servings INTEGER
                )""")

    con.commit()

@app.route('/')
def home():
    return redirect('/login')

@app.route('/login',methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        user = request.form['username']
        pwd = request.form['password']
        with get_db() as con:
            cur = con.execute('SELECT * FROM users where username=?',(user,))
            row = cur.fetchone()
            if not row:
                error = "User does not exist"
            elif not check_password_hash(row[2], pwd):
                error = "Incorrect password"
            else:
                session['user_id'] = row[0]
                return redirect('/dashboard')    
    return render_template('login.html',error = error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


@app.route('/signup',methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        data = request.form
        password = generate_password_hash(data['password'])
        g = 1 if data.get('grocery') else 0
        s = 1 if data.get('staff') else 0
        c = 1 if data.get('combo') else 0
        try:
            with get_db() as con:
                #in case error osthey comma check cheskovali
                cur = con.cursor()
                cur.execute('''INSERT INTO users (username, password_hash) VALUES (?, ?)''',(data['username'],password))
                uid = cur.lastrowid
                cur.execute('''INSERT INTO restaurants(user_id,name) VALUES (?,?)''',(uid,data['restaurant']))
                rid = cur.lastrowid
                cur.execute('''INSERT INTO feature_settings(restaurant_id,grocery_management,staff_management,combo_creation) VALUES(?,?,?,?)''',(rid,g,s,c))
                con.commit()
            return redirect('/login') 
        except: 
            # in case exception vasthe internal ga sqlite ye rollback chesthadi commit ni so you no need to worry 
            return 'User already exists'   
    return render_template('signup.html')

@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    if 'user_id' not in session:
        return redirect('/login')

    uid = session['user_id']

    with get_db() as con:
        cur = con.cursor()

        cur.execute("""
            SELECT r.id, r.name,
                   f.grocery_management,
                   f.staff_management,
                   f.combo_creation
            FROM restaurants r
            JOIN feature_settings f ON f.restaurant_id = r.id
            WHERE r.user_id = ?
        """, (uid,))
        row = cur.fetchone()

        if not row:
            return "No restaurant found", 404

        restaurant_id = row[0]

        user = {
            "restaurant_name": row[1]
        }

        services = {
            "grocery": bool(row[2]),
            "staff": bool(row[3]),
            "combo": bool(row[4])
        }

        cur.execute("""
            SELECT menu_item, predicted_at, servings
            FROM predictions
            WHERE restaurant_id = ?
            ORDER BY predicted_at DESC
        """, (restaurant_id,))
        predictions = cur.fetchall()

    menu_items = get_trained_menu_items(restaurant_id)

    return render_template(
        'dashboard.html',
        user=user,
        services=services,
        predictions=predictions,
        menu_items=menu_items
    )

    

def get_trained_menu_items(restaurant_id):
    base_path = f"ml/storage/user_{restaurant_id}"
    if not os.path.exists(base_path):
        return []

    return [
        name for name in os.listdir(base_path)
        if os.path.isdir(os.path.join(base_path, name))
    ]

def get_restaurant_id(user_id):
    with get_db() as con:
        cur = con.execute(
            "SELECT id FROM restaurants WHERE user_id = ?",
            (user_id,)
        )
        return cur.fetchone()[0]

def get_last_30d_avg(restaurant_id, menu_item):
    path = f"uploads/user_{restaurant_id}/{menu_item.lower().replace(' ', '_')}.csv"

    if not os.path.exists(path):
        return 0

    df = pd.read_csv(path)

    if "Date" not in df.columns or "no_of_servings" not in df.columns:
        return 0

    df["Date"] = pd.to_datetime(df["Date"],format="%d-%m-%Y")
    last_30 = df.sort_values("Date").tail(30)

    return float(last_30["no_of_servings"].mean())

def save_csv(restaurant_id, menu_item, csv_file):
    base_dir = f"uploads/user_{restaurant_id}"
    os.makedirs(base_dir, exist_ok=True)

    filename = secure_filename(menu_item.lower().replace(" ", "_") + ".csv")
    path = os.path.join(base_dir, filename)

    csv_file.save(path)
    return path

def train_menu_item_model(restaurant_id, menu_item, csv_path):
    from ml.train import train_and_save

    model_dir = f"ml/storage/user_{restaurant_id}/{menu_item}"
    os.makedirs(model_dir, exist_ok=True)

    train_and_save(
        menu_item=menu_item,
        csv_path=csv_path,
        output_dir=model_dir
    )

@app.route("/process-all-sales", methods=["POST"])
def process_all_sales():
    if "user_id" not in session:
        return redirect("/login")

    menu_items = request.form.getlist("menu_items[]")
    csv_files = request.files.getlist("sales_csvs[]")

    if len(menu_items) != len(csv_files):
        return "Mismatch in menu items and CSVs", 400

    restaurant_id = get_restaurant_id(session["user_id"])

    for menu_item, csv in zip(menu_items, csv_files):
        csv_path = save_csv(restaurant_id, menu_item, csv)

        train_menu_item_model(
            restaurant_id=restaurant_id,
            menu_item=menu_item,
            csv_path=csv_path
        )

    return redirect("/dashboard")

def load_dashboard_context(restaurant_id, uid):
    with get_db() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT r.name,
                   f.grocery_management,
                   f.staff_management,
                   f.combo_creation
            FROM restaurants r
            JOIN feature_settings f ON f.restaurant_id = r.id
            WHERE r.user_id = ?
        """, (uid,))
        row = cur.fetchone()

    return {
        "user": {"restaurant_name": row[0]},
        "services": {
            "grocery": bool(row[1]),
            "staff": bool(row[2]),
            "combo": bool(row[3])
        }
    }

def load_predictions(restaurant_id):
    with get_db() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT menu_item, predicted_at, servings
            FROM predictions
            WHERE restaurant_id = ?
            ORDER BY predicted_at DESC
        """, (restaurant_id,))
        return cur.fetchall()

@app.route("/predict", methods=["POST"])
def predict():
    if "user_id" not in session:
        return redirect("/login")

    menu_item = request.form["menu_item"]
    restaurant_id = get_restaurant_id(session["user_id"])

    date_obj = datetime.strptime(request.form["date"], "%Y-%m-%d")

    features = {
        "day_of_week": date_obj.strftime("%A"),
        "meal_period": request.form["meal_period"],
        "is_holiday": int(request.form.get("holiday", 0)),
        "weather": request.form["weather"],
        "temperature": float(request.form.get("temperature", 25)),
        "sales_last_30d_avg": get_last_30d_avg(
            restaurant_id,
            menu_item
        )
    }

    from ml.predict import predict_demand

    prediction = predict_demand(
        restaurant_id=restaurant_id,
        menu_item=menu_item,
        features=features
    )

    context = load_dashboard_context(restaurant_id, session["user_id"])

    if "error" in prediction:
        return render_template(
            "dashboard.html",
            error=prediction["error"],
            menu_items=get_trained_menu_items(restaurant_id),
            predictions=[],
            **context
        )

    predictions = load_predictions(restaurant_id)

    return render_template(
        "dashboard.html",
        prediction=prediction,
        menu_items=get_trained_menu_items(restaurant_id),
        predictions=predictions,
        **context
    )

@app.route("/save-prediction", methods=["POST"])
def save_prediction():
    if "user_id" not in session:
        return redirect("/login")

    restaurant_id = get_restaurant_id(session["user_id"])

    prediction_uid = request.form["prediction_uid"]
    menu_item = request.form["menu_item"]
    servings = request.form["servings"]

    with get_db() as con:
        con.execute("""
            INSERT INTO predictions (
                prediction_uid,
                restaurant_id,
                menu_item,
                servings
            )
            VALUES (?, ?, ?, ?)
        """, (prediction_uid, restaurant_id, menu_item, servings))
        con.commit()

    return redirect("/dashboard")



if __name__ == '__main__':
    app.run(debug=True)