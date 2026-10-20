"""Create or refresh the configured demo administrator account."""

import os

import mysql.connector
from werkzeug.security import generate_password_hash


def main():
    email = os.getenv("ADMIN_EMAIL", "vasan1@gmail.com").strip().lower()
    password = os.getenv("ADMIN_PASSWORD", "vasan@1")
    name = os.getenv("ADMIN_NAME", "Auction Administrator").strip()

    if not password:
        raise SystemExit("ADMIN_PASSWORD cannot be empty.")

    connection = mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "localhost"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        database=os.getenv("MYSQL_DATABASE", "auction_db"),
    )
    cursor = connection.cursor()
    try:
        password_hash = generate_password_hash(password)
        cursor.execute(
            """INSERT INTO Users (name, email, password, role, is_active)
               VALUES (%s, %s, %s, 'admin', 1)
               ON DUPLICATE KEY UPDATE
                   name = VALUES(name),
                   password = VALUES(password),
                   role = 'admin',
                   is_active = 1""",
            (name, email, password_hash),
        )
        # ON DUPLICATE KEY does not set lastrowid consistently, so look up the account.
        cursor.execute("SELECT user_id FROM Users WHERE email=%s", (email,))
        admin_id = cursor.fetchone()[0]
        cursor.execute(
            "UPDATE Products SET seller_id=%s WHERE seller_id IS NULL",
            (admin_id,),
        )
        connection.commit()
        print(f"Administrator is ready: {email}")
        print("This demo password is public; change ADMIN_PASSWORD before deployment.")
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


if __name__ == "__main__":
    main()
