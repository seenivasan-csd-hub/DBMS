from contextlib import closing
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps
from pathlib import Path
from threading import Lock
from time import monotonic
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import os
import re
import secrets
import uuid

import mysql.connector
from flask import (
    Flask, abort, flash, g, jsonify, redirect, render_template, request,
    session, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash


app = Flask(__name__)
IS_PRODUCTION = os.getenv("APP_ENV", "development").lower() == "production"
app.config.update(
    SECRET_KEY=os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "1" if IS_PRODUCTION else "0").lower()
    in {"1", "true", "yes"},
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    MAX_CONTENT_LENGTH=6 * 1024 * 1024,
)
if IS_PRODUCTION and not os.getenv("FLASK_SECRET_KEY"):
    raise RuntimeError("FLASK_SECRET_KEY must be set in production.")

try:
    APP_TIMEZONE = ZoneInfo(os.getenv("APP_TIMEZONE", "Asia/Kolkata"))
except ZoneInfoNotFoundError as exc:
    raise RuntimeError("APP_TIMEZONE must be a valid IANA timezone.") from exc

RATE_LIMITS = {}
RATE_LIMIT_LOCK = Lock()
ALLOWED_IMAGE_TYPES = {
    ".jpg": ("image/jpeg", b"\xff\xd8\xff"),
    ".jpeg": ("image/jpeg", b"\xff\xd8\xff"),
    ".png": ("image/png", b"\x89PNG\r\n\x1a\n"),
    ".webp": ("image/webp", b"RIFF"),
}


def get_db_connection():
    connection = mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "localhost"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        database=os.getenv("MYSQL_DATABASE", "auction_db"),
        connection_timeout=8,
    )
    # DATETIME values are stored and interpreted in the configured app timezone.
    cursor = connection.cursor()
    cursor.execute("SET time_zone = %s", (os.getenv("MYSQL_TIME_ZONE", "+05:30"),))
    cursor.close()
    return connection


def fetch_all(sql, params=()):
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(sql, params)
        return cursor.fetchall()
    finally:
        cursor.close()
        connection.close()


def fetch_one(sql, params=()):
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(sql, params)
        return cursor.fetchone()
    finally:
        cursor.close()
        connection.close()


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


app.jinja_env.globals["csrf_token"] = csrf_token


@app.template_filter("localtime")
def localtime(value, fmt="%d %b %Y, %I:%M %p"):
    if value is None:
        return "Not set"
    if isinstance(value, str):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=APP_TIMEZONE)
    return value.astimezone(APP_TIMEZONE).strftime(fmt)


@app.template_filter("datetime_iso")
def datetime_iso(value):
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=APP_TIMEZONE)
    return value.astimezone(APP_TIMEZONE).isoformat()


def load_user(user_id):
    return fetch_one(
        """SELECT user_id, name, email, role, is_active, created_at
           FROM Users WHERE user_id = %s""",
        (user_id,),
    )


@app.before_request
def load_current_user():
    g.user = None
    if request.endpoint == "static" or "user_id" not in session:
        return
    try:
        user = load_user(session["user_id"])
    except mysql.connector.Error:
        app.logger.exception("Could not load the current user")
        user = None
    if not user or not user["is_active"]:
        session.clear()
        return
    g.user = user
    session["user_role"] = user["role"]
    session["user_name"] = user["name"]
    session["user_email"] = user["email"]


