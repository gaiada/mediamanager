#!/bin/bash

# Start the MySQL service
service mysql start

# Wait for MySQL to fully start
until mysqladmin ping -h "localhost" --silent; do
    echo "Waiting for MySQL to start..."
    sleep 1
done

# Create the database and user, and grant privileges
mysql -e "CREATE DATABASE mediamanager;"
mysql -e "CREATE USER 'mediamanager'@'localhost' IDENTIFIED BY 'm3d14m4n4g3r';"
mysql -e "GRANT ALL PRIVILEGES ON mediamanager.* TO 'mediamanager'@'localhost';"
mysql -e "FLUSH PRIVILEGES;"

# Initialize the database schema
mysql mediamanager < /opt/mediamanager/database-schema.sql

# Run the Flask application
cd /opt/mediamanager
exec python3 app.py

