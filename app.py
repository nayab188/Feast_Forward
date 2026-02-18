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
    cur.execute("""CREATE TABLE IF NOT EXISTS recipe_mapping (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    restaurant_id INTEGER NOT NULL,
                    menu_item TEXT NOT NULL,
                    ingredient_name TEXT NOT NULL,
                    qty_per_serving REAL NOT NULL,
                    unit TEXT NOT NULL,
                    FOREIGN KEY (restaurant_id) 
                    REFERENCES restaurants(id) 
                    ON DELETE CASCADE
                 )""")
    cur.execute(""" CREATE TABLE IF NOT EXISTS staff_mapping (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    restaurant_id INTEGER NOT NULL,
                    menu_item TEXT NOT NULL,
                    base_servings INTEGER NOT NULL,
                    cooks INTEGER NOT NULL,
                    helpers INTEGER NOT NULL,
                    cleaners INTEGER NOT NULL,
                    FOREIGN KEY (restaurant_id)
                        REFERENCES restaurants(id)
                        ON DELETE CASCADE
                )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS staff_predictions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        restaurant_id INTEGER,
                        menu_item TEXT,
                        predicted_servings INTEGER,
                        cooks INTEGER,
                        helpers INTEGER,
                        cleaners INTEGER,
                        calculated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS combos (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        restaurant_id INTEGER,
                        combo_name TEXT,
                        items TEXT,
                        total_cost REAL,
                        discount_percent REAL,
                        final_price REAL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (restaurant_id)
                            REFERENCES restaurants(id)
                            ON DELETE CASCADE
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

    recipe_exists = has_recipe_setup(restaurant_id)
    staff_history = load_staff_history(restaurant_id)
    combos = load_combos(restaurant_id)



    return render_template(
        'dashboard.html',
        user=user,
        services=services,
        predictions=predictions,
        staff_history=staff_history,
        combos=combos,
        menu_items=menu_items,
        recipe_exists=recipe_exists,
        auto_open_manage=False
    )


def has_recipe_setup(restaurant_id):
    with get_db() as con:
        cur = con.execute(
            "SELECT COUNT(*) FROM recipe_mapping WHERE restaurant_id = ?",
            (restaurant_id,)
        )
        count = cur.fetchone()[0]
        return count > 0


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
def calculate_staff(base_servings, predicted_servings, cooks, helpers, cleaners):
    if base_servings == 0:
        return {
            "cooks": 0,
            "helpers": 0,
            "cleaners": 0
        }
    multiplier = predicted_servings / base_servings

    return {
        "cooks": round(cooks * multiplier),
        "helpers": round(helpers * multiplier),
        "cleaners": round(cleaners * multiplier)
    }


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
    
def load_staff_history(restaurant_id):
    with get_db() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT menu_item, predicted_servings, cooks, helpers, cleaners, calculated_at
            FROM staff_predictions
            WHERE restaurant_id = ?
            ORDER BY calculated_at DESC
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
        recipe_exists = has_recipe_setup(restaurant_id)
        return render_template(
            "dashboard.html",
            error=prediction["error"],
            menu_items=get_trained_menu_items(restaurant_id),
            predictions=[],
            recipe_exists=recipe_exists,
            auto_open_manage=False,
            **context
        )

    predictions = load_predictions(restaurant_id)
    recipe_exists = has_recipe_setup(restaurant_id)

    return render_template(
        "dashboard.html",
        prediction=prediction,
        staff_history=load_staff_history(restaurant_id),
        menu_items=get_trained_menu_items(restaurant_id),
        predictions=predictions,
        recipe_exists=recipe_exists,
        auto_open_manage=False,
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

@app.route("/grocery-setup", methods=["POST"])
def grocery_setup():
    if "user_id" not in session:
        return redirect("/login")

    restaurant_id = get_restaurant_id(session["user_id"])

    menu_item = request.form["menu_item"]
    ingredients = request.form.getlist("ingredient_name[]")
    quantities = request.form.getlist("qty_per_serving[]")
    units = request.form.getlist("unit[]")

    with get_db() as con:
        cur = con.cursor()

        cur.execute("""
            DELETE FROM recipe_mapping
            WHERE restaurant_id = ?
            AND menu_item = ?
        """, (restaurant_id, menu_item))

        for name, qty, unit in zip(ingredients, quantities, units):
            if name.strip() == "":
                continue

            cur.execute("""
                INSERT INTO recipe_mapping
                (restaurant_id, menu_item, ingredient_name, qty_per_serving, unit)
                VALUES (?, ?, ?, ?, ?)
            """, (
                restaurant_id,
                menu_item,
                name.strip(),
                float(qty),
                unit.strip()
            ))

        con.commit()

    return redirect("/dashboard")

@app.route("/calculate-groceries", methods=["POST"])
def calculate_groceries():
    if "user_id" not in session:
        return redirect("/login")

    restaurant_id = get_restaurant_id(session["user_id"])

    menu_item = request.form["menu_item"]
    servings = float(request.form["servings"])

    with get_db() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT ingredient_name, qty_per_serving, unit
            FROM recipe_mapping
            WHERE restaurant_id = ?
            AND menu_item = ?
        """, (restaurant_id, menu_item))

        rows = cur.fetchall()

    if not rows:
        context = load_dashboard_context(restaurant_id, session["user_id"])
        recipe_exists = has_recipe_setup(restaurant_id)

        return render_template(
            "dashboard.html",
            error="No recipe defined for this menu item.",
            menu_items=get_trained_menu_items(restaurant_id),
            staff_history=load_staff_history(restaurant_id),
            predictions=load_predictions(restaurant_id),
            recipe_exists=recipe_exists,
            auto_open_manage=True,
            **context
        )


    results = []
    for ingredient, qty_per_serving, unit in rows:
        required = round(qty_per_serving * servings, 2)
        results.append({
            "ingredient": ingredient,
            "required": required,
            "unit": unit
        })

    context = load_dashboard_context(restaurant_id, session["user_id"])
    recipe_exists = has_recipe_setup(restaurant_id)


    return render_template(
    "dashboard.html",
    grocery_results=results,
    selected_menu=menu_item,
    entered_servings=servings,
    menu_items=get_trained_menu_items(restaurant_id),
    staff_history=load_staff_history(restaurant_id),
    predictions=load_predictions(restaurant_id),
    recipe_exists=recipe_exists,
    auto_open_manage=True,
    **context
    )

