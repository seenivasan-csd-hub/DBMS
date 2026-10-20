
from flask import (
    Flask, render_template, request,
    redirect, url_for, flash, session
)
import mysql.connector
from decimal import Decimal, InvalidOperation
from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)
from functools import wraps
import os

app = Flask(__name__)
app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY",
    "auction-demo-change-this-key"
)

def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="ChooseAnotherPassword!",
        database="auction_db"
    )

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not name or not email or not password:
            flash("Please fill in all fields.", "error")
            return redirect(url_for("register"))

        if len(password) < 8:
            flash("Password must contain at least 8 characters.", "error")
            return redirect(url_for("register"))

        password_hash = generate_password_hash(password)
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO Users (name, email, password)
                VALUES (%s, %s, %s)
                """,
                (name, email, password_hash)
            )
            conn.commit()
            flash("Registration successful! Please log in.", "success")
            return redirect(url_for("login"))

        except mysql.connector.IntegrityError:
            conn.rollback()
            flash("This email is already registered.", "error")

        except mysql.connector.Error:
            conn.rollback()
            app.logger.exception("Registration failed")
            flash("Database error during registration.", "error")

        finally:
            cursor.close()
            conn.close()

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            cursor.execute(
                """
                SELECT user_id, name, email, password
                FROM Users
                WHERE email = %s
                """,
                (email,)
            )
            user = cursor.fetchone()

        except mysql.connector.Error:
            app.logger.exception("Login failed")
            flash("Database error during login.", "error")
            return redirect(url_for("login"))

        finally:
            cursor.close()
            conn.close()

        if user and check_password_hash(user["password"], password):
            session.clear()
            session["user_id"] = user["user_id"]
            session["user_name"] = user["name"]
            session["user_email"] = user["email"]

            flash("Login successful!", "success")
            return redirect(url_for("home"))

        flash("Invalid email or password.", "error")

    return render_template("login.html")


@app.route("/")
def home():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT
                a.auction_id,
                a.end_time,
                a.status,
                p.product_name,
                p.description,
                p.starting_price,
                COALESCE(MAX(b.bid_amount), 0) AS highest_bid,
                COUNT(b.bid_id) AS total_bids
            FROM Auctions a
            JOIN Products p
                ON a.product_id = p.product_id
            LEFT JOIN Bids b
                ON a.auction_id = b.auction_id
            GROUP BY
                a.auction_id, a.end_time, a.status,
                p.product_name, p.description,
                p.starting_price
            ORDER BY a.auction_id DESC
        """)
        auctions = cursor.fetchall()
        print("Auctions fetched:", auctions)

        cursor.execute("""
            SELECT user_id, name FROM Users ORDER BY name
        """)
        users = cursor.fetchall()

        # Get declared auction winners
        cursor.execute("""
            SELECT
                w.auction_id,
                p.product_name,
                u.name AS winner_name,
                w.winning_bid,
                w.declared_at
            FROM Winners w
            JOIN Auctions a ON w.auction_id = a.auction_id
            JOIN Products p ON a.product_id = p.product_id
            JOIN Users u ON w.user_id = u.user_id
            ORDER BY w.declared_at DESC
        """)

        winners = cursor.fetchall()

        cursor.execute("""
            SELECT
                pay.payment_id,
                p.product_name,
                u.name AS winner_name,
                pay.amount,
                pay.payment_status,
                pay.payment_date
            FROM Payments pay
            JOIN Auctions a ON pay.auction_id = a.auction_id
            JOIN Products p ON a.product_id = p.product_id
            JOIN Users u ON pay.user_id = u.user_id
            ORDER BY pay.payment_id DESC
        """)
        payments = cursor.fetchall()
        logged_in = "user_id" in session

        return render_template(
            "index.html",
            logged_in=logged_in,
            auctions=auctions,
            users=users,
            winners=winners,
            payments=payments
        )

    finally:
        cursor.close()
        conn.close()