@app.before_request
def protect_unsafe_requests():
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return
    expected = session.get("csrf_token", "")
    supplied = request.form.get("csrf_token", "") or request.headers.get("X-CSRF-Token", "")
    if not expected or not secrets.compare_digest(expected, supplied):
        abort(400, description="Your form expired. Refresh the page and try again.")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not getattr(g, "user", None):
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def customer_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if g.user["role"] == "admin":
            return redirect(url_for("admin_dashboard"))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if g.user["role"] != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def rate_limit(limit, seconds=60):
    """Small per-process guard for this single-instance college demo."""
    def decorate(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if request.method != "POST":
                return view(*args, **kwargs)
            key = (request.endpoint, request.remote_addr or "unknown")
            now = monotonic()
            with RATE_LIMIT_LOCK:
                attempts = [stamp for stamp in RATE_LIMITS.get(key, []) if now - stamp < seconds]
                if len(attempts) >= limit:
                    abort(429)
                attempts.append(now)
                RATE_LIMITS[key] = attempts
                if len(RATE_LIMITS) > 5000:
                    for old_key, stamps in list(RATE_LIMITS.items()):
                        if not stamps or now - stamps[-1] >= seconds:
                            RATE_LIMITS.pop(old_key, None)
            return view(*args, **kwargs)
        return wrapped
    return decorate


def settle_ended_auctions():
    """Close expired lots and record the winning bid/payment exactly once."""
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        connection.start_transaction()
        cursor.execute(
            """SELECT a.auction_id
               FROM Auctions a
               WHERE a.end_time IS NOT NULL AND a.end_time <= NOW()
                 AND (a.status <> 'Ended' OR (
                      EXISTS (SELECT 1 FROM Bids b WHERE b.auction_id = a.auction_id)
                      AND NOT EXISTS (SELECT 1 FROM Winners w WHERE w.auction_id = a.auction_id)
                 ))
               FOR UPDATE"""
        )
        expired = cursor.fetchall()
        for item in expired:
            auction_id = item["auction_id"]
            cursor.execute("UPDATE Auctions SET status = 'Ended' WHERE auction_id = %s", (auction_id,))
            cursor.execute(
                """SELECT user_id, bid_amount FROM Bids
                   WHERE auction_id = %s
                   ORDER BY bid_amount DESC, bid_time ASC, bid_id ASC LIMIT 1""",
                (auction_id,),
            )
            winning_bid = cursor.fetchone()
            if winning_bid:
                cursor.execute(
                    """INSERT INTO Winners (auction_id, user_id, winning_bid)
                       VALUES (%s, %s, %s)
                       ON DUPLICATE KEY UPDATE auction_id = VALUES(auction_id)""",
                    (auction_id, winning_bid["user_id"], winning_bid["bid_amount"]),
                )
                cursor.execute(
                    """INSERT INTO Payments (auction_id, user_id, amount, payment_status)
                       VALUES (%s, %s, %s, 'Pending')
                       ON DUPLICATE KEY UPDATE auction_id = VALUES(auction_id)""",
                    (auction_id, winning_bid["user_id"], winning_bid["bid_amount"]),
                )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


def auction_select(where="", order_by="a.auction_id DESC", limit=None, offset=0, params=(), include_inactive=False):
    sql = """SELECT a.auction_id, a.product_id, a.start_time, a.end_time,
                    a.min_increment, a.status,
                    p.product_name, p.description, p.starting_price, p.category,
                    p.image_url, p.image_source, p.seller_id,seller.name AS seller_name,
                    p.created_at AS product_created_at,
                    CASE WHEN a.start_time IS NOT NULL AND a.start_time > NOW() THEN 'Upcoming'
                         WHEN a.end_time IS NOT NULL AND a.end_time <= NOW() THEN 'Ended'
                         ELSE 'Live' END AS display_status,
                    COALESCE((SELECT MAX(b.bid_amount) FROM Bids b
                              WHERE b.auction_id = a.auction_id), 0) AS highest_bid,
                    (SELECT COUNT(*) FROM Bids b
                     WHERE b.auction_id = a.auction_id) AS bid_count,
                    GREATEST(p.starting_price, COALESCE((SELECT MAX(b.bid_amount)
                              FROM Bids b WHERE b.auction_id = a.auction_id), 0)) AS current_bid
             FROM Auctions a
             JOIN Products p ON p.product_id = a.product_id
             LEFT JOIN Users seller ON seller.user_id = p.seller_id
             WHERE """ + ("1=1 " if include_inactive else "p.is_active = 1 ")
    if where:
        sql += " AND " + where
    sql += " ORDER BY " + order_by
    query_params = list(params)
    if limit is not None:
        sql += " LIMIT %s OFFSET %s"
        query_params.extend([limit, offset])
    return fetch_all(sql, tuple(query_params))


def auction_card_data(auction):
    auction["current_bid"] = auction["highest_bid"] if auction["bid_count"] else auction["starting_price"]
    auction["minimum_next_bid"] = (
        auction["highest_bid"] + auction["min_increment"]
        if auction["bid_count"] else auction["starting_price"]
    )
    return auction


def get_categories():
    return fetch_all(
        """SELECT DISTINCT category FROM Products
           WHERE is_active = 1 AND category IS NOT NULL AND category <> ''
           ORDER BY category"""
    )


def safe_return_url(default_endpoint):
    candidate = request.referrer
    if candidate:
        parsed = urlparse(candidate)
        if parsed.scheme in {"http", "https"} and parsed.netloc == request.host:
            return candidate
    return url_for(default_endpoint)


@app.route("/api/auctions/schedules")
@login_required
def auction_schedules():
    requested_ids = request.args.getlist("id")
    try:
        auction_ids = list(dict.fromkeys(int(value) for value in requested_ids))
    except ValueError:
        return jsonify({"error": "Auction IDs must be integers."}), 400
    if len(auction_ids) > 100:
        return jsonify({"error": "Request at most 100 auction schedules."}), 400
    if not auction_ids:
        return jsonify({})

    placeholders = ",".join(["%s"] * len(auction_ids))
    schedules = fetch_all(
        f"""SELECT a.auction_id,a.start_time,a.end_time,
                   CASE WHEN a.start_time>NOW() THEN 'Upcoming'
                        WHEN a.end_time<=NOW() THEN 'Ended' ELSE 'Live' END AS status
            FROM Auctions a JOIN Products p ON p.product_id=a.product_id
            WHERE p.is_active=1 AND a.auction_id IN ({placeholders})""",
        tuple(auction_ids),
    )
    response = jsonify({
        str(item["auction_id"]): {
            "start_time": datetime_iso(item["start_time"]),
            "end_time": datetime_iso(item["end_time"]),
            "end_value": item["end_time"].strftime("%Y-%m-%dT%H:%M"),
            "closing_display": localtime(item["end_time"]),
            "status": item["status"],
        }
        for item in schedules
    })
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/")
def index():
    if not getattr(g, "user", None):
        return redirect(url_for("login"))
    if g.user["role"] == "admin":
        return redirect(url_for("admin_dashboard"))
    return redirect(url_for("home"))


@app.route("/register", methods=["GET", "POST"])
@rate_limit(8)
def register():
    if getattr(g, "user", None):
        return redirect(url_for("index"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        if not name or len(name) > 100:
            flash("Enter your name (up to 100 characters).", "error")
        elif not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or len(email) > 100:
            flash("Enter a valid email address.", "error")
        elif len(password) < 8:
            flash("Choose a password with at least 8 characters.", "error")
        elif password != confirm:
            flash("The passwords do not match.", "error")
        else:
            connection = get_db_connection()
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """INSERT INTO Users (name, email, password, role, is_active)
                       VALUES (%s, %s, %s, 'user', 1)""",
                    (name, email, generate_password_hash(password)),
                )
                connection.commit()
                user_id = cursor.lastrowid
                session.clear()
                session["user_id"] = user_id
                session.permanent = True
                flash("Your account is ready. Welcome to Bidwell!", "success")
                return redirect(url_for("home"))
            except mysql.connector.IntegrityError:
                connection.rollback()
                flash("An account already uses that email address.", "error")
            except mysql.connector.Error:
                connection.rollback()
                app.logger.exception("Registration failed")
                flash("We could not create your account. Please try again.", "error")
            finally:
                cursor.close()
                connection.close()
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
@rate_limit(10)
def login():
    if getattr(g, "user", None):
        return redirect(url_for("index"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        try:
            user = fetch_one(
                """SELECT user_id, name, email, password, role, is_active
                   FROM Users WHERE email = %s""",
                (email,),
            )
        except mysql.connector.Error:
            app.logger.exception("Login failed")
            flash("We could not reach the account service. Try again shortly.", "error")
            return render_template("login.html"), 503
        if user and user["is_active"] and check_password_hash(user["password"], password):
            session.clear()
            session["user_id"] = user["user_id"]
            session.permanent = True
            flash("Welcome back.", "success")
            if user["role"] == "admin":
                return redirect(url_for("admin_dashboard"))
            return redirect(url_for("home"))
        flash("Email or password is incorrect, or this account is disabled.", "error")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


@app.route("/home")
@customer_required
def home():
    settle_ended_auctions()
    live = auction_select("a.start_time <= NOW() AND a.end_time > NOW()", "a.end_time ASC", 6)
    recent = auction_select("1=1", "p.created_at DESC, a.auction_id DESC", 6)
    popular = auction_select("1=1", "bid_count DESC, a.auction_id DESC", 6)
    ending = auction_select("a.start_time <= NOW() AND a.end_time > NOW()", "a.end_time ASC", 4)
    counts = fetch_one(
        """SELECT
             (SELECT COUNT(*) FROM Auctions a JOIN Products p ON p.product_id=a.product_id
                WHERE p.is_active=1 AND a.start_time <= NOW() AND a.end_time > NOW()) AS live_count,
             (SELECT COUNT(*) FROM Products WHERE is_active=1) AS product_count,
             (SELECT COUNT(*) FROM Bids) AS bid_count"""
    )
    return render_template(
        "index.html",
        live_auctions=[auction_card_data(a) for a in live],
        recent_auctions=[auction_card_data(a) for a in recent],
        popular_auctions=[auction_card_data(a) for a in popular],
        ending_auctions=[auction_card_data(a) for a in ending],
        categories=get_categories(), counts=counts,
    )


@app.route("/auctions")
@customer_required
def browse():
    settle_ended_auctions()
    query = request.args.get("q", "").strip()[:100]
    category = request.args.get("category", "").strip()[:80]
    status = request.args.get("status", "").strip().title()
    sort = request.args.get("sort", "newest")
    page = max(1, request.args.get("page", 1, type=int) or 1)
    per_page = 9
    order_by = {
        "newest": "a.auction_id DESC",
        "ending": "a.end_time ASC",
        "popular": "bid_count DESC, a.auction_id DESC",
        "price": "current_bid DESC",
    }.get(sort, "a.auction_id DESC")
    conditions, params = [], []
    if query:
        conditions.append("(p.product_name LIKE %s OR p.description LIKE %s)")
        params.extend([f"%{query}%", f"%{query}%"])
    if category:
        conditions.append("p.category = %s")
        params.append(category)
    if status in {"Live", "Upcoming", "Ended"}:
        conditions.append(
            "(CASE WHEN a.start_time > NOW() THEN 'Upcoming' "
            "WHEN a.end_time <= NOW() THEN 'Ended' ELSE 'Live' END) = %s"
        )
        params.append(status)
    where = " AND ".join(conditions) or "1=1"
    count = fetch_one(
        "SELECT COUNT(*) AS total FROM Auctions a JOIN Products p "
        "ON p.product_id=a.product_id WHERE p.is_active=1 AND " + where,
        tuple(params),
    )["total"]
    auctions = auction_select(where, order_by, per_page, (page - 1) * per_page, tuple(params))
    return render_template(
        "browse.html", auctions=[auction_card_data(a) for a in auctions],
        categories=get_categories(), query=query, category=category,
        status=status, sort=sort, page=page,
        page_count=max(1, (count + per_page - 1) // per_page), total=count,
    )


@app.route("/auction/<int:auction_id>")
@login_required
def auction_detail(auction_id):
    settle_ended_auctions()
    auction = fetch_one(
        """SELECT a.auction_id, a.product_id, a.start_time, a.end_time,
                  a.min_increment, a.status, p.product_name, p.description,
                  p.starting_price, p.category, p.image_url, p.image_source,
                  p.seller_id,seller.name AS seller_name,
                  CASE WHEN a.start_time > NOW() THEN 'Upcoming'
                       WHEN a.end_time <= NOW() THEN 'Ended' ELSE 'Live' END AS display_status,
                  COALESCE(MAX(b.bid_amount), 0) AS highest_bid,
                  COUNT(b.bid_id) AS bid_count
           FROM Auctions a JOIN Products p ON p.product_id=a.product_id
           LEFT JOIN Users seller ON seller.user_id=p.seller_id
           LEFT JOIN Bids b ON b.auction_id=a.auction_id
           WHERE a.auction_id=%s AND (p.is_active=1 OR %s='admin')
           GROUP BY a.auction_id,a.product_id,a.start_time,a.end_time,a.min_increment,
                    a.status,p.product_name,p.description,p.starting_price,p.category,
                    p.image_url,p.image_source,p.seller_id,seller.name""",
        (auction_id, g.user["role"]),
    )
    if not auction:
        abort(404)
    auction_card_data(auction)
    bids = fetch_all(
        """SELECT b.bid_id, b.bid_amount, b.bid_time, u.name AS bidder_name
           FROM Bids b JOIN Users u ON u.user_id=b.user_id
           WHERE b.auction_id=%s ORDER BY b.bid_amount DESC,b.bid_time ASC,b.bid_id ASC""",
        (auction_id,),
    )
    watch = fetch_one(
        "SELECT watchlist_id FROM Watchlist WHERE user_id=%s AND auction_id=%s",
        (g.user["user_id"], auction_id),
    )
    participant = fetch_one(
        "SELECT bid_id FROM Bids WHERE user_id=%s AND auction_id=%s LIMIT 1",
        (g.user["user_id"], auction_id),
    )
    winner = fetch_one(
        """SELECT w.user_id,w.winning_bid,u.name AS winner_name
           FROM Winners w JOIN Users u ON u.user_id=w.user_id
           WHERE w.auction_id=%s""",
        (auction_id,),
    ) if auction["display_status"] == "Ended" else None
    if winner and g.user["role"] != "admin" and not participant:
        winner = None
    related = auction_select(
        "p.category = %s AND a.auction_id <> %s",
        "a.auction_id DESC", 4, 0, (auction["category"], auction_id),
    )
    return render_template(
        "auction_detail.html", auction=auction, bids=bids,
        is_watched=bool(watch), winner=winner,
        related=[auction_card_data(a) for a in related],
    )


@app.route("/bid", methods=["POST"])
@customer_required
@rate_limit(30)
def place_bid():
    try:
        auction_id = int(request.form.get("auction_id", ""))
        amount = Decimal(request.form.get("bid_amount", ""))
        if not amount.is_finite() or amount <= 0:
            raise ValueError("Enter a valid positive bid.")
    except (ValueError, InvalidOperation):
        flash("Enter a valid positive bid amount.", "error")
        return redirect(safe_return_url("browse"))

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        connection.start_transaction()
        cursor.execute(
            """SELECT a.auction_id, a.start_time, a.end_time, a.min_increment,
                      a.status, p.starting_price, NOW() AS server_now
               FROM Auctions a JOIN Products p ON p.product_id=a.product_id
               WHERE a.auction_id=%s AND p.is_active=1 FOR UPDATE""",
            (auction_id,),
        )
        auction = cursor.fetchone()
        if not auction:
            raise ValueError("That auction could not be found.")
        now = auction["server_now"]
        if auction["start_time"] and auction["start_time"] > now:
            raise ValueError("This auction has not started yet.")
        if not auction["end_time"] or auction["end_time"] <= now:
            raise ValueError("This auction has ended.")
        cursor.execute("SELECT MAX(bid_amount) AS highest FROM Bids WHERE auction_id=%s", (auction_id,))
        current = cursor.fetchone()["highest"]
        minimum = auction["starting_price"] if current is None else current + auction["min_increment"]
        if amount < minimum:
            raise ValueError(f"The next acceptable bid is ₹{minimum:.2f} or higher.")
        cursor.execute(
            "INSERT INTO Bids (auction_id, user_id, bid_amount) VALUES (%s,%s,%s)",
            (auction_id, g.user["user_id"], amount),
        )
        connection.commit()
        flash("Your bid is in. Good luck!", "success")
    except ValueError as exc:
        connection.rollback()
        flash(str(exc), "error")
    except mysql.connector.Error:
        connection.rollback()
        app.logger.exception("Bid submission failed")
        flash("We could not save your bid. Please try again.", "error")
    finally:
        cursor.close()
        connection.close()
    return redirect(url_for("auction_detail", auction_id=auction_id))


@app.route("/watchlist")
@customer_required
def watchlist():
    auctions = auction_select(
        "EXISTS (SELECT 1 FROM Watchlist w WHERE w.user_id=%s AND w.auction_id=a.auction_id)",
        "a.end_time ASC", 100, 0, (g.user["user_id"],),
    )
    return render_template("watchlist.html", auctions=[auction_card_data(a) for a in auctions])


@app.route("/watchlist/<int:auction_id>/toggle", methods=["POST"])
@customer_required
def toggle_watchlist(auction_id):
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT watchlist_id FROM Watchlist WHERE user_id=%s AND auction_id=%s",
            (g.user["user_id"], auction_id),
        )
        found = cursor.fetchone()
        if found:
            cursor.execute("DELETE FROM Watchlist WHERE watchlist_id=%s", (found[0],))
            flash("Removed from your watchlist.", "success")
        else:
            cursor.execute(
                "INSERT INTO Watchlist (user_id, auction_id) VALUES (%s,%s)",
                (g.user["user_id"], auction_id),
            )
            flash("Added to your watchlist.", "success")
        connection.commit()
    except mysql.connector.Error:
        connection.rollback()
        app.logger.exception("Watchlist update failed")
        flash("We could not update your watchlist.", "error")
    finally:
        cursor.close()
        connection.close()
    return redirect(safe_return_url("watchlist"))


@app.route("/my-bids")
@customer_required
def my_bids():
    bids = fetch_all(
        """SELECT b.bid_id,b.bid_amount,b.bid_time,a.auction_id,a.start_time,a.end_time,
                  p.product_name,p.image_url,p.category,p.starting_price,
                  (SELECT MAX(all_bids.bid_amount) FROM Bids all_bids
                   WHERE all_bids.auction_id=a.auction_id) AS highest_bid,
                  (SELECT COUNT(*) FROM Bids all_bids
                   WHERE all_bids.auction_id=a.auction_id) AS bid_count,
                  CASE WHEN a.start_time > NOW() THEN 'Upcoming'
                       WHEN a.end_time <= NOW() THEN 'Ended' ELSE 'Live' END AS display_status
           FROM Bids b JOIN Auctions a ON a.auction_id=b.auction_id
           JOIN Products p ON p.product_id=a.product_id
           WHERE b.user_id=%s ORDER BY b.bid_time DESC""",
        (g.user["user_id"],),
    )
    for item in bids:
        item["is_winning"] = item["bid_amount"] == item["highest_bid"]
    return render_template("my_bids.html", bids=bids)


@app.route("/profile", methods=["GET", "POST"])
@customer_required
def profile():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        if not name or len(name) > 100:
            flash("Enter your name (up to 100 characters).", "error")
        elif not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or len(email) > 100:
            flash("Enter a valid email address.", "error")
        else:
            connection = get_db_connection()
            cursor = connection.cursor()
            try:
                cursor.execute("UPDATE Users SET name=%s,email=%s WHERE user_id=%s", (name,email,g.user["user_id"]))
                connection.commit()
                session["user_name"] = name
                session["user_email"] = email
                flash("Your profile has been updated.", "success")
                return redirect(url_for("profile"))
            except mysql.connector.IntegrityError:
                connection.rollback()
                flash("That email address is already in use.", "error")
            except mysql.connector.Error:
                connection.rollback()
                app.logger.exception("Profile update failed")
                flash("We could not update your profile.", "error")
            finally:
                cursor.close()
                connection.close()
    return render_template("profile.html", profile_user=g.user)


@app.route("/auction-history")
@login_required
def auction_history():
    settle_ended_auctions()
    history = fetch_all(
        """SELECT a.auction_id,p.product_name,a.start_time,a.end_time,
                  CASE WHEN a.start_time > NOW() THEN 'Upcoming'
                       WHEN a.end_time <= NOW() THEN 'Ended' ELSE 'Live' END AS status,
                  u.name AS winner_name,w.winning_bid,
                  COALESCE(pay.payment_status,'Not Created') AS payment_status,pay.payment_id
           FROM Auctions a JOIN Products p ON p.product_id=a.product_id
           LEFT JOIN Winners w ON w.auction_id=a.auction_id
           LEFT JOIN Users u ON u.user_id=w.user_id
           LEFT JOIN Payments pay ON pay.auction_id=a.auction_id
           WHERE (%s = 'admin' OR EXISTS (
               SELECT 1 FROM Bids mine
               WHERE mine.auction_id=a.auction_id AND mine.user_id=%s
           ))
           ORDER BY a.auction_id DESC""",
        (g.user["role"], g.user["user_id"]),
    )
    return render_template("auction_history.html", history=history)


@app.route("/admin")
@admin_required
def admin_dashboard():
    settle_ended_auctions()
    stats = fetch_one(
        """SELECT
           (SELECT COUNT(*) FROM Users WHERE role='user') AS total_users,
           (SELECT COUNT(*) FROM Products WHERE is_active=1) AS total_products,
           (SELECT COUNT(*) FROM Auctions) AS total_auctions,
           (SELECT COUNT(*) FROM Auctions WHERE start_time<=NOW() AND end_time>NOW()) AS live_auctions,
           (SELECT COUNT(*) FROM Auctions WHERE start_time>NOW()) AS upcoming_auctions,
           (SELECT COUNT(*) FROM Auctions WHERE end_time<=NOW()) AS ended_auctions,
           (SELECT COUNT(*) FROM Bids) AS total_bids,
           (SELECT COUNT(*) FROM Bids WHERE bid_time>=CURDATE()) AS bids_today,
           (SELECT COUNT(DISTINCT user_id) FROM Bids) AS unique_bidders,
           (SELECT COUNT(*) FROM Auctions WHERE end_time>NOW() AND end_time<=DATE_ADD(NOW(),INTERVAL 24 HOUR)) AS ending_soon,
           (SELECT COALESCE(SUM(amount),0) FROM Payments WHERE payment_status='Paid') AS total_paid,
           (SELECT COUNT(*) FROM Payments WHERE payment_status='Paid') AS paid_payments"""
    )
    recent_users = fetch_all(
        "SELECT user_id,name,email,role,created_at FROM Users ORDER BY created_at DESC LIMIT 6"
    )
    recent_bids = fetch_all(
        """SELECT b.bid_id,b.bid_amount,b.bid_time,u.name AS bidder_name,
                  p.product_name,a.auction_id
           FROM Bids b JOIN Users u ON u.user_id=b.user_id
           JOIN Auctions a ON a.auction_id=b.auction_id
           JOIN Products p ON p.product_id=a.product_id
           ORDER BY b.bid_time DESC LIMIT 8"""
    )
    ending_soon = auction_select(
        "a.end_time > NOW() AND a.end_time <= DATE_ADD(NOW(), INTERVAL 24 HOUR)",
        "a.end_time ASC", 6,
    )
    bids_by_day = fetch_all(
        """SELECT DATE(bid_time) AS day,COUNT(*) AS total FROM Bids
           WHERE bid_time >= DATE_SUB(CURDATE(),INTERVAL 6 DAY)
           GROUP BY DATE(bid_time) ORDER BY day"""
    )
    regs_by_day = fetch_all(
        """SELECT DATE(created_at) AS day,COUNT(*) AS total FROM Users
           WHERE role='user' AND created_at >= DATE_SUB(CURDATE(),INTERVAL 6 DAY)
           GROUP BY DATE(created_at) ORDER BY day"""
    )
    popular_products = fetch_all(
        """SELECT p.product_name,COUNT(b.bid_id) AS bid_count
           FROM Products p LEFT JOIN Auctions a ON a.product_id=p.product_id
           LEFT JOIN Bids b ON b.auction_id=a.auction_id
           WHERE p.is_active=1 GROUP BY p.product_id,p.product_name
           ORDER BY bid_count DESC,p.product_name LIMIT 6"""
    )
    popular_max = max((row["bid_count"] for row in popular_products), default=0) or 1
    for row in popular_products:
        row["height"] = max(6, int(row["bid_count"] * 100 / popular_max)) if row["bid_count"] else 4
    auction_activity = fetch_all(
        """SELECT a.auction_id,p.product_name,COUNT(b.bid_id) AS bid_count
           FROM Auctions a JOIN Products p ON p.product_id=a.product_id
           LEFT JOIN Bids b ON b.auction_id=a.auction_id
           GROUP BY a.auction_id,p.product_name
           ORDER BY bid_count DESC,a.auction_id DESC LIMIT 6"""
    )
    activity_max = max((row["bid_count"] for row in auction_activity), default=0) or 1
    for row in auction_activity:
        row["height"] = max(6, int(row["bid_count"] * 100 / activity_max)) if row["bid_count"] else 4
    status_counts = {
        "Live": stats["live_auctions"],
        "Upcoming": stats["upcoming_auctions"],
        "Ended": stats["ended_auctions"],
    }
    return render_template(
        "admin.html", stats=stats, recent_users=recent_users,
        recent_bids=recent_bids, ending_soon=[auction_card_data(a) for a in ending_soon],
        bid_chart=build_week_chart(bids_by_day),
        registration_chart=build_week_chart(regs_by_day),
        popular_products=popular_products, status_counts=status_counts,
        auction_activity=auction_activity,
    )


def build_week_chart(rows):
    by_day = {row["day"]: row["total"] for row in rows}
    today = datetime.now(APP_TIMEZONE).date()
    values = []
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        values.append({"label": day.strftime("%a"), "total": by_day.get(day, 0)})
    maximum = max((item["total"] for item in values), default=0) or 1
    for item in values:
        item["height"] = max(6, int(item["total"] * 100 / maximum)) if item["total"] else 4
    return values


@app.route("/admin/users")
@admin_required
def admin_users():
    query = request.args.get("q", "").strip()[:100]
    page = max(1, request.args.get("page", 1, type=int) or 1)
    per_page = 20
    where, params = "role='user'", []
    if query:
        where += " AND (name LIKE %s OR email LIKE %s)"
        params.extend([f"%{query}%", f"%{query}%"])
    total = fetch_one(f"SELECT COUNT(*) AS total FROM Users WHERE {where}", tuple(params))["total"]
    users = fetch_all(
        f"""SELECT u.user_id,u.name,u.email,u.role,u.is_active,u.created_at,
                   COUNT(b.bid_id) AS bid_count
            FROM Users u LEFT JOIN Bids b ON b.user_id=u.user_id
            WHERE {where} GROUP BY u.user_id,u.name,u.email,u.role,u.is_active,u.created_at
            ORDER BY u.created_at DESC LIMIT %s OFFSET %s""",
        tuple(params + [per_page, (page - 1) * per_page]),
    )
    return render_template(
        "admin_users.html", users=users, query=query, page=page,
        page_count=max(1, (total + per_page - 1) // per_page), total=total,
    )


@app.route("/admin/users/<int:user_id>/toggle", methods=["POST"])
@admin_required
def toggle_user(user_id):
    if user_id == g.user["user_id"]:
        flash("You cannot disable your own administrator account.", "error")
        return redirect(url_for("admin_users"))
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        connection.start_transaction()
        cursor.execute("SELECT role,is_active FROM Users WHERE user_id=%s FOR UPDATE", (user_id,))
        target = cursor.fetchone()
        if not target or target["role"] == "admin":
            raise ValueError("Administrator accounts cannot be disabled here.")
        cursor.execute("UPDATE Users SET is_active=%s WHERE user_id=%s", (0 if target["is_active"] else 1, user_id))
        connection.commit()
        flash("User account status updated.", "success")
    except ValueError as exc:
        connection.rollback()
        flash(str(exc), "error")
    except mysql.connector.Error:
        connection.rollback()
        app.logger.exception("User status update failed")
        flash("We could not update this account.", "error")
    finally:
        cursor.close()
        connection.close()
    return redirect(url_for("admin_users"))


def validate_image_url(value):
    value = value.strip()
    if not value:
        return None
    if value.startswith("/static/uploads/") and ".." not in value:
        return value
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("Use an HTTPS image URL or upload a JPG, PNG, or WebP image.")
    return value


def save_product_image(upload):
    if not upload or not upload.filename:
        return None
    filename = upload.filename
    extension = Path(filename).suffix.lower()
    spec = ALLOWED_IMAGE_TYPES.get(extension)
    data = upload.read(5 * 1024 * 1024 + 1)
    if not spec or len(data) > 5 * 1024 * 1024:
        raise ValueError("Image must be a JPG, PNG, or WebP file under 5 MB.")
    mime, signature = spec
    if not data.startswith(signature) or (mime == "image/webp" and data[8:12] != b"WEBP"):
        raise ValueError("The uploaded file does not match its image type.")
    stored_name = f"{uuid.uuid4().hex}{extension}"
    upload_dir = Path(app.static_folder) / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / stored_name).write_bytes(data)
    return f"/static/uploads/{stored_name}"


def product_form_values(existing=None):
    name = request.form.get("product_name", "").strip()
    description = request.form.get("description", "").strip()
    category = request.form.get("category", "").strip()
    try:
        price = Decimal(request.form.get("starting_price", ""))
        if not price.is_finite() or price <= 0 or price > Decimal("99999999.99"):
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        raise ValueError("Enter a valid starting price.")
    if existing and price != Decimal(existing["starting_price"]):
        placed_bid = fetch_one(
            """SELECT b.bid_id FROM Bids b JOIN Auctions a ON a.auction_id=b.auction_id
               WHERE a.product_id=%s LIMIT 1""",
            (existing["product_id"],),
        )
        if placed_bid:
            raise ValueError("Starting price cannot change after bids have been placed.")
    if not name or len(name) > 100:
        raise ValueError("Product name is required and must be 100 characters or fewer.")
    if len(description) > 255:
        raise ValueError("Description must be 255 characters or fewer.")
    if not category or len(category) > 80:
        raise ValueError("Choose a category up to 80 characters long.")
    image_url = validate_image_url(request.form.get("image_url", ""))
    uploaded = save_product_image(request.files.get("image_file"))
    if uploaded:
        image_url = uploaded
    elif existing and not image_url:
        image_url = existing["image_url"]
    source = request.form.get("image_source", "").strip()[:500] or None
    if source:
        source_parts = urlparse(source)
        if source_parts.scheme != "https" or not source_parts.netloc:
            raise ValueError("Image credit must be an HTTPS source URL.")
    if uploaded:
        source = None
    return name, description or None, category, price, image_url, source


@app.route("/admin/products", methods=["GET", "POST"])
@admin_required
def admin_products():
    if request.method == "POST":
        try:
            values = product_form_values()
            connection = get_db_connection()
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """INSERT INTO Products
                       (product_name,description,category,starting_price,image_url,image_source,seller_id,is_active)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,1)""",
                    values + (g.user["user_id"],),
                )
                connection.commit()
                flash("Product added. Create an auction for it when you are ready.", "success")
            except mysql.connector.Error:
                connection.rollback()
                app.logger.exception("Product creation failed")
                flash("We could not save that product.", "error")
            finally:
                cursor.close()
                connection.close()
            return redirect(url_for("admin_products"))
        except ValueError as exc:
            flash(str(exc), "error")
    query = request.args.get("q", "").strip()[:100]
    where, params = "", []
    if query:
        where = "WHERE p.product_name LIKE %s OR p.category LIKE %s"
        params = [f"%{query}%", f"%{query}%"]
    products = fetch_all(
        f"""SELECT p.product_id,p.product_name,p.description,p.starting_price,p.category,
                   p.image_url,p.image_source,p.is_active,p.created_at,
                   a.auction_id,a.start_time,a.end_time,
                   CASE WHEN a.auction_id IS NULL THEN NULL
                        WHEN a.start_time>NOW() THEN 'Upcoming'
                        WHEN a.end_time<=NOW() THEN 'Ended' ELSE 'Live' END AS auction_status
            FROM Products p
            LEFT JOIN Auctions a ON a.auction_id=(
                SELECT current_auction.auction_id FROM Auctions current_auction
                WHERE current_auction.product_id=p.product_id
                ORDER BY (current_auction.end_time>NOW()) DESC,
                         current_auction.auction_id DESC
                LIMIT 1
            )
            {where} ORDER BY p.created_at DESC""", tuple(params)
    )
    return render_template(
        "admin_products.html", products=products, query=query,
        now_local=datetime.now(APP_TIMEZONE).replace(second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M"),
    )


@app.route("/admin/products/<int:product_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_product(product_id):
    existing = fetch_one("SELECT * FROM Products WHERE product_id=%s", (product_id,))
    if not existing:
        abort(404)
    if request.method == "POST":
        try:
            values = product_form_values(existing)
            connection = get_db_connection()
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """UPDATE Products SET product_name=%s,description=%s,category=%s,
                       starting_price=%s,image_url=%s,image_source=%s WHERE product_id=%s""",
                    values + (product_id,),
                )
                connection.commit()
                flash("Product updated.", "success")
                return redirect(url_for("admin_products"))
            except mysql.connector.Error:
                connection.rollback()
                app.logger.exception("Product update failed")
                flash("We could not update this product.", "error")
            finally:
                cursor.close()
                connection.close()
        except ValueError as exc:
            flash(str(exc), "error")
    return render_template("admin_product_form.html", product=existing, editing=True)


@app.route("/admin/products/<int:product_id>/archive", methods=["POST"])
@admin_required
def archive_product(product_id):
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """SELECT COUNT(*) FROM Auctions
               WHERE product_id=%s AND end_time>NOW()""",
            (product_id,),
        )
        if cursor.fetchone()[0]:
            connection.rollback()
            flash("This product has a live or upcoming auction. Archive it after bidding closes.", "error")
            return redirect(url_for("admin_products"))
        cursor.execute("UPDATE Products SET is_active=0 WHERE product_id=%s", (product_id,))
        connection.commit()
        flash("Product archived. Its auction and bid history remain available.", "success")
    except mysql.connector.Error:
        connection.rollback()
        app.logger.exception("Product archival failed")
        flash("We could not archive this product.", "error")
    finally:
        cursor.close()
        connection.close()
    return redirect(url_for("admin_products"))


@app.route("/admin/products/<int:product_id>/restore", methods=["POST"])
@admin_required
def restore_product(product_id):
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("UPDATE Products SET is_active=1 WHERE product_id=%s", (product_id,))
        connection.commit()
        flash("Product restored.", "success")
    except mysql.connector.Error:
        connection.rollback()
        app.logger.exception("Product restore failed")
        flash("We could not restore this product.", "error")
    finally:
        cursor.close()
        connection.close()
    return redirect(url_for("admin_products"))


@app.route("/admin/auctions", methods=["GET", "POST"])
@admin_required
def admin_auctions():
    if request.method == "POST":
        try:
            product_id = int(request.form.get("product_id", ""))
            start = datetime.fromisoformat(request.form.get("start_time", ""))
            end = datetime.fromisoformat(request.form.get("end_time", ""))
            increment = Decimal(request.form.get("min_increment", "1"))
            if end <= start:
                raise ValueError("Auction end time must be after its start time.")
            if start < datetime.now(APP_TIMEZONE).replace(tzinfo=None):
                raise ValueError("Auction start time must be now or later.")
            if not increment.is_finite() or increment <= 0 or increment > Decimal("99999999.99"):
                raise ValueError("Minimum bid increment must be greater than zero.")
            product = fetch_one("SELECT product_id FROM Products WHERE product_id=%s AND is_active=1", (product_id,))
            if not product:
                raise ValueError("Choose an active product.")
            overlapping = fetch_one(
                "SELECT auction_id FROM Auctions WHERE product_id=%s AND end_time>NOW() LIMIT 1",
                (product_id,),
            )
            if overlapping:
                raise ValueError("This product already has a live or upcoming auction.")
            connection = get_db_connection()
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """INSERT INTO Auctions (product_id,start_time,end_time,status,min_increment)
                       VALUES (%s,%s,%s,'Active',%s)""",
                    (product_id, start, end, increment),
                )
                connection.commit()
                flash("Auction created.", "success")
                return redirect(url_for("admin_auctions"))
            except mysql.connector.Error:
                connection.rollback()
                app.logger.exception("Auction creation failed")
                flash("We could not create that auction.", "error")
            finally:
                cursor.close()
                connection.close()
        except (ValueError, InvalidOperation) as exc:
            flash(str(exc) or "Enter valid auction details.", "error")
    query = request.args.get("q", "").strip()[:100]
    status = request.args.get("status", "").strip().title()
    page = max(1, request.args.get("page", 1, type=int) or 1)
    per_page = 30
    conditions, params = [], []
    if query:
        conditions.append("p.product_name LIKE %s")
        params.append(f"%{query}%")
    if status in {"Live", "Upcoming", "Ended"}:
        conditions.append(
            "(CASE WHEN a.start_time>NOW() THEN 'Upcoming' "
            "WHEN a.end_time<=NOW() THEN 'Ended' ELSE 'Live' END)=%s"
        )
        params.append(status)
    where = " AND ".join(conditions) or "1=1"
    total = fetch_one(
        "SELECT COUNT(*) AS total FROM Auctions a JOIN Products p "
        "ON p.product_id=a.product_id WHERE " + where,
        tuple(params),
    )["total"]
    auctions = auction_select(
        where, "a.auction_id DESC", per_page, (page - 1) * per_page,
        tuple(params), include_inactive=True,
    )
    products = fetch_all("SELECT product_id,product_name,starting_price FROM Products WHERE is_active=1 ORDER BY product_name")
    return render_template(
        "admin_auctions.html", auctions=[auction_card_data(a) for a in auctions],
        products=products, query=query, status=status, page=page, total=total,
        page_count=max(1, (total + per_page - 1) // per_page),
    )


@app.route("/admin/auctions/<int:auction_id>/edit-time", methods=["GET", "POST"])
@admin_required
def edit_auction_time(auction_id):
    auction_query = """SELECT a.auction_id,p.product_name,a.start_time,a.end_time,
                              CASE WHEN a.start_time>NOW() THEN 'Upcoming'
                                   WHEN a.end_time<=NOW() THEN 'Ended' ELSE 'Live' END AS status,
                              NOW() AS server_now
                       FROM Auctions a JOIN Products p ON p.product_id=a.product_id
                       WHERE a.auction_id=%s"""
    auction = fetch_one(auction_query, (auction_id,))
    if not auction:
        abort(404)

    closing_value = auction["end_time"].strftime("%Y-%m-%dT%H:%M") if auction["end_time"] else ""
    if request.method == "POST":
        modal_request = request.form.get("response_mode") == "modal"
        closing_value = request.form.get("end_time", "").strip()
        try:
            new_end = datetime.fromisoformat(closing_value)
            if new_end.tzinfo is not None:
                new_end = None
        except ValueError:
            new_end = None
        if new_end is None:
            message = "Choose a valid closing date and time."
            if modal_request:
                return jsonify({"error": message}), 400
            flash(message, "error")
        else:
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)
            try:
                connection.start_transaction()
                cursor.execute(
                    """SELECT start_time,end_time
                       FROM Auctions WHERE auction_id=%s FOR UPDATE""",
                    (auction_id,),
                )
                current = cursor.fetchone()
                if not current:
                    abort(404)
                cursor.execute("SELECT NOW() AS server_now")
                current["server_now"] = cursor.fetchone()["server_now"]
                if current["end_time"] <= current["server_now"]:
                    raise ValueError("This auction has already ended and its schedule cannot be changed.")
                if new_end <= current["server_now"]:
                    raise ValueError("The new closing time must be in the future.")
                if new_end <= current["start_time"]:
                    raise ValueError("The closing time must be later than the auction start time.")
                cursor.execute(
                    "UPDATE Auctions SET end_time=%s WHERE auction_id=%s",
                    (new_end, auction_id),
                )
                connection.commit()
                if modal_request:
                    return jsonify({
                        "auction_id": auction_id,
                        "end_time": datetime_iso(new_end),
                        "end_value": new_end.strftime("%Y-%m-%dT%H:%M"),
                        "closing_display": localtime(new_end),
                        "status": "Upcoming" if current["start_time"] > current["server_now"] else "Live",
                    })
                flash("Auction closing time updated.", "success")
                return redirect(url_for("admin_auctions"))
            except ValueError as exc:
                connection.rollback()
                if modal_request:
                    return jsonify({"error": str(exc)}), 400
                flash(str(exc), "error")
            except mysql.connector.Error:
                connection.rollback()
                app.logger.exception("Auction closing time update failed")
                if modal_request:
                    return jsonify({"error": "We could not update this auction's closing time."}), 500
                flash("We could not update this auction's closing time.", "error")
            finally:
                cursor.close()
                connection.close()
            auction = fetch_one(auction_query, (auction_id,))
            if not auction:
                abort(404)

    if auction["end_time"] <= auction["server_now"]:
        flash("This auction has already ended and its schedule cannot be changed.", "error")
        return redirect(url_for("admin_auctions"))
    return render_template(
        "admin_auction_time.html", auction=auction,
        closing_value=closing_value,
        min_closing=auction["server_now"].strftime("%Y-%m-%dT%H:%M"),
    )


@app.route("/admin/bids")
@admin_required
def admin_bids():
    query = request.args.get("q", "").strip()[:100]
    page = max(1, request.args.get("page", 1, type=int) or 1)
    per_page = 30
    where, params = "", []
    if query:
        where = "WHERE p.product_name LIKE %s OR u.name LIKE %s OR u.email LIKE %s"
        params = [f"%{query}%", f"%{query}%", f"%{query}%"]
    total = fetch_one(
        "SELECT COUNT(*) AS total FROM Bids b JOIN Users u ON u.user_id=b.user_id "
        "JOIN Auctions a ON a.auction_id=b.auction_id JOIN Products p ON p.product_id=a.product_id " + where,
        tuple(params),
    )["total"]
    bids = fetch_all(
        f"""SELECT b.bid_id,b.bid_amount,b.bid_time,u.name AS bidder_name,u.email,
                   p.product_name,a.auction_id,a.start_time,a.end_time,
                   (SELECT MAX(b2.bid_amount) FROM Bids b2 WHERE b2.auction_id=a.auction_id) AS highest_bid,
                   CASE WHEN a.start_time>NOW() THEN 'Upcoming'
                        WHEN a.end_time<=NOW() THEN 'Ended' ELSE 'Live' END AS status
            FROM Bids b JOIN Users u ON u.user_id=b.user_id
            JOIN Auctions a ON a.auction_id=b.auction_id
            JOIN Products p ON p.product_id=a.product_id {where}
            ORDER BY b.bid_time DESC LIMIT %s OFFSET %s""",
        tuple(params + [per_page, (page - 1) * per_page]),
    )
    return render_template(
        "admin_bids.html", bids=bids, query=query, page=page,
        page_count=max(1, (total + per_page - 1) // per_page), total=total,
    )


@app.route("/mark-paid/<int:payment_id>", methods=["POST"])
@admin_required
def mark_paid(payment_id):
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """UPDATE Payments SET payment_status='Paid',payment_date=NOW()
               WHERE payment_id=%s AND payment_status='Pending'""",
            (payment_id,),
        )
        if cursor.rowcount == 1:
            connection.commit()
            flash("Payment marked as paid.", "success")
        else:
            connection.rollback()
            flash("Payment not found or already processed.", "error")
    except mysql.connector.Error:
        connection.rollback()
        app.logger.exception("Payment update failed")
        flash("We could not update payment status.", "error")
    finally:
        cursor.close()
        connection.close()
    return redirect(safe_return_url("admin_dashboard"))


@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(413)
@app.errorhandler(429)
def handle_http_error(error):
    code = getattr(error, "code", 500)
    return render_template("error.html", code=code, message=getattr(error, "description", "Something went wrong.")), code


if __name__ == "__main__":
    app.run(
        debug=os.getenv("FLASK_DEBUG", "0").lower() in {"1", "true", "yes"},
        host=os.getenv("FLASK_HOST", "127.0.0.1"),
        port=int(os.getenv("FLASK_PORT", "5000")),
    )
