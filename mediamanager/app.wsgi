
import sys
import os
import datetime

try:
    # Log a simple message to verify if the script runs
    with open("/media/test.log", "a") as log_file:
        log_file.write(f"WSGI script loaded at {datetime.datetime.now()}\n")

    # Virtual environment setup
    venv_path = "/mnt/c/Users/Bel/media/myenv/lib/python3.8/site-packages"
    sys.path.insert(0, venv_path)

    # Add the directory containing the Flask app
    app_dir = os.path.dirname(__file__)
    sys.path.insert(0, app_dir)

    # Import the Flask app
    from app import app as application
except Exception as e:
    # Log any exceptions
    with open("/media/test.log", "a") as log_file:
        log_file.write(f"Error: {e}\n")