@app.route("/bid", methods=["POST"])
def place_bid():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        auction_id = int(request.form["auction_id"])
        user_id = int(request.form["user_id"])
        amount = Decimal(request.form["bid_amount"])

        if not amount.is_finite() or amount <= 0:
            raise ValueError("Bid must be a positive amount.")

        conn.start_transaction()

        # Lock the auction row while validating and saving the bid.
        cursor.execute("""
            SELECT auction_id, status, end_time, p.starting_price
            FROM Auctions a
            JOIN Products p ON a.product_id = p.product_id
            WHERE a.auction_id = %s
            FOR UPDATE
        """, (auction_id,))

        auction = cursor.fetchone()

        if not auction:
            raise ValueError("Auction not found.")

        
        cursor.execute("SELECT NOW() AS server_now")
        server_now = cursor.fetchone()["server_now"]


        if auction["status"] != "Active":
            raise ValueError("This auction is not active.")

       
        if auction["end_time"] is None or auction["end_time"] <= server_now:

            raise ValueError("This auction has ended.")

        cursor.execute("""
            SELECT MAX(bid_amount) AS highest_bid
            FROM Bids
            WHERE auction_id = %s
        """, (auction_id,))

        result = cursor.fetchone()
        highest_bid = result["highest_bid"]

        minimum_bid = (
            highest_bid
            if highest_bid is not None
            else auction["starting_price"]
        )

        if amount <= minimum_bid:
            raise ValueError(
                f"Your bid must be higher than {minimum_bid}."
            )

        cursor.execute("""
            INSERT INTO Bids (auction_id, user_id, bid_amount)
            VALUES (%s, %s, %s)
        """, (auction_id, user_id, amount))

        conn.commit()
        flash("Bid placed successfully!", "success")

    except (ValueError, InvalidOperation, KeyError):
        conn.rollback()
        flash("Invalid bid or auction. Check your details.", "error")

    except mysql.connector.Error:
        conn.rollback()
        app.logger.exception("Database error while placing bid")
        flash("Database error. Please try again.", "error")

    finally:
        cursor.close()
        conn.close()

    return redirect(url_for("home"))
    
@app.route("/mark-paid/<int:payment_id>", methods=["POST"])
def mark_paid(payment_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE Payments
            SET payment_status = 'Paid',
                payment_date = NOW()
            WHERE payment_id = %s
              AND payment_status = 'Pending'
        """, (payment_id,))

        if cursor.rowcount == 1:
            conn.commit()
            flash("Demo payment marked as Paid!", "success")
        else:
            conn.rollback()
            flash("Payment not found or already processed.", "error")

    except mysql.connector.Error:
        conn.rollback()
        app.logger.exception("Error updating payment")
        flash("Could not update payment status.", "error")

    finally:
        cursor.close()
        conn.close()

    return redirect(url_for("home"))
    
@app.route("/auction-history")
def auction_history():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT
                a.auction_id,
                p.product_name,
                a.start_time,
                a.end_time,
                a.status,
                u.name AS winner_name,
                w.winning_bid,
                COALESCE(pay.payment_status, 'Not Created')
                    AS payment_status
            FROM Auctions a
            JOIN Products p
                ON a.product_id = p.product_id
            LEFT JOIN Winners w
                ON a.auction_id = w.auction_id
            LEFT JOIN Users u
                ON w.user_id = u.user_id
            LEFT JOIN Payments pay
                ON a.auction_id = pay.auction_id
            ORDER BY a.auction_id DESC
        """)

        history = cursor.fetchall()

        return render_template(
            "auction_history.html",
            history=history
        )

    finally:
        cursor.close()
        conn.close()
        
@app.route("/admin")
def admin_dashboard():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT
                (SELECT COUNT(*) FROM Users) AS total_users,
                (SELECT COUNT(*) FROM Products) AS total_products,
                (SELECT COUNT(*) FROM Auctions) AS total_auctions,
                (SELECT COUNT(*) FROM Bids) AS total_bids,
                (SELECT COUNT(*) FROM Auctions
                    WHERE status = 'Closed') AS closed_auctions,
                (SELECT COUNT(*) FROM Payments
                    WHERE payment_status = 'Paid') AS paid_payments,
                (SELECT COALESCE(SUM(amount), 0)
                    FROM Payments
                    WHERE payment_status = 'Paid') AS total_paid
        """)

        stats = cursor.fetchone()

        cursor.execute("""
            SELECT
                p.product_name,
                COUNT(b.bid_id) AS bid_count,
                COALESCE(MAX(b.bid_amount), 0) AS highest_bid
            FROM Products p
            LEFT JOIN Auctions a
                ON p.product_id = a.product_id
            LEFT JOIN Bids b
                ON a.auction_id = b.auction_id
            GROUP BY p.product_id, p.product_name
            ORDER BY bid_count DESC, p.product_name
        """)

        product_stats = cursor.fetchall()

        return render_template(
            "admin.html",
            stats=stats,
            product_stats=product_stats
        )

    finally:
        cursor.close()
        conn.close()




@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out successfully.", "success")
    return redirect(url_for("home"))


if __name__ == "__main__":
    app.run(debug=True)
