
CREATE DATABASE IF NOT EXISTS auction_db;
USE auction_db;

CREATE TABLE Users (
    user_id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL
);

CREATE TABLE Products (
    product_id INT PRIMARY KEY AUTO_INCREMENT,
    product_name VARCHAR(100) NOT NULL,
    description VARCHAR(255),
    starting_price DECIMAL(10,2) NOT NULL
);

CREATE TABLE Auctions (
    auction_id INT PRIMARY KEY AUTO_INCREMENT,
    product_id INT NOT NULL,
    start_time DATETIME,
    end_time DATETIME,
    status VARCHAR(20) DEFAULT 'Active',
    FOREIGN KEY (product_id)
        REFERENCES Products(product_id)
);

CREATE TABLE Bids (
    bid_id INT PRIMARY KEY AUTO_INCREMENT,
    auction_id INT NOT NULL,
    user_id INT NOT NULL,
    bid_amount DECIMAL(10,2) NOT NULL,
    bid_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (auction_id)
        REFERENCES Auctions(auction_id)
);

