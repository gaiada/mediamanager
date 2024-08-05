FROM ubuntu

# Install ffmpeg, MySQL server, and required dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    mysql-server \
    python3 \
    python3-venv \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*


# Copy the current directory contents into the container at /app
COPY mediamanager /opt/mediamanager
COPY requirements.txt /opt/mediamanager
# Set the working directory
WORKDIR /opt/mediamanager


# Install Python dependencies

RUN python3 -m venv /opt/mediamanager/myenv

RUN . /opt/mediamanager/myenv/bin/activate
RUN pip install -r /opt/mediamanager/requirements.txt


# Expose port 5000 for Flask and 3306 for MySQL
EXPOSE 5000 3306

# Add a script to run both MySQL server and the Python application
COPY entrypoint.sh /entrypoint.sh

# Set the entrypoint to the script
ENTRYPOINT ["/entrypoint.sh"]