@app.route("/save-staff-config", methods=["POST"])
def save_staff_config():
    if "user_id" not in session:
        return redirect("/login")

    restaurant_id = get_restaurant_id(session["user_id"])

    menu_items = request.form.getlist("menu_item[]")
    base_servings = request.form.getlist("base_servings[]")
    cooks = request.form.getlist("cooks[]")
    helpers = request.form.getlist("helpers[]")
    cleaners = request.form.getlist("cleaners[]")

    with get_db() as con:
        cur = con.cursor()

        for m, b, c, h, cl in zip(menu_items, base_servings, cooks, helpers, cleaners):

            cur.execute("""
                DELETE FROM staff_mapping
                WHERE restaurant_id = ?
                AND menu_item = ?
            """, (restaurant_id, m))

            cur.execute("""
                INSERT INTO staff_mapping
                (restaurant_id, menu_item, base_servings, cooks, helpers, cleaners)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                restaurant_id,
                m,
                int(b),
                int(c),
                int(h),
                int(cl)
            ))

        con.commit()

    return redirect("/dashboard")

@app.route("/calculate-staff", methods=["POST"])
def calculate_staff_route():
    if "user_id" not in session:
        return redirect("/login")

    restaurant_id = get_restaurant_id(session["user_id"])
    menu_item = request.form["menu_item"]
    predicted_servings = int(request.form["predicted_servings"])

    with get_db() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT base_servings, cooks, helpers, cleaners
            FROM staff_mapping
            WHERE restaurant_id = ?
            AND menu_item = ?
        """, (restaurant_id, menu_item))

        row = cur.fetchone()

    if not row:
        context = load_dashboard_context(restaurant_id, session["user_id"])
        return render_template(
            "dashboard.html",
            error="No staff configuration found for this menu item.",
            menu_items=get_trained_menu_items(restaurant_id),
            predictions=load_predictions(restaurant_id),
            staff_history=load_staff_history(restaurant_id),
            recipe_exists=has_recipe_setup(restaurant_id),
            auto_open_manage=False,
            **context
        )

    base_servings, cooks, helpers, cleaners = row

    result = calculate_staff(
        base_servings,
        predicted_servings,
        cooks,
        helpers,
        cleaners
    )

    staff_results = {
        "menu_item": menu_item,
        "servings": predicted_servings,
        "cooks": result["cooks"],
        "helpers": result["helpers"],
        "cleaners": result["cleaners"]
    }

    context = load_dashboard_context(restaurant_id, session["user_id"])
    with get_db() as con:
        con.execute("""
            INSERT INTO staff_predictions
            (restaurant_id, menu_item, predicted_servings, cooks, helpers, cleaners)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            restaurant_id,
            menu_item,
            predicted_servings,
            result["cooks"],
            result["helpers"],
            result["cleaners"]
        ))
        con.commit()


    return render_template(
        "dashboard.html",
        staff_results=staff_results,
        staff_history=load_staff_history(restaurant_id), 
        menu_items=get_trained_menu_items(restaurant_id),
        predictions=load_predictions(restaurant_id),
        recipe_exists=has_recipe_setup(restaurant_id),
        auto_open_manage=False,
        **context
    )
    # return redirect("/dashboard")
@app.route("/prepare-combo", methods=["POST"])
def prepare_combo():

    if "user_id" not in session:
        return redirect("/login")

    restaurant_id = get_restaurant_id(session["user_id"])

    menu_items = request.form.getlist("menu_item[]")
    predicted = request.form.getlist("predicted_servings[]")
    sold = request.form.getlist("sold_quantity[]")
    costs = request.form.getlist("cost_per_item[]")

    

    combo_data = []
    total_cost = 0

    for m, p, s, c in zip(menu_items, predicted, sold, costs):

        leftover = int(p) - int(s)

        if leftover <= 0:
            continue

        item_cost = float(c)

        combo_data.append({
            "menu_item": m,
            "leftover": leftover,
            "cost_per_item": item_cost
        })

        total_cost += item_cost

    context = load_dashboard_context(restaurant_id, session["user_id"])
    if len(combo_data) < 3:
        return redirect("/dashboard")

    return render_template(
        "dashboard.html",
        show_discount_options=True,
        combo_data=combo_data,
        total_cost=total_cost,
        menu_items=get_trained_menu_items(restaurant_id),
        predictions=load_predictions(restaurant_id),
        staff_history=load_staff_history(restaurant_id),
        combos=load_combos(restaurant_id),   # ADD THIS
        recipe_exists=has_recipe_setup(restaurant_id),
        **context
    )



@app.route("/create-combo", methods=["POST"])
def create_combo():

    if "user_id" not in session:
        return redirect("/login")

    restaurant_id = get_restaurant_id(session["user_id"])

    import json

    combo_data = json.loads(request.form["combo_data"])
    discount = float(request.form["discount"])

    total_cost = sum(item["cost_per_item"] for item in combo_data)

    final_price = round(
        total_cost * (1 + discount / 100),
        2
    )
    
    combo_name = " + ".join([item["menu_item"] for item in combo_data])
    combo_name = combo_name + "(Super Saver)"

    with get_db() as con:
        con.execute("""
            INSERT INTO combos
            (restaurant_id, combo_name, items,
             total_cost, discount_percent, final_price)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            restaurant_id,
            combo_name,
            json.dumps(combo_data),
            total_cost,
            discount,
            final_price
        ))
        con.commit()

    return redirect("/dashboard")


def load_combos(restaurant_id):
    with get_db() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT combo_name, final_price, discount_percent, created_at
            FROM combos
            WHERE restaurant_id = ?
            ORDER BY created_at DESC
        """, (restaurant_id,))
        return cur.fetchall()



if __name__ == '__main__':
    app.run(debug=True)