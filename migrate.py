"""Additive, repeatable schema migration for auction_db."""

import os

import mysql.connector


def connect():
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "localhost"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        database=os.getenv("MYSQL_DATABASE", "auction_db"),
    )


def column_exists(cursor, table, column):
    cursor.execute(
        """SELECT 1 FROM information_schema.columns
           WHERE table_schema = DATABASE() AND table_name = %s
             AND column_name = %s LIMIT 1""",
        (table, column),
    )
    return cursor.fetchone() is not None


def index_exists(cursor, table, index):
    cursor.execute(
        """SELECT 1 FROM information_schema.statistics
           WHERE table_schema = DATABASE() AND table_name = %s
             AND index_name = %s LIMIT 1""",
        (table, index),
    )
    return cursor.fetchone() is not None


def add_column(cursor, table, column, definition):
    if not column_exists(cursor, table, column):
        cursor.execute(
            f"ALTER TABLE `{table}` ADD COLUMN `{column}` {definition}"
        )
        print(f"Added {table}.{column}")


def add_index(cursor, table, name, expression):
    if not index_exists(cursor, table, name):
        cursor.execute(f"CREATE INDEX `{name}` ON `{table}` ({expression})")
        print(f"Added index {name}")


def migrate():
    connection = connect()
    cursor = connection.cursor()
    try:
        add_column(cursor, "Users", "role", "VARCHAR(20) NOT NULL DEFAULT 'user'")
        add_column(cursor, "Users", "is_active", "TINYINT(1) NOT NULL DEFAULT 1")
        add_column(cursor, "Users", "created_at", "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP")

        add_column(cursor, "Products", "category", "VARCHAR(80) NOT NULL DEFAULT 'Collectibles'")
        add_column(cursor, "Products", "image_url", "VARCHAR(500) NULL")
        add_column(cursor, "Products", "image_source", "VARCHAR(500) NULL")
        add_column(cursor, "Products", "seller_id", "INT NULL")
        add_column(cursor, "Products", "is_active", "TINYINT(1) NOT NULL DEFAULT 1")
        add_column(cursor, "Products", "created_at", "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP")

        add_column(cursor, "Auctions", "min_increment", "DECIMAL(10,2) NOT NULL DEFAULT 1.00")

        cursor.execute(
            """CREATE TABLE IF NOT EXISTS Watchlist (
                watchlist_id INT PRIMARY KEY AUTO_INCREMENT,
                user_id INT NOT NULL,
                auction_id INT NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_watchlist_user_auction (user_id, auction_id),
                KEY ix_watchlist_auction (auction_id),
                CONSTRAINT fk_watchlist_user FOREIGN KEY (user_id)
                    REFERENCES Users(user_id) ON DELETE CASCADE,
                CONSTRAINT fk_watchlist_auction FOREIGN KEY (auction_id)
                    REFERENCES Auctions(auction_id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
        )

        add_index(cursor, "Users", "ix_users_created_at", "created_at")
        add_index(cursor, "Products", "ix_products_category_active", "category, is_active")
        add_index(cursor, "Products", "ix_products_seller", "seller_id")
        add_index(cursor, "Auctions", "ix_auctions_schedule", "start_time, end_time")
        add_index(cursor, "Bids", "ix_bids_user_time", "user_id, bid_time")

        # Older versions of the project omitted the bidder foreign key.
        cursor.execute(
            """SELECT 1 FROM information_schema.referential_constraints
               WHERE constraint_schema = DATABASE()
                 AND table_name = 'bids' AND constraint_name = 'fk_bids_user'
               LIMIT 1"""
        )
        has_bid_user_fk = cursor.fetchone() is not None
        cursor.execute(
            """SELECT COUNT(*) FROM Bids b
               LEFT JOIN Users u ON u.user_id = b.user_id
               WHERE u.user_id IS NULL"""
        )
        orphan_bids = cursor.fetchone()[0]
        if not has_bid_user_fk and orphan_bids == 0:
            cursor.execute(
                """ALTER TABLE Bids
                   ADD CONSTRAINT fk_bids_user FOREIGN KEY (user_id)
                   REFERENCES Users(user_id)"""
            )
            print("Added bidder foreign key")
        elif orphan_bids:
            print(f"Skipped bidder foreign key: {orphan_bids} orphan bid(s) need review")

        cursor.execute(
            """SELECT 1 FROM information_schema.referential_constraints
               WHERE constraint_schema = DATABASE()
                 AND table_name = 'products' AND constraint_name = 'fk_products_seller'
               LIMIT 1"""
        )
        has_seller_fk = cursor.fetchone() is not None
        if not has_seller_fk:
            cursor.execute(
                """ALTER TABLE Products ADD CONSTRAINT fk_products_seller
                   FOREIGN KEY (seller_id) REFERENCES Users(user_id) ON DELETE SET NULL"""
            )
            print("Added product seller foreign key")

        connection.commit()
        print("Migration complete.")
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


if __name__ == "__main__":
    migrate()
