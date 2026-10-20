# Bidwell Auction Management System

Bidwell is a Flask and MySQL auction marketplace. Customers can browse and search auction listings, place transactional bids, follow lots, and review their bids. Administrators can manage members, products, auction schedules, and recorded bid activity.

## Requirements

- Python 3.10 or newer
- MySQL 8.0 or a compatible MySQL server
- Internet access for the remotely hosted Unsplash product photos (a local placeholder is shown if a photo fails to load)

## Setup on Windows PowerShell

From the project directory, create and activate an environment, then install the dependencies:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Set the database connection values for the current PowerShell session. Keep the password private:

```powershell
$env:MYSQL_HOST = "localhost"
$env:MYSQL_PORT = "3306"
$env:MYSQL_USER = "root"
$env:MYSQL_PASSWORD = "your-mysql-password"
$env:MYSQL_DATABASE = "auction_db"
$env:MYSQL_TIME_ZONE = "+05:30"
$env:APP_TIMEZONE = "Asia/Kolkata"
```

For a new database, create the tables and then seed the administrator and product catalog:

```powershell
mysql -u $env:MYSQL_USER -p -e "source database.sql"
python migrate.py
python seed_admin.py
python seed_products.py
```

For an existing project database, preserve its data and run the additive migration before the seeders:

```powershell
python migrate.py
python seed_admin.py
python seed_products.py
```

The admin seed is repeatable and uses `vasan1@gmail.com` / `vasan@1` by default, as requested for the college demo. Override those values before running the seeder if needed:

```powershell
$env:ADMIN_EMAIL = "admin@example.com"
$env:ADMIN_PASSWORD = "choose-a-private-password"
$env:ADMIN_NAME = "Auction Administrator"
python seed_admin.py
```

The default credentials are public demo credentials. Set a private `ADMIN_PASSWORD` before any deployment. Set a stable Flask secret as well; production mode refuses to start without it:

```powershell
$env:FLASK_SECRET_KEY = "replace-with-a-long-random-secret"
$env:APP_ENV = "production"
$env:SESSION_COOKIE_SECURE = "1"
```

Run the local server:

```powershell
python app.py
```

The development server listens at `http://127.0.0.1:5000`. For production, serve the WSGI app with a production server behind HTTPS rather than Flask's development server.

## Tests

The end-to-end suite creates a randomly named disposable MySQL database, initializes the schema and seed data, exercises account roles, catalog/profile/watchlist pages, bid validation, concurrent bids, and auction settlement, then drops the disposable database:

```powershell
python -m unittest discover -s tests -v
```

The MySQL account used for tests needs permission to create and drop databases. The suite does not write its test users, bids, or products into the configured `auction_db`.

## Images

Seeded product images use individual Unsplash photo URLs and keep a corresponding source page in `Products.image_source`. The marketplace footer links to the [Unsplash License](https://unsplash.com/license). Administrators can set an HTTPS image URL or upload a JPG, PNG, or WebP image up to 5 MB.

## Schema notes

- `database.sql` is the complete fresh-install schema.
- `migrate.py` is an additive, repeatable migration for the original `auction_db` tables.
- `seed_admin.py` creates or refreshes the configured admin account using Werkzeug's password hashing.
- `seed_products.py` updates the curated image/category metadata and adds missing sample listings and auctions without duplicating them.
- `seed_products.sql` contains the matching SQL-based image and demo inventory seed for manual MySQL use.
