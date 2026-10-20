USE auction_db;

-- Refresh image and category details on the original ten sample listings.
UPDATE Products
SET category = CASE product_name
      WHEN 'Vintage Film Camera' THEN 'Photography'
      WHEN 'Hand-thrown Ceramic Vase' THEN 'Home & Decor'
      WHEN 'Brass Desk Lamp' THEN 'Home & Decor'
      WHEN 'First Edition Poetry Book' THEN 'Books'
      WHEN 'Woven Leather Satchel' THEN 'Accessories'
      WHEN 'Teakwood Mantel Clock' THEN 'Collectibles'
      WHEN 'Classic Vinyl Turntable' THEN 'Audio'
      WHEN 'Handwoven Wool Rug' THEN 'Home & Decor'
      WHEN 'Silver Cuff Bracelet' THEN 'Jewelry'
      WHEN 'Retro Typewriter' THEN 'Collectibles'
      WHEN 'Wireless Headphones' THEN 'Audio'
    END,
    image_url = CASE product_name
      WHEN 'Vintage Film Camera' THEN 'https://images.unsplash.com/photo-1669415087163-587cb2944ccc?auto=format&fit=crop&w=1000&q=85'
      WHEN 'Hand-thrown Ceramic Vase' THEN 'https://images.unsplash.com/photo-1607200711767-5f91ad860ae0?auto=format&fit=crop&w=1000&q=85'
      WHEN 'Brass Desk Lamp' THEN 'https://images.unsplash.com/photo-1766524555120-9c2e886c72f5?auto=format&fit=crop&w=1000&q=85'
      WHEN 'First Edition Poetry Book' THEN 'https://images.unsplash.com/photo-1698954634383-eba274a1b1c7?auto=format&fit=crop&w=1000&q=85'
      WHEN 'Woven Leather Satchel' THEN 'https://images.unsplash.com/photo-1473188588951-666fce8e7c68?auto=format&fit=crop&w=1000&q=85'
      WHEN 'Teakwood Mantel Clock' THEN 'https://images.unsplash.com/photo-1619741468499-c9cac73c2df7?auto=format&fit=crop&w=1000&q=85'
      WHEN 'Classic Vinyl Turntable' THEN 'https://images.unsplash.com/photo-1645360148899-f9a99c23a153?auto=format&fit=crop&w=1000&q=85'
      WHEN 'Handwoven Wool Rug' THEN 'https://images.unsplash.com/photo-1532526674046-5b3f6d7d2ab1?auto=format&fit=crop&w=1000&q=85'
      WHEN 'Silver Cuff Bracelet' THEN 'https://images.unsplash.com/photo-1581522723372-e1a239e7ed2d?auto=format&fit=crop&w=1000&q=85'
      WHEN 'Retro Typewriter' THEN 'https://images.unsplash.com/photo-1640350412168-d32860d61c2d?auto=format&fit=crop&w=1000&q=85'
      WHEN 'Wireless Headphones' THEN 'https://images.unsplash.com/photo-1505740420928-5e560c06d30e?auto=format&fit=crop&w=1000&q=85'
    END,
    image_source = CASE product_name
      WHEN 'Vintage Film Camera' THEN 'https://unsplash.com/s/photos/film-camera'
      WHEN 'Hand-thrown Ceramic Vase' THEN 'https://unsplash.com/s/photos/ceramic-vase'
      WHEN 'Brass Desk Lamp' THEN 'https://unsplash.com/s/photos/brass-desk-lamp'
      WHEN 'First Edition Poetry Book' THEN 'https://unsplash.com/s/photos/open-book'
      WHEN 'Woven Leather Satchel' THEN 'https://unsplash.com/s/photos/leather-bag'
      WHEN 'Teakwood Mantel Clock' THEN 'https://unsplash.com/s/photos/analog-clock'
      WHEN 'Classic Vinyl Turntable' THEN 'https://unsplash.com/s/photos/vintage-turntable'
      WHEN 'Handwoven Wool Rug' THEN 'https://unsplash.com/s/photos/wool-rug'
      WHEN 'Silver Cuff Bracelet' THEN 'https://unsplash.com/s/photos/silver-bracelet'
      WHEN 'Retro Typewriter' THEN 'https://unsplash.com/photos/an-old-fashioned-typewriter-sitting-on-a-wooden-table-SM-GdzIWJfk'
      WHEN 'Wireless Headphones' THEN 'https://unsplash.com/photos/flatlay-photography-of-wireless-headphones-PDX_a_82obo'
    END
