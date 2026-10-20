-- Fresh-install schema for Bidwell Auction Management.
-- For an existing installation, run migrate.py instead of recreating tables.
CREATE DATABASE IF NOT EXISTS auction_db
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE auction_db;

CREATE TABLE IF NOT EXISTS Users (
    user_id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(100) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'user',
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY ix_users_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS Products (
    product_id INT PRIMARY KEY AUTO_INCREMENT,
    product_name VARCHAR(100) NOT NULL,
    description VARCHAR(255),
    starting_price DECIMAL(10,2) NOT NULL,
    category VARCHAR(80) NOT NULL DEFAULT 'Collectibles',
    image_url VARCHAR(500),
    image_source VARCHAR(500),
    seller_id INT NULL,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY ix_products_category_active (category, is_active),
    KEY ix_products_seller (seller_id),
    CONSTRAINT fk_products_seller FOREIGN KEY (seller_id)
        REFERENCES Users(user_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS Auctions (
    auction_id INT PRIMARY KEY AUTO_INCREMENT,
    product_id INT NOT NULL,
    start_time DATETIME NOT NULL,
    end_time DATETIME NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'Active',
    min_increment DECIMAL(10,2) NOT NULL DEFAULT 1.00,
    KEY ix_auctions_schedule (start_time, end_time),
    CONSTRAINT fk_auctions_product FOREIGN KEY (product_id)
        REFERENCES Products(product_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS Bids (
    bid_id INT PRIMARY KEY AUTO_INCREMENT,
    auction_id INT NOT NULL,
    user_id INT NOT NULL,
    bid_amount DECIMAL(10,2) NOT NULL,
    bid_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY ix_bids_auction_amount (auction_id, bid_amount),
    KEY ix_bids_user_time (user_id, bid_time),
    CONSTRAINT fk_bids_auction FOREIGN KEY (auction_id)
        REFERENCES Auctions(auction_id),
    CONSTRAINT fk_bids_user FOREIGN KEY (user_id)
        REFERENCES Users(user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS Winners (
    auction_id INT PRIMARY KEY,
    user_id INT NOT NULL,
    winning_bid DECIMAL(10,2) NOT NULL,
    won_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_winners_auction FOREIGN KEY (auction_id)
        REFERENCES Auctions(auction_id),
    CONSTRAINT fk_winners_user FOREIGN KEY (user_id)
        REFERENCES Users(user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS Payments (
    payment_id INT PRIMARY KEY AUTO_INCREMENT,
    auction_id INT NOT NULL UNIQUE,
    user_id INT NOT NULL,
    amount DECIMAL(10,2) NOT NULL,
    payment_status VARCHAR(20) NOT NULL DEFAULT 'Pending',
    payment_date DATETIME NULL,
    CONSTRAINT fk_payments_auction FOREIGN KEY (auction_id)
        REFERENCES Auctions(auction_id),
    CONSTRAINT fk_payments_user FOREIGN KEY (user_id)
        REFERENCES Users(user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS Watchlist (
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
