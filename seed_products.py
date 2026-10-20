"""Idempotently add curated products and one auction per unlisted product."""

import os

import mysql.connector


PRODUCTS = [
    ("Vintage Film Camera", "A well-kept 35mm camera for collectors and film photography fans.", 8500, "Photography", "photo-1669415087163-587cb2944ccc", "https://unsplash.com/s/photos/film-camera"),
    ("Hand-thrown Ceramic Vase", "A one-of-a-kind glazed stoneware vase made by an independent potter.", 1800, "Home & Decor", "photo-1607200711767-5f91ad860ae0", "https://unsplash.com/s/photos/ceramic-vase"),
    ("Brass Desk Lamp", "A warm, adjustable brass lamp with a timeless mid-century profile.", 3500, "Home & Decor", "photo-1766524555120-9c2e886c72f5", "https://unsplash.com/s/photos/brass-desk-lamp"),
    ("First Edition Poetry Book", "A carefully preserved first edition from a beloved modern poet.", 2200, "Books", "photo-1698954634383-eba274a1b1c7", "https://unsplash.com/s/photos/open-book"),
    ("Woven Leather Satchel", "A sturdy hand-finished leather satchel with room for everyday essentials.", 4200, "Accessories", "photo-1473188588951-666fce8e7c68", "https://unsplash.com/s/photos/leather-bag"),
    ("Teakwood Mantel Clock", "A restored teakwood clock with a quiet movement and classic face.", 5100, "Collectibles", "photo-1619741468499-c9cac73c2df7", "https://unsplash.com/s/photos/analog-clock"),
    ("Classic Vinyl Turntable", "A vintage belt-drive turntable, ready for another spin.", 7200, "Audio", "photo-1645360148899-f9a99c23a153", "https://unsplash.com/s/photos/vintage-turntable"),
    ("Handwoven Wool Rug", "A colorful handwoven wool rug with a distinctive geometric pattern.", 6400, "Home & Decor", "photo-1532526674046-5b3f6d7d2ab1", "https://unsplash.com/s/photos/wool-rug"),
    ("Silver Cuff Bracelet", "A simple sterling silver cuff with a softly hammered finish.", 2800, "Jewelry", "photo-1581522723372-e1a239e7ed2d", "https://unsplash.com/s/photos/silver-bracelet"),
    ("Retro Typewriter", "A restored portable typewriter with original keys and carrying case.", 9500, "Collectibles", "photo-1640350412168-d32860d61c2d", "https://unsplash.com/photos/an-old-fashioned-typewriter-sitting-on-a-wooden-table-SM-GdzIWJfk"),
    ("Wireless Headphones", "Comfortable wireless over-ear headphones with a clean, modern design.", 7800, "Audio", "photo-1505740420928-5e560c06d30e", "https://unsplash.com/photos/flatlay-photography-of-wireless-headphones-PDX_a_82obo"),
    ("Gaming Laptop", "A powerful gaming laptop ready for competitive play and creative work.", 84000, "Electronics", "photo-1771015310937-6754da25e49a", "https://unsplash.com/s/photos/gaming-laptop"),
    ("Smartphone", "A recent-generation smartphone with a bright display and capable camera.", 22000, "Electronics", "photo-1630598706778-798e5204a0dc", "https://unsplash.com/s/photos/smartphone"),
    ("Premium Wristwatch", "A refined wristwatch with a polished case and timeless styling.", 16000, "Accessories", "photo-1775145478616-250890a4dd81", "https://unsplash.com/s/photos/premium-wristwatch"),
    ("City Bicycle", "A versatile city bicycle suited to daily rides and weekend exploring.", 18000, "Sports & Outdoors", "photo-1532298229144-0ec0c57515c7", "https://unsplash.com/s/photos/city-bicycle"),
    ("Collectible Sneakers", "A limited-style sneaker pair for collectors and streetwear fans.", 9500, "Fashion", "photo-1622760808027-095ea611f657", "https://unsplash.com/s/photos/collectible-sneakers"),
    ("Digital Camera", "A compact digital camera with a flip-out screen for photography and video.", 32000, "Photography", "photo-1774647665780-1eb47c16db16", "https://unsplash.com/photos/a-black-digital-camera-with-a-flip-out-screen-g3nPQlhkfLw"),
    ("Handheld Game Console", "A portable game console for gaming at home or on the move.", 18000, "Electronics", "photo-1618556679398-486ba2cf2e89", "https://unsplash.com/s/photos/handheld-game-console"),
    ("Antique Furniture Cabinet", "A characterful antique cabinet with warm wood grain and classic proportions.", 25000, "Home & Decor", "photo-1655375207595-54c5df5aacb8", "https://unsplash.com/photos/a-large-antique-cabinet-hcimh-jO6Mk"),
]


def main():
    connection = mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "localhost"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        database=os.getenv("MYSQL_DATABASE", "auction_db"),
    )
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT user_id FROM Users WHERE email=%s", (os.getenv("ADMIN_EMAIL", "vasan1@gmail.com").lower(),))
        admin = cursor.fetchone()
        seller_id = admin[0] if admin else None
        added = 0
        auction_count = 0
        for name, description, price, category, photo_id, source in PRODUCTS:
            image_url = f"https://images.unsplash.com/{photo_id}?auto=format&fit=crop&w=1000&q=85"
            cursor.execute("SELECT product_id FROM Products WHERE product_name=%s ORDER BY product_id LIMIT 1", (name,))
            existing = cursor.fetchone()
            if existing:
                product_id = existing[0]
                cursor.execute(
                    """UPDATE Products SET category=%s,image_url=%s,image_source=%s
                       WHERE product_id=%s""",
                    (category, image_url, source, product_id),
                )
            else:
                cursor.execute(
                    """INSERT INTO Products
                       (product_name,description,starting_price,category,image_url,image_source,seller_id)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (name, description, price, category, image_url, source, seller_id),
                )
                product_id = cursor.lastrowid
                added += 1

            cursor.execute("SELECT 1 FROM Auctions WHERE product_id=%s LIMIT 1", (product_id,))
            if not cursor.fetchone():
                cursor.execute(
                    """INSERT INTO Auctions (product_id,start_time,end_time,status,min_increment)
                       VALUES (%s,NOW(),DATE_ADD(NOW(),INTERVAL 7 DAY),'Active',100.00)""",
                    (product_id,),
                )
                auction_count += 1

        connection.commit()
        print(f"Inventory ready: {len(PRODUCTS)} curated products; added {added} new products and {auction_count} auctions.")
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


if __name__ == "__main__":
    main()