WHERE product_name IN (
    'Vintage Film Camera','Hand-thrown Ceramic Vase','Brass Desk Lamp',
    'First Edition Poetry Book','Woven Leather Satchel','Teakwood Mantel Clock',
    'Classic Vinyl Turntable','Handwoven Wool Rug','Silver Cuff Bracelet',
    'Retro Typewriter','Wireless Headphones'
);

-- Create the original ten curated listings for an empty fresh database too.
INSERT INTO Products
    (product_name,description,starting_price,category,image_url,image_source,seller_id)
SELECT s.product_name,s.description,s.starting_price,s.category,s.image_url,
       s.image_source,(SELECT user_id FROM Users WHERE email='vasan1@gmail.com' LIMIT 1)
FROM (
    SELECT 'Vintage Film Camera' AS product_name,
           'A well-kept 35mm camera for collectors and film photography fans.' AS description,
           8500.00 AS starting_price,'Photography' AS category,
           'https://images.unsplash.com/photo-1669415087163-587cb2944ccc?auto=format&fit=crop&w=1000&q=85' AS image_url,
           'https://unsplash.com/s/photos/film-camera' AS image_source
    UNION ALL SELECT 'Hand-thrown Ceramic Vase','A one-of-a-kind glazed stoneware vase made by an independent potter.',1800.00,'Home & Decor','https://images.unsplash.com/photo-1607200711767-5f91ad860ae0?auto=format&fit=crop&w=1000&q=85','https://unsplash.com/s/photos/ceramic-vase'
    UNION ALL SELECT 'Brass Desk Lamp','A warm, adjustable brass lamp with a timeless mid-century profile.',3500.00,'Home & Decor','https://images.unsplash.com/photo-1766524555120-9c2e886c72f5?auto=format&fit=crop&w=1000&q=85','https://unsplash.com/s/photos/brass-desk-lamp'
    UNION ALL SELECT 'First Edition Poetry Book','A carefully preserved first edition from a beloved modern poet.',2200.00,'Books','https://images.unsplash.com/photo-1698954634383-eba274a1b1c7?auto=format&fit=crop&w=1000&q=85','https://unsplash.com/s/photos/open-book'
    UNION ALL SELECT 'Woven Leather Satchel','A sturdy hand-finished leather satchel with room for everyday essentials.',4200.00,'Accessories','https://images.unsplash.com/photo-1473188588951-666fce8e7c68?auto=format&fit=crop&w=1000&q=85','https://unsplash.com/s/photos/leather-bag'
    UNION ALL SELECT 'Teakwood Mantel Clock','A restored teakwood clock with a quiet movement and classic face.',5100.00,'Collectibles','https://images.unsplash.com/photo-1619741468499-c9cac73c2df7?auto=format&fit=crop&w=1000&q=85','https://unsplash.com/s/photos/analog-clock'
    UNION ALL SELECT 'Classic Vinyl Turntable','A vintage belt-drive turntable, ready for another spin.',7200.00,'Audio','https://images.unsplash.com/photo-1645360148899-f9a99c23a153?auto=format&fit=crop&w=1000&q=85','https://unsplash.com/s/photos/vintage-turntable'
    UNION ALL SELECT 'Handwoven Wool Rug','A colorful handwoven wool rug with a distinctive geometric pattern.',6400.00,'Home & Decor','https://images.unsplash.com/photo-1532526674046-5b3f6d7d2ab1?auto=format&fit=crop&w=1000&q=85','https://unsplash.com/s/photos/wool-rug'
    UNION ALL SELECT 'Silver Cuff Bracelet','A simple sterling silver cuff with a softly hammered finish.',2800.00,'Jewelry','https://images.unsplash.com/photo-1581522723372-e1a239e7ed2d?auto=format&fit=crop&w=1000&q=85','https://unsplash.com/s/photos/silver-bracelet'
    UNION ALL SELECT 'Retro Typewriter','A restored portable typewriter with original keys and carrying case.',9500.00,'Collectibles','https://images.unsplash.com/photo-1640350412168-d32860d61c2d?auto=format&fit=crop&w=1000&q=85','https://unsplash.com/photos/an-old-fashioned-typewriter-sitting-on-a-wooden-table-SM-GdzIWJfk'
) AS s
WHERE NOT EXISTS (SELECT 1 FROM Products p WHERE p.product_name=s.product_name);

-- Add eight more sample items. Re-running this script will not duplicate them.
INSERT INTO Products
    (product_name,description,starting_price,category,image_url,image_source,seller_id)
