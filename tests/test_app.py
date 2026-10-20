"""End-to-end checks against a disposable MySQL database."""

import os
import re
import uuid
import unittest
from datetime import datetime, timedelta
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import mysql.connector


ROOT = Path(__file__).resolve().parents[1]
TEST_DATABASE = "auction_test_" + uuid.uuid4().hex[:12]
os.environ.setdefault("MYSQL_HOST", "localhost")
os.environ.setdefault("MYSQL_PORT", "3306")
os.environ.setdefault("MYSQL_USER", "root")
os.environ.setdefault("ADMIN_EMAIL", "vasan1@gmail.com")
os.environ.setdefault("ADMIN_PASSWORD", "vasan@1")
os.environ["MYSQL_DATABASE"] = TEST_DATABASE


def mysql_connection(database=None):
    options = {
        "host": os.getenv("MYSQL_HOST", "localhost"),
        "port": int(os.getenv("MYSQL_PORT", "3306")),
        "user": os.getenv("MYSQL_USER", "root"),
        "password": os.getenv("MYSQL_PASSWORD", ""),
    }
    if database:
        options["database"] = database
    return mysql.connector.connect(**options)


def initialize_database():
    admin_connection = mysql_connection()
    admin_cursor = admin_connection.cursor()
    try:
        admin_cursor.execute(f"CREATE DATABASE `{TEST_DATABASE}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        admin_connection.commit()
    finally:
        admin_cursor.close()
        admin_connection.close()

    schema = (ROOT / "database.sql").read_text(encoding="utf-8")
    schema = schema.replace("USE auction_db;", f"USE `{TEST_DATABASE}`;")
    statements = [
        line for line in schema.splitlines()
        if not line.lstrip().startswith("--")
    ]
    connection = mysql_connection(TEST_DATABASE)
    cursor = connection.cursor()
    try:
        for statement in "\n".join(statements).split(";"):
            if statement.strip():
                cursor.execute(statement)
        connection.commit()
    finally:
        cursor.close()
        connection.close()

    import seed_admin
    seed_admin.main()
    seed_sql = (ROOT / "seed_products.sql").read_text(encoding="utf-8")
    seed_sql = seed_sql.replace("USE auction_db;", f"USE `{TEST_DATABASE}`;")
    seed_sql = "\n".join(line for line in seed_sql.splitlines() if not line.lstrip().startswith("--"))
    connection = mysql_connection(TEST_DATABASE)
    cursor = connection.cursor()
    try:
        for statement in seed_sql.split(";"):
            if statement.strip():
                cursor.execute(statement)
        connection.commit()
        for statement in seed_sql.split(";"):
            if statement.strip():
                cursor.execute(statement)
        connection.commit()
    finally:
        cursor.close()
        connection.close()

    import seed_products

    seed_products.main()


initialize_database()

from app import APP_TIMEZONE, app as flask_app  # noqa: E402
from werkzeug.security import check_password_hash  # noqa: E402


class AuctionFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        cls.connection = mysql_connection(TEST_DATABASE)
        cls.connection.autocommit = True
        cls.cursor = cls.connection.cursor(dictionary=True)
        cls.cursor.execute("SELECT user_id FROM Users WHERE email=%s", (os.environ["ADMIN_EMAIL"].lower(),))
        cls.admin_id = cls.cursor.fetchone()["user_id"]
        cls.cursor.execute("""INSERT INTO Products
            (product_name,description,starting_price,category,seller_id)
            VALUES ('Concurrent Bid Test Lot','Temporary test fixture',1000,'Testing',%s)""", (cls.admin_id,))
        cls.product_id = cls.cursor.lastrowid
        cls.cursor.execute("""INSERT INTO Auctions
            (product_id,start_time,end_time,status,min_increment)
            VALUES (%s,DATE_SUB(NOW(),INTERVAL 1 MINUTE),DATE_ADD(NOW(),INTERVAL 1 HOUR),'Active',100)""", (cls.product_id,))
        cls.auction_id = cls.cursor.lastrowid
        cls.cursor.execute("""INSERT INTO Auctions
            (product_id,start_time,end_time,status,min_increment)
            VALUES (%s,DATE_ADD(NOW(),INTERVAL 1 HOUR),DATE_ADD(NOW(),INTERVAL 2 HOUR),'Active',100)""", (cls.product_id,))
        cls.upcoming_auction_id = cls.cursor.lastrowid
        cls.connection.commit()

    @classmethod
    def tearDownClass(cls):
        cls.cursor.close()
        cls.connection.close()
        connection = mysql_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(f"DROP DATABASE IF EXISTS `{TEST_DATABASE}`")
            connection.commit()
        finally:
            cursor.close()
            connection.close()

    @staticmethod
    def token(client, path):
        response = client.get(path)
        match = re.search(rb'name="csrf_token" value="([^"]+)"', response.data)
        if not match:
            raise AssertionError(f"No CSRF token found on {path} (HTTP {response.status_code})")
        return match.group(1).decode()

    @classmethod
    def register(cls, client, name, email, password):
        csrf = cls.token(client, "/register")
        response = client.post("/register", data={
            "csrf_token": csrf,
            "name": name,
            "email": email,
            "password": password,
            "confirm_password": password,
        })
        return response

    def test_admin_can_edit_live_auction_closing_time(self):
        self.cursor.execute(
            """INSERT INTO Auctions (product_id,start_time,end_time,status,min_increment)
               VALUES (%s,DATE_SUB(NOW(),INTERVAL 1 MINUTE),DATE_ADD(NOW(),INTERVAL 1 HOUR),'Active',100)""",
            (self.product_id,),
        )
        auction_id = self.cursor.lastrowid
        self.connection.commit()

        admin = flask_app.test_client()
        with admin.session_transaction() as session:
            session["user_id"] = self.admin_id
        edit_url = f"/admin/auctions/{auction_id}/edit-time"
        edit_page = admin.get(edit_url)
        self.assertEqual(edit_page.status_code, 200)
        self.assertIn(b"Concurrent Bid Test Lot", edit_page.data)
        self.assertIn(b"Current start time", edit_page.data)
        self.assertIn(b"Current closing time", edit_page.data)
        self.assertIn(b"Live", edit_page.data)
        admin_csrf = self.token(admin, edit_url)
        self.cursor.execute("SELECT end_time FROM Auctions WHERE auction_id=%s", (auction_id,))
        original_end = self.cursor.fetchone()["end_time"]

        extended_end = datetime.now(APP_TIMEZONE).replace(second=0, microsecond=0) + timedelta(hours=3)
        extended = admin.post(edit_url, data={
            "csrf_token": admin_csrf,
            "end_time": extended_end.strftime("%Y-%m-%dT%H:%M"),
        }, follow_redirects=True)
        self.assertEqual(extended.status_code, 200)
        self.assertIn(b"Auction closing time updated.", extended.data)
        self.cursor.execute("SELECT end_time FROM Auctions WHERE auction_id=%s", (auction_id,))
        self.assertEqual(self.cursor.fetchone()["end_time"], extended_end.replace(tzinfo=None))
        self.assertNotEqual(extended_end.replace(tzinfo=None), original_end)
        self.assertIn(b"Edit auction time", admin.get("/admin/auctions").data)
        schedule = admin.get(f"/api/auctions/schedules?id={auction_id}").get_json()[str(auction_id)]
        self.assertEqual(schedule["end_time"], extended_end.replace(tzinfo=APP_TIMEZONE).isoformat())
        detail_after_edit = admin.get(f"/auction/{auction_id}")
        self.assertIn(extended_end.strftime("%d %b %Y, %I:%M %p").encode(), detail_after_edit.data)
        self.assertIn(extended_end.replace(tzinfo=APP_TIMEZONE).isoformat().encode(), detail_after_edit.data)

        before_start = datetime.now(APP_TIMEZONE).replace(second=0, microsecond=0) + timedelta(minutes=10)
        invalid_start = admin.post(f"/admin/auctions/{self.upcoming_auction_id}/edit-time", data={
            "csrf_token": admin_csrf,
            "end_time": before_start.strftime("%Y-%m-%dT%H:%M"),
        })
        self.assertEqual(invalid_start.status_code, 200)
        self.assertIn(b"later than the auction start time", invalid_start.data)

        buyer = flask_app.test_client()
        self.register(buyer, "Schedule Test Buyer", f"schedule-{uuid.uuid4().hex[:8]}@example.test", "AuctionPass!5")
        detail = buyer.get(f"/auction/{auction_id}")
        buyer_csrf = re.search(rb'name="csrf_token" value="([^"]+)"', detail.data).group(1).decode()
        accepted = buyer.post("/bid", data={
            "csrf_token": buyer_csrf,
            "auction_id": auction_id,
            "bid_amount": "1000",
        })
        self.assertEqual(accepted.status_code, 302)
        self.cursor.execute("SELECT COUNT(*) AS total FROM Bids WHERE auction_id=%s", (auction_id,))
        self.assertEqual(self.cursor.fetchone()["total"], 1)

        shortened_end = datetime.now(APP_TIMEZONE).replace(second=0, microsecond=0) + timedelta(minutes=2)
        shortened = admin.post(edit_url, data={
            "csrf_token": admin_csrf,
            "end_time": shortened_end.strftime("%Y-%m-%dT%H:%M"),
        })
        self.assertEqual(shortened.status_code, 302)
        self.cursor.execute("SELECT end_time FROM Auctions WHERE auction_id=%s", (auction_id,))
        self.assertEqual(self.cursor.fetchone()["end_time"], shortened_end.replace(tzinfo=None))
        self.assertLess(shortened_end, extended_end)
        shortened_schedule = admin.get(f"/api/auctions/schedules?id={auction_id}").get_json()[str(auction_id)]
        self.assertEqual(shortened_schedule["end_time"], shortened_end.replace(tzinfo=APP_TIMEZONE).isoformat())

        invalid = admin.post(edit_url, data={
            "csrf_token": admin_csrf,
            "end_time": (datetime.now(APP_TIMEZONE).replace(second=0, microsecond=0) - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M"),
        })
        self.assertEqual(invalid.status_code, 200)
        self.assertIn(b"must be in the future", invalid.data)
        self.cursor.execute("SELECT end_time FROM Auctions WHERE auction_id=%s", (auction_id,))
        self.assertEqual(self.cursor.fetchone()["end_time"], shortened_end.replace(tzinfo=None))

        self.cursor.execute("UPDATE Auctions SET end_time=DATE_SUB(NOW(),INTERVAL 1 MINUTE) WHERE auction_id=%s", (auction_id,))
        self.connection.commit()
        ended_edit = admin.post(edit_url, data={
            "csrf_token": admin_csrf,
            "response_mode": "modal",
            "end_time": (datetime.now(APP_TIMEZONE).replace(second=0, microsecond=0) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
        })
        self.assertEqual(ended_edit.status_code, 400)
        self.assertIn("already ended", ended_edit.get_json()["error"])
        rejected_bid = buyer.post("/bid", data={
            "csrf_token": buyer_csrf,
            "auction_id": auction_id,
            "bid_amount": "1100",
        })
        self.assertEqual(rejected_bid.status_code, 302)
        self.cursor.execute("SELECT COUNT(*) AS total FROM Bids WHERE auction_id=%s", (auction_id,))
        self.assertEqual(self.cursor.fetchone()["total"], 1)

        regular_user = flask_app.test_client()
        self.register(regular_user, "Regular User", f"regular-{uuid.uuid4().hex[:8]}@example.test", "AuctionPass!6")
        self.assertEqual(regular_user.get(edit_url).status_code, 403)
        user_detail = regular_user.get(f"/auction/{auction_id}")
        user_csrf = re.search(rb'name="csrf_token" value="([^"]+)"', user_detail.data).group(1).decode()
        forbidden = regular_user.post(edit_url, data={
            "csrf_token": user_csrf,
            "end_time": (datetime.now(APP_TIMEZONE).replace(second=0, microsecond=0) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M"),
        })
        self.assertEqual(forbidden.status_code, 403)

    def test_auth_registration_roles_and_admin_pages(self):
        client = flask_app.test_client()
        self.assertEqual(client.get("/").status_code, 302)
        self.assertIn("/login", client.get("/").headers["Location"])

        email = f"buyer-{uuid.uuid4().hex[:8]}@example.test"
        password = "AuctionPass!1"
        created = self.register(client, "Test Buyer", email, password)
        self.assertEqual(created.status_code, 302)
        self.assertEqual(client.get("/home").status_code, 200)

        self.cursor.execute("SELECT user_id,password,role FROM Users WHERE email=%s", (email,))
        user = self.cursor.fetchone()
        self.assertEqual(user["role"], "user")
        self.assertNotEqual(user["password"], password)
        self.assertTrue(check_password_hash(user["password"], password))
        self.assertEqual(client.get("/admin").status_code, 403)

        duplicate_client = flask_app.test_client()
        duplicate = self.register(duplicate_client, "Duplicate", email, password)
        self.assertEqual(duplicate.status_code, 200)
        self.assertIn(b"already uses that email", duplicate.data)

        admin = flask_app.test_client()
        csrf = self.token(admin, "/login")
        response = admin.post("/login", data={
            "csrf_token": csrf,
            "email": os.environ["ADMIN_EMAIL"],
            "password": os.environ["ADMIN_PASSWORD"],
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin", response.headers["Location"])
        for path in ("/admin", "/admin/users", "/admin/products", "/admin/auctions", "/admin/bids", "/auction-history", f"/auction/{self.auction_id}"):
            with self.subTest(path=path):
                self.assertEqual(admin.get(path).status_code, 200)

    def test_catalog_profile_watchlist_and_images(self):
        client = flask_app.test_client()
        self.register(client, "Catalog Buyer", f"catalog-{uuid.uuid4().hex[:8]}@example.test", "AuctionPass!2")
        for path in (
            "/auctions?q=Gaming&sort=price",
            "/auctions?status=Live&sort=ending",
            f"/auction/{self.auction_id}",
        ):
            with self.subTest(path=path):
                self.assertEqual(client.get(path).status_code, 200)

        detail = client.get(f"/auction/{self.auction_id}")
        csrf_match = re.search(rb'name="csrf_token" value="([^"]+)"', detail.data)
        self.assertIsNotNone(csrf_match)
        csrf = csrf_match.group(1).decode()
        response = client.post(f"/watchlist/{self.auction_id}/toggle", data={"csrf_token": csrf})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(client.get("/watchlist").status_code, 200)

        profile = client.post("/profile", data={
            "csrf_token": csrf,
            "name": "Updated Buyer",
            "email": f"updated-{uuid.uuid4().hex[:8]}@example.test",
        })
        self.assertEqual(profile.status_code, 302)
        self.assertEqual(client.get("/profile").status_code, 200)
        placeholder = client.get("/static/images/product-placeholder.svg")
        self.assertEqual(placeholder.status_code, 200)
        placeholder.close()

    def test_admin_product_and_auction_management(self):
        admin = flask_app.test_client()
        with admin.session_transaction() as state:
            state["user_id"] = self.admin_id
        token = self.token(admin, "/admin/products")
        name = f"Admin Test Listing {uuid.uuid4().hex[:6]}"
        created = admin.post("/admin/products", data={
            "csrf_token": token,
            "product_name": name,
            "category": "Testing",
            "starting_price": "2500.00",
            "description": "Created through the admin product form.",
            "image_url": "",
            "image_source": "",
        })
        self.assertEqual(created.status_code, 302)
        self.cursor.execute("SELECT product_id,category,starting_price FROM Products WHERE product_name=%s", (name,))
        product = self.cursor.fetchone()
        product_id = product["product_id"]
        self.assertEqual(product["category"], "Testing")
        self.assertEqual(float(product["starting_price"]), 2500.0)

        bad_image = admin.post("/admin/products", data={
            "csrf_token": token,
            "product_name": "Rejected Image Listing",
            "category": "Testing",
            "starting_price": "100",
            "description": "Invalid upload must not create a listing.",
            "image_file": (BytesIO(b"not an image"), "bad.jpg"),
        }, content_type="multipart/form-data")
        self.assertEqual(bad_image.status_code, 200)
        self.cursor.execute("SELECT COUNT(*) AS total FROM Products WHERE product_name='Rejected Image Listing'")
        self.assertEqual(self.cursor.fetchone()["total"], 0)

        edit_token = self.token(admin, f"/admin/products/{product_id}/edit")
        edited = admin.post(f"/admin/products/{product_id}/edit", data={
            "csrf_token": edit_token,
            "product_name": name,
            "category": "Collectibles",
            "starting_price": "2600.00",
            "description": "Edited through the admin product form.",
            "image_url": "",
            "image_source": "",
        })
        self.assertEqual(edited.status_code, 302)
        self.cursor.execute("SELECT category,starting_price,description FROM Products WHERE product_id=%s", (product_id,))
        edited_product = self.cursor.fetchone()
        self.assertEqual(edited_product["category"], "Collectibles")
        self.assertEqual(float(edited_product["starting_price"]), 2600.0)
        self.assertEqual(edited_product["description"], "Edited through the admin product form.")

        start = datetime.now(APP_TIMEZONE).replace(second=0, microsecond=0) + timedelta(minutes=5)
        end = start + timedelta(hours=2)
        auction_form = {
            "csrf_token": token,
            "product_id": str(product_id),
            "min_increment": "100.00",
            "start_time": start.strftime("%Y-%m-%dT%H:%M"),
            "end_time": end.strftime("%Y-%m-%dT%H:%M"),
        }
        scheduled = admin.post("/admin/auctions", data=auction_form)
        self.assertEqual(scheduled.status_code, 302)
        duplicate_schedule = admin.post("/admin/auctions", data=auction_form)
        self.assertEqual(duplicate_schedule.status_code, 200)
        self.cursor.execute("SELECT COUNT(*) AS total FROM Auctions WHERE product_id=%s", (product_id,))
        self.assertEqual(self.cursor.fetchone()["total"], 1)

        self.cursor.execute("SELECT auction_id FROM Auctions WHERE product_id=%s", (product_id,))
        product_auction_id = self.cursor.fetchone()["auction_id"]
        self.assertEqual(admin.get(f"/auction/{product_auction_id}").status_code, 200)
        self.assertEqual(admin.get(f"/admin/auctions?q={name}&status=Upcoming").status_code, 200)
        products_page = admin.get(f"/admin/products?q={name}")
        self.assertEqual(products_page.status_code, 200)
        self.assertIn(b"Auction Time", products_page.data)
        self.assertIn(b"data-auction-time-modal", products_page.data)
        self.assertIn(b"Save Changes", products_page.data)
        self.assertIn(b"Cancel", products_page.data)

        self.cursor.execute("SELECT start_time,end_time FROM Auctions WHERE auction_id=%s", (product_auction_id,))
        original_schedule = self.cursor.fetchone()
        invalid_close = (original_schedule["start_time"] - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M")
        invalid_modal_save = admin.post(
            f"/admin/auctions/{product_auction_id}/edit-time",
            data={"csrf_token": token, "response_mode": "modal", "end_time": invalid_close},
            headers={"Accept": "application/json"},
        )
        self.assertEqual(invalid_modal_save.status_code, 400)
        self.assertIn("later than the auction start time", invalid_modal_save.get_json()["error"])
        self.cursor.execute("SELECT end_time FROM Auctions WHERE auction_id=%s", (product_auction_id,))
        self.assertEqual(self.cursor.fetchone()["end_time"], original_schedule["end_time"])

        extended_close = original_schedule["end_time"] + timedelta(hours=1)
        extended_modal_save = admin.post(
            f"/admin/auctions/{product_auction_id}/edit-time",
            data={"csrf_token": token, "response_mode": "modal", "end_time": extended_close.strftime("%Y-%m-%dT%H:%M")},
            headers={"Accept": "application/json"},
        )
        self.assertEqual(extended_modal_save.status_code, 200)
        self.assertEqual(extended_modal_save.get_json()["closing_display"], extended_close.strftime("%d %b %Y, %I:%M %p"))
        self.cursor.execute("SELECT end_time FROM Auctions WHERE auction_id=%s", (product_auction_id,))
        self.assertEqual(self.cursor.fetchone()["end_time"], extended_close)

        shortened_close = original_schedule["end_time"] + timedelta(minutes=20)
        shortened_modal_save = admin.post(
            f"/admin/auctions/{product_auction_id}/edit-time",
            data={"csrf_token": token, "response_mode": "modal", "end_time": shortened_close.strftime("%Y-%m-%dT%H:%M")},
            headers={"Accept": "application/json"},
        )
        self.assertEqual(shortened_modal_save.status_code, 200)
        refreshed_products_page = admin.get(f"/admin/products?q={name}")
        self.assertIn(shortened_close.strftime("%Y-%m-%dT%H:%M").encode(), refreshed_products_page.data)
        self.assertIn(shortened_close.strftime("%d %b %Y, %I:%M %p").encode(), refreshed_products_page.data)
        archive = admin.post(f"/admin/products/{product_id}/archive", data={"csrf_token": token})
        self.assertEqual(archive.status_code, 302)
        self.cursor.execute("SELECT is_active FROM Products WHERE product_id=%s", (product_id,))
        self.assertEqual(self.cursor.fetchone()["is_active"], 1)

    def test_bid_validation_concurrency_and_winner_settlement(self):
        first = flask_app.test_client()
        second = flask_app.test_client()
        self.register(first, "Bidder One", f"bidder-one-{uuid.uuid4().hex[:8]}@example.test", "AuctionPass!3")
        self.register(second, "Bidder Two", f"bidder-two-{uuid.uuid4().hex[:8]}@example.test", "AuctionPass!4")

        detail = first.get(f"/auction/{self.auction_id}")
        csrf_one = re.search(rb'name="csrf_token" value="([^"]+)"', detail.data).group(1).decode()
        second_detail = second.get(f"/auction/{self.auction_id}")
        csrf_two = re.search(rb'name="csrf_token" value="([^"]+)"', second_detail.data).group(1).decode()
        accepted = first.post("/bid", data={
            "csrf_token": csrf_one,
            "auction_id": self.auction_id,
            "bid_amount": "1000",
        })
        self.assertEqual(accepted.status_code, 302)
        too_low = first.post("/bid", data={
            "csrf_token": csrf_one,
            "auction_id": self.auction_id,
            "bid_amount": "1050",
        })
        self.assertEqual(too_low.status_code, 302)

        def bid(client, token):
            return client.post("/bid", data={
                "csrf_token": token,
                "auction_id": self.auction_id,
                "bid_amount": "1100",
            }, environ_overrides={"REMOTE_ADDR": "127.0.0.2" if token == csrf_one else "127.0.0.3"})

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda args: bid(*args), ((first, csrf_one), (second, csrf_two))))
        self.assertTrue(all(response.status_code == 302 for response in results))
        self.cursor.execute("SELECT COUNT(*) AS total,MAX(bid_amount) AS highest FROM Bids WHERE auction_id=%s", (self.auction_id,))
        result = self.cursor.fetchone()
        self.assertEqual(result["total"], 2)
        self.assertEqual(float(result["highest"]), 1100.0)

        self.cursor.execute("UPDATE Auctions SET end_time=DATE_SUB(NOW(),INTERVAL 1 MINUTE) WHERE auction_id=%s", (self.auction_id,))
        self.connection.commit()
        history = first.get("/auction-history")
        self.assertEqual(history.status_code, 200)
        self.cursor.execute("SELECT winning_bid FROM Winners WHERE auction_id=%s", (self.auction_id,))
        winner = self.cursor.fetchone()
        self.assertIsNotNone(winner)
        self.assertEqual(float(winner["winning_bid"]), 1100.0)
        self.cursor.execute("SELECT payment_status FROM Payments WHERE auction_id=%s", (self.auction_id,))
        self.assertEqual(self.cursor.fetchone()["payment_status"], "Pending")
        ended_bid = first.post("/bid", data={
            "csrf_token": csrf_one,
            "auction_id": self.auction_id,
            "bid_amount": "1200",
        })
        upcoming_bid = first.post("/bid", data={
            "csrf_token": csrf_one,
            "auction_id": self.upcoming_auction_id,
            "bid_amount": "1000",
        })
        self.assertEqual(ended_bid.status_code, 302)
        self.assertEqual(upcoming_bid.status_code, 302)
        self.cursor.execute("SELECT COUNT(*) AS total FROM Bids WHERE auction_id=%s", (self.auction_id,))
        self.assertEqual(self.cursor.fetchone()["total"], 2)
        self.cursor.execute("SELECT COUNT(*) AS total FROM Bids WHERE auction_id=%s", (self.upcoming_auction_id,))
        self.assertEqual(self.cursor.fetchone()["total"], 0)


if __name__ == "__main__":
    unittest.main()
