from flask import Flask, jsonify, render_template
from flask_cors import CORS
import sqlite3
import os
import traceback

app = Flask(__name__)
# Enable CORS for all routes and origins
CORS(app, resources={r"/api/*": {"origins": "*"}})

# ABSOLUTE PATH: Update this string if your DB is located elsewhere!
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "../database/target_products.db"))
DB_PATH = "/home/rich/Documents/CODE_SESSIONS/Python_Freelance_Portfolio/Web_Scraping/target-scraper/data/target_products.db"

@app.route('/')
def home():
    return render_template('index.html')  # or redirect to your visualizer

@app.route("/api/products")
def get_products():
    print(f"--> API Request received. Looking for database at: {DB_PATH}")
    
    if not os.path.exists(DB_PATH):
        print(f"[ERROR] Database file DOES NOT EXIST at {DB_PATH}")
        return jsonify({"error": f"Database not found at {DB_PATH}"}), 404

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Query product data
        cursor.execute("""
            SELECT tcin, title, category, price, rating, review_count 
            FROM target_products 
            WHERE price IS NOT NULL
                AND review_count IS NOT NULL
        """)
        rows = cursor.fetchall()
        conn.close()
        
        products = [dict(row) for row in rows]
        print(f"--> Success! Returning {len(products)} products to frontend.")
        return jsonify(products)

    except Exception as e:
        print("[ERROR] Database query crashed:")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)