SELECT s.product_name,s.description,s.starting_price,s.category,s.image_url,
       s.image_source,(SELECT user_id FROM Users WHERE email='vasan1@gmail.com' LIMIT 1)
FROM (
    SELECT 'Wireless Headphones' AS product_name,
           'Comfortable wireless over-ear headphones with a clean, modern design.' AS description,
           7800.00 AS starting_price,'Audio' AS category,
           'https://images.unsplash.com/photo-1505740420928-5e560c06d30e?auto=format&fit=crop&w=1000&q=85' AS image_url,
           'https://unsplash.com/photos/flatlay-photography-of-wireless-headphones-PDX_a_82obo' AS image_source
    UNION ALL SELECT 'Gaming Laptop','A powerful gaming laptop ready for competitive play and creative work.',84000.00,'Electronics','https://images.unsplash.com/photo-1771015310937-6754da25e49a?auto=format&fit=crop&w=1000&q=85','https://unsplash.com/s/photos/gaming-laptop'
    UNION ALL SELECT 'Smartphone','A recent-generation smartphone with a bright display and capable camera.',22000.00,'Electronics','https://images.unsplash.com/photo-1630598706778-798e5204a0dc?auto=format&fit=crop&w=1000&q=85','https://unsplash.com/s/photos/smartphone'
    UNION ALL SELECT 'Premium Wristwatch','A refined wristwatch with a polished case and timeless styling.',16000.00,'Accessories','https://images.unsplash.com/photo-1775145478616-250890a4dd81?auto=format&fit=crop&w=1000&q=85','https://unsplash.com/s/photos/premium-wristwatch'
    UNION ALL SELECT 'City Bicycle','A versatile city bicycle suited to daily rides and weekend exploring.',18000.00,'Sports & Outdoors','https://images.unsplash.com/photo-1532298229144-0ec0c57515c7?auto=format&fit=crop&w=1000&q=85','https://unsplash.com/s/photos/city-bicycle'
    UNION ALL SELECT 'Collectible Sneakers','A limited-style sneaker pair for collectors and streetwear fans.',9500.00,'Fashion','https://images.unsplash.com/photo-1622760808027-095ea611f657?auto=format&fit=crop&w=1000&q=85','https://unsplash.com/s/photos/collectible-sneakers'
    UNION ALL SELECT 'Digital Camera','A compact digital camera with a flip-out screen for photography and video.',32000.00,'Photography','https://images.unsplash.com/photo-1774647665780-1eb47c16db16?auto=format&fit=crop&w=1000&q=85','https://unsplash.com/photos/a-black-digital-camera-with-a-flip-out-screen-g3nPQlhkfLw'
    UNION ALL SELECT 'Handheld Game Console','A portable game console for gaming at home or on the move.',18000.00,'Electronics','https://images.unsplash.com/photo-1618556679398-486ba2cf2e89?auto=format&fit=crop&w=1000&q=85','https://unsplash.com/s/photos/handheld-game-console'
    UNION ALL SELECT 'Antique Furniture Cabinet','A characterful antique cabinet with warm wood grain and classic proportions.',25000.00,'Home & Decor','https://images.unsplash.com/photo-1655375207595-54c5df5aacb8?auto=format&fit=crop&w=1000&q=85','https://unsplash.com/photos/a-large-antique-cabinet-hcimh-jO6Mk'
) AS s
WHERE NOT EXISTS (
    SELECT 1 FROM Products p WHERE p.product_name=s.product_name
);

-- Add one-week auctions only for seeded products that do not already have one.
INSERT INTO Auctions (product_id,start_time,end_time,status,min_increment)
SELECT p.product_id,NOW(),DATE_ADD(NOW(),INTERVAL 7 DAY),'Active',100.00
FROM Products p
LEFT JOIN Auctions a ON a.product_id=p.product_id
WHERE a.auction_id IS NULL AND p.product_name IN (
    'Vintage Film Camera','Hand-thrown Ceramic Vase','Brass Desk Lamp',
    'First Edition Poetry Book','Woven Leather Satchel','Teakwood Mantel Clock',
    'Classic Vinyl Turntable','Handwoven Wool Rug','Silver Cuff Bracelet',
    'Retro Typewriter','Wireless Headphones','Gaming Laptop','Smartphone',
    'Premium Wristwatch','City Bicycle','Collectible Sneakers','Digital Camera',
    'Handheld Game Console','Antique Furniture Cabinet'
);
