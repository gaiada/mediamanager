#import sqlite3 
import hashlib
from PIL import Image, UnidentifiedImageError
import os 
import json
import random
import string
from flask import Flask, render_template, redirect, url_for, request, session, flash, jsonify,current_app, send_file, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash

from concurrent.futures import ThreadPoolExecutor
from queue import Queue
import threading
import time

#from flask_socketio import SocketIO, emit

import subprocess

import shutil
import filecmp 
from contextlib import contextmanager
import mysql.connector
from mysql.connector import pooling
import tempfile
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'My_secr3t_qey'



garbage_dir = '/mnt/garbage'


IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff','.jfif'}
VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv'}


MAX_CONCURRENT_THREADS = 4

executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_THREADS)

task_queue = Queue()

lock = threading.Lock()

thumbnail_lock = threading.Lock()
directory_locks = {}
global_lock = threading.Lock()  




pool = mysql.connector.pooling.MySQLConnectionPool(
    pool_name="mypool", 
    pool_size=20,
    pool_reset_session=True,
    host="localhost",   
    user="mediamanager",    
    password="m3d14m4n4g3r",  
    database="mediamanager"  
)





@app.route('/serve', methods=['GET'])
def serve_file():
    if 'username' not in session:
        return redirect(url_for('login'))
    if 'filepath' not in request.args:
        return 'Error: filepath parameter is missing', 400
    
    file_path = request.args['filepath']
    
    absolute_file_path = "/" + file_path 

    return send_from_directory('/', file_path)





def create_cache(file_info):
    item_path, item_type = file_info 

    cache_path = None 

    if item_type == 'image':
        cache_path = create_thumbnail(item_path, 'static/thumbnails')  
        print(f"Cache created for file: {item_path}, Type: {item_type}")
    elif item_type == 'video':
        cache_path = create_video_thumbnail(item_path, 'static/thumbnails')  
        print(f"Cache created for file: {item_path}, Type: {item_type}")

    elif item_type == 'directory':
        dir_size, total_images, total_videos = calculate_directory_size(item_path)
        print(f"Directory:{item_path}, Total Size: {dir_size}, Images:{total_images}, Videos: {total_videos}")
        conn = pool.get_connection()

        try:
           cursor = conn.cursor()  
           update_query = "UPDATE files SET size = %s,images = %s,videos = %s,lastupdate = now() WHERE item_path = %s"
        
           cursor.execute(update_query, (dir_size,total_images,total_videos,item_path))
        
           conn.commit()


        except mysql.connector.Error as err:
           print(f"Database error: {err}") 
    
        finally:
           if cursor:
               cursor.close() 
           if conn:
               conn.close()  


    else:
        print(f"Unknown type for file: {item_path}, setting mediacache to None")

    conn = pool.get_connection() 
    try:
        cursor = conn.cursor()
        update_query = """
        UPDATE files
        SET mediacache = %s, lastupdate = now()
        WHERE item_path = %s
        """
        cursor.execute(update_query, (cache_path, item_path))  
        conn.commit()  
        rows_affected = cursor.rowcount





    except mysql.connector.Error as err:
        print(f"Database error during cache update: {err}") 
    finally:
        if conn:
            conn.close() 






def mark_as_pending(path):
    connection = pool.get_connection()
    cursor = connection.cursor()
    pattern = path+'/%'
    cursor.execute("DELETE FROM files WHERE item_path like %s and retain is null", (pattern,))
    connection.commit();
    cursor.close()
    connection.close()

def has_valid_childrennnnn(path):
    connection = pool.get_connection()
    cursor = connection.cursor()
    cursor.execute("SELECT COUNT(*) FROM files WHERE item_path LIKE %s", (path + '/%',))
    result = cursor.fetchone()[0]
    cursor.close()
    connection.close()
    return result > 0







@app.route('/settings', methods=['POST'])
def get_settings():
    if 'username' not in session:
        return redirect(url_for('login'))
    action = request.form.get('action')
    if action is None or action == 'get':
        connection = pool.get_connection()
        cursor = connection.cursor()
        cursor.execute("SELECT source_path, deleted_path, allow_register,unix_timestamp(now()) as curtime FROM settings")
        row = cursor.fetchone()
        if row:
            source_path, deleted_path, allow_register,curtime = row
            settings = {
                "source_path": source_path,
                "deleted_path": deleted_path,
                "allow_register": allow_register,
                "current_time": curtime
            }
        else:
            settings = {}
        cursor.close()
        connection.close()
        return jsonify(settings)
    else:
        source_path = request.form.get('source_path')
        deleted_path = request.form.get('deleted_path')
        allow_register = request.form.get('allow_register')

        connection = pool.get_connection()
        cursor = connection.cursor()

        update_query = """
        UPDATE settings
        SET source_path = %s, deleted_path = %s, allow_register = %s
        """
        cursor.execute(update_query, (source_path, deleted_path, allow_register))
        connection.commit()

        cursor.close()
        connection.close()

        return jsonify({"message": "Settings updated successfully"}), 200




















@app.route('/invalidate',methods=['POST'])
def invalidate_cache_route():
    if 'username' not in session:
        return redirect(url_for('login'))
    path = request.form.get('path')
    mark_as_pending(path)
    
    return 'Cache invalidated for path: {}'.format(path)



def create_video_thumbnail(video_path, cache_dir, timeout_duration=60):
    hash_value = generate_unique_hash(video_path)
    cache_file = f"{hash_value}.png"
    cache_path = os.path.join(cache_dir, cache_file)

    with thumbnail_lock:
        if os.path.exists(cache_path):
            return cache_path

        temp_cache_path = f"{cache_path}.tmp"
        if os.path.exists(temp_cache_path):
            return "pending"

        with open(temp_cache_path, 'w'):
            pass
    print('opened file')
    try:
        video_length_cmd = (
            f'ffprobe -v error -show_entries format=duration '
            f'-of default=noprint_wrappers=1:nokey=1 "{video_path}"'
        )
        video_length_str = subprocess.check_output(
            video_length_cmd, shell=True, timeout=timeout_duration
        ).strip()

        video_length = float(video_length_str)
        frame_time = video_length * 0.5

        extract_frame_cmd = (
            f'nice -n 10 ffmpeg -y -ss {frame_time} -i "{video_path}" '
            f'-frames:v 1 -vf "scale=300:300" "{cache_path}"'
        )

        subprocess.check_output(
            extract_frame_cmd, shell=True, timeout=timeout_duration
        )

        os.remove(temp_cache_path)

    except subprocess.TimeoutExpired:
        print(f"Timeout expired while creating thumbnail for {video_path}.")
        cache_path = "pending"

        if os.path.exists(temp_cache_path):
            os.remove(temp_cache_path)

    except Exception as e:
        print(f"An error occurred while creating thumbnail for {video_path}: {e}")
        cache_path = "fail"

        if os.path.exists(temp_cache_path):
            os.remove(temp_cache_path)

    return cache_path



def check_pending_cache():
    while True:
        pending_files = []
        conn = pool.get_connection()  
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT item_path, type FROM files WHERE mediacache = 'pending' order by type asc")
            pending_files = cursor.fetchall()  
        except mysql.connector.Error as err:
            print(f"Database error: {err}")  
        finally:
            if conn:
                conn.close()  

        if pending_files:
            for file_info in pending_files:
                if executor._work_queue.qsize() < MAX_CONCURRENT_THREADS:
                    executor.submit(create_cache, file_info) 

        time.sleep(1)






def start_cache_check_thread():
    cache_check_thread = threading.Thread(target=check_pending_cache)
    cache_check_thread.daemon = True  
    cache_check_thread.start()








def generate_unique_hash(data):
    return hashlib.sha256(data.encode()).hexdigest()

def create_placeholder(cache_dir):
    placeholder_name = ''.join(random.choices(string.ascii_lowercase + string.digits, k=16)) + ".png"
    placeholder_path = os.path.join(cache_dir, placeholder_name)

    if not os.path.exists(placeholder_path):
        with Image.new("RGB", (150, 150), color='gray') as placeholder:
            placeholder.save(placeholder_path)

    return placeholder_path

def create_thumbnail(image_path, cache_dir):
    ext = os.path.splitext(image_path)[1]
    cache_file = generate_unique_hash(image_path) + ext
    cache_path = os.path.join(cache_dir, cache_file)

    try:
        if not os.path.exists(cache_path):
            with Image.open(image_path) as img:
                img.thumbnail((150, 150))
                img.save(cache_path)
    except UnidentifiedImageError:
        cache_path = create_placeholder(cache_dir)

    return cache_path







def sort_key(x):
	try:
		return -x["size"]
	except KeyError:
		return 0








def list_files(directory, depth=0, current_depth=0):
    if 'username' not in session:
        return redirect(url_for('login'))
    if current_depth > depth:
        return []

    full_path = os.path.join('', directory)
    files = []
    directories = []

    conn = pool.get_connection()
    try:
        cursor = conn.cursor()

        for item in os.listdir(full_path):
            item_path = os.path.join(full_path, item)
#            print(item)
#            print(item_path)
            if "$" in item_path:
                print('skipping ' + item)
                continue

            cursor.execute("SELECT name, type, size, mediacache, images, videos, lastupdate, retain FROM files WHERE item_path = %s", (item_path,))
            cached_data = cursor.fetchone()

            if cached_data:
                name, file_type, file_size, mediacache, images, videos, lastupdate,retain = cached_data
                # Ensure lastupdate is a datetime object
                if lastupdate and not isinstance(lastupdate, datetime):
                    last_update_time = datetime.strptime(lastupdate, '%Y-%m-%d %H:%M:%S')
                else:
                    last_update_time = lastupdate
                try:
                    file_mod_time = datetime.fromtimestamp(os.path.getmtime(item_path))
                except:
                    file_mod_time = datetime.fromtimestamp(1)

                if last_update_time and file_mod_time > last_update_time:
                    # File has been modified after the cached data was last updated, ignore cache
                    print(name+' has been changed')
                    cached_data = None

            if cached_data:
                name, file_type, file_size, mediacache, images, videos, lastupdate,retain = cached_data
                item_info = {
                    'name': name,
                    'type': file_type,
                    'size': file_size,
                    'cachefile': mediacache,
                    'images': images,
                    'videos': videos,
                    'retain': retain,
                    'cachepath': os.path.join('static', 'thumbnails', mediacache) if mediacache else None
                }
            else:
                item_info = {
                    'name': item,
                    'type': 'directory' if os.path.isdir(item_path) else 'file',
                    'size': os.path.getsize(item_path) if os.path.isfile(item_path) else None,
                }

                if os.path.isdir(item_path):
                    if current_depth < depth:
                        # Recursive call if within the depth limit
                        item_info['contents'] = []
                    else:
                        item_info['contents'] = []
                elif os.path.isfile(item_path):
                    if item_path.endswith(('.mp4', '.avi', '.mkv', '.mov', '.mpeg', '.mpg')):
                        item_info['type'] = 'video'
                        item_info['cachefile'] = 'pending'
                        item_info['cachepath'] = 'pending'
                    elif item_path.endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg', '.jfif')):
                        item_info['type'] = 'image'
                        item_info['cachefile'] = 'pending'
                        item_info['cachepath'] = 'pending'
                    else:
                        item_info['type'] = 'file'

                cursor.execute('''
                    INSERT INTO files (item_path, name, type, size, mediacache, lastupdate)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                    ON DUPLICATE KEY UPDATE
                    name = VALUES(name), type = VALUES(type), size = VALUES(size), mediacache = VALUES(mediacache), lastupdate = NOW()
                ''', (item_path, item_info['name'], item_info['type'], item_info['size'], item_info.get('cachefile', 'pending')))
                conn.commit()

            if item_info['type'] == 'directory':
                directories.append(item_info)
            else:
                if item_info['size'] is None:
                    item_info["size"] = 0
                files.append(item_info)
        files = sorted(files, key=lambda x: (-x['size'] if x['size'] is not None else 0, x['name'].lower()))
        directories = sorted(directories, key=lambda x: -x["size"] if x["size"] is not None else 0)

    except mysql.connector.Error as err:
        f = json.dumps(files)
        d = json.dumps(directories)
        print(f"Database error: {err} dir {directory} \n f {f} \n d {d}")

    finally:
        if conn:
            conn.close()

    return files + directories
#    return jsonify({files, directories})



















def get_available_space(directory):
    """Get available space in bytes for the given directory."""
    statvfs = os.statvfs(directory)
    return statvfs.f_frsize * statvfs.f_bavail

def send_to_deleted(file):
    print(file)
    if not os.path.exists(file):
        raise FileNotFoundError(f"The file {file} does not exist.")
    
    file_abs_path = os.path.abspath(file)
    garbage_abs_path = os.path.abspath(garbage_dir)
    
    file_relative_path = os.path.relpath(file_abs_path, '/')
    target_path = os.path.join(garbage_abs_path, file_relative_path)
    target_dir = os.path.dirname(target_path)
    
    os.makedirs(target_dir, exist_ok=True)
    
    if os.path.exists(target_path):
        print(f"File {target_path} already exists in the garbage directory. Ignoring move operation.")
        return

    file_size = os.path.getsize(file_abs_path)
    available_space = get_available_space(garbage_abs_path)
    
    if available_space < file_size:
        print(f"Not enough space in the garbage directory to move {file_abs_path}. Required: {file_size}, Available: {available_space}")
        return
    
    shutil.move(file_abs_path, target_path)
    print(f"Moved {file_abs_path} to {target_path}")





@app.route('/remove', methods=['POST'])
def remove_route():
    if 'username' not in session:
        return redirect(url_for('login'))
    target_file = request.form.get('file')
    send_to_deleted(target_file)	




@app.route('/start', methods=['POST'])
def list_files_route():
    if 'username' not in session:
        return redirect(url_for('login'))
    directory = request.form['directory']
    directory_contents = list_files(directory)
    return jsonify({'files': directory_contents})






@app.route('/')
def index():
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template('index.html', username=session['username'])








@app.route('/retain', methods=['POST'])
def route_retain():
    if 'username' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        path = request.form.get('path')

        if not path:
            return jsonify({'error': 'path parameter is required'}), 400

        conn = pool.get_connection()
        try:
            cursor = conn.cursor()

            cursor.execute("SELECT retain FROM files WHERE item_path = %s", (path,))
            result = cursor.fetchone()

            if result is None:
                return jsonify({'error': 'Path not found in database'}), 404

            current_retain = result[0]

            if current_retain is None:
                new_retain = 'retain'
            else:
                new_retain = None

            cursor.execute("UPDATE files SET retain = %s,lastupdate = now() WHERE item_path = %s", (new_retain, path))
            conn.commit()

            response = {'retain': new_retain}

            return jsonify(response)

        except mysql.connector.Error as err:
            return jsonify({'error': str(err)}), 500

        finally:
            if conn:
                conn.close()







@app.route('/query', methods=['GET', 'POST'])
def query_route():
    if 'username' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        directory = request.form.get('directory')
        lastupd = request.form.get('lastupdate') 
        curtime = None
        if not directory:
            return jsonify({'error': 'Directory parameter is required'}), 400

        conn = pool.get_connection()
        files = []  
        try:
            cursor = conn.cursor()
            query = "SELECT * FROM files WHERE item_path LIKE %s AND mediacache != 'pending' and unix_timestamp(lastupdate) > "+lastupd
          #  print(query)
            cursor.execute(query, (f"%{directory}%",))  
            raw_files = cursor.fetchall()  

            column_names = [col[0] for col in cursor.description]  
            files = [dict(zip(column_names, row)) for row in raw_files]  

        finally:
            query = "SELECT unix_timestamp(now())"
            cursor.execute(query)  
            curtime = cursor.fetchone()[0]  
            conn.close()

        return jsonify({'directory': directory, 'files': files,'time':curtime})

    return jsonify({'message': 'This endpoint only supports POST'}), 405








@app.route('/querydir', methods=['GET', 'POST'])
def querydir_route():
    if 'username' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        directory = request.form.get('directory')

        if not directory:
            return jsonify({'error': 'Directory parameter is required'}), 400

        conn = pool.get_connection()
        files = []  
        try:
            cursor = conn.cursor()
            query = "SELECT * FROM files WHERE item_path LIKE %s AND type = 'directory' and size is not NULL"
            cursor.execute(query, (f"%{directory}%",))  
            raw_files = cursor.fetchall()  

            column_names = [col[0] for col in cursor.description]  
            files = [dict(zip(column_names, row)) for row in raw_files]  

        finally:
            conn.close()

        return jsonify({'directory': directory, 'files': files})

    return jsonify({'message': 'This endpoint only supports POST'}), 405













@app.route('/move', methods=['GET', 'POST'])
def move_file():
    if 'username' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        file_path = request.form.get('file')
        destination_dir = request.form.get('destination')

        if not file_path or not destination_dir:
            return jsonify({'status': 'fail', 'reason': 'Missing file or destination parameter'}), 400

        if not os.path.isfile(file_path):
            return jsonify({'status': 'fail', 'reason': f"File '{file_path}' does not exist"}), 404

        if not os.path.isdir(destination_dir):
            return jsonify({'status': 'fail', 'reason': f"Destination '{destination_dir}' does not exist"}), 404
        if not os.access(destination_dir, os.W_OK):
            return jsonify({'status': 'fail', 'reason': f"Cannot write to destination '{destination_dir}'"}), 403

        file_name = os.path.basename(file_path)
        new_file_path = os.path.join(destination_dir, file_name)

        try:
            shutil.copy(file_path, new_file_path)
        except Exception as e:
            return jsonify({'status': 'fail', 'reason': f"Failed to copy file: {str(e)}"}), 500

        if not filecmp.cmp(file_path, new_file_path, shallow=False):
            return jsonify({'status': 'fail', 'reason': 'Files are not identical after copy'}), 500

        try:
            os.remove(file_path)
        except Exception as e:
            return jsonify({'status': 'fail', 'reason': f"Failed to remove original file: {str(e)}"}), 500

        return jsonify({'status': 'OK', 'newfile': new_file_path})

    return jsonify({'status': 'fail', 'reason': 'Invalid request method'}), 405




@app.route('/login', methods=['GET', 'POST'])
def login():
    a_register = None
    if request.method == 'POST':
        username = request.form.get('username') 
        password = request.form.get('password')

        if not username or not password:
            flash('Username and password are required', 'danger')
            return redirect(url_for('login'))

        conn = pool.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
            user = cursor.fetchone() 
            cursor.execute("SELECT allow_register FROM settings")
            a_register = cursor.fetchone()[0] 
            print(a_register)
            if user and check_password_hash(user[2], password): 
                session['username'] = user[1]
                return redirect(url_for('index'))
            else:
                flash('Invalid username or password', 'danger')
                return redirect(url_for('login'))

        except mysql.connector.Error as err:
            flash(f"Database error: {err}", 'danger')
            return redirect(url_for('login'))

        finally:
            conn.close() 
    else:
        try:
            conn = pool.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT allow_register FROM settings")
            a_register = cursor.fetchone()[0] 
        except mysql.connector.Error as err:
            flash(f"Database error: {err}", 'danger')
            print(f"Database error: {err}", 'danger')
            return redirect(url_for('login'))
        finally:
            conn.close() 

    return render_template('login.html',allow_register=a_register) 







def is_image(file_path):
    _, ext = os.path.splitext(file_path)
    return ext.lower() in IMAGE_EXTENSIONS

def is_video(file_path):
    _, ext = os.path.splitext(file_path)
    return ext.lower() in VIDEO_EXTENSIONS

def calculate_directory_size_old(root_dir, max_depth=5):
    total_size = 0
    image_count = 0
    video_count = 0

    print("calculating ",root_dir)
    def traverse_directory(current_dir, current_depth):
        nonlocal total_size, image_count, video_count

        if current_depth > max_depth:
            return

        for item in os.listdir(current_dir):
            item_path = os.path.join(current_dir, item)

            if os.path.isfile(item_path):
                file_size = os.path.getsize(item_path)
                total_size += file_size

                if is_image(item_path):
                    image_count += 1
                elif is_video(item_path):
                    video_count += 1
            elif os.path.isdir(item_path):
                traverse_directory(item_path, current_depth + 1)

    traverse_directory(root_dir, 1)

    return total_size, image_count, video_count





def get_lock_file_path(dir_path):
    lock_file_name = f".lock_mediamanager_{hash(dir_path)}"
    return os.path.join(tempfile.gettempdir(), lock_file_name)

def is_locked(dir_path):
    lock_file_path = get_lock_file_path(dir_path)
    return os.path.exists(lock_file_path)

def create_lock(dir_path):
    lock_file_path = get_lock_file_path(dir_path)
    with open(lock_file_path, 'w') as lock_file:
        lock_file.write("locked")

def release_lock(dir_path):
    lock_file_path = get_lock_file_path(dir_path)
    if os.path.exists(lock_file_path):
        os.remove(lock_file_path)

def calculate_directory_size_unsafe(root_dir, max_depth=5):
    if is_locked(root_dir):
        print(f"Directory '{root_dir}' is already being processed.")
        return None, None, None

    create_lock(root_dir)

    try:
        total_size = 0
        image_count = 0
        video_count = 0

        def traverse_directory(current_dir, current_depth):
            nonlocal total_size, image_count, video_count

            if current_depth > max_depth:
                return

            for item in os.listdir(current_dir):
                item_path = os.path.join(current_dir, item)

                if os.path.isfile(item_path):
                    file_size = os.path.getsize(item_path)
                    total_size += file_size

                    if is_image(item_path):
                        image_count += 1
                    elif is_video(item_path):
                        video_count += 1
                elif os.path.isdir(item_path):
                    traverse_directory(item_path, current_depth + 1)

        traverse_directory(root_dir, 1)

        return total_size, image_count, video_count
    
    finally:
        release_lock(root_dir)











@contextmanager
def directory_lock(dir_path):
    with global_lock:
        if dir_path not in directory_locks:
            directory_locks[dir_path] = threading.Lock()

    dir_lock = directory_locks[dir_path]

    if dir_lock.acquire(blocking=False):  
        try:
            yield  
        finally:
            dir_lock.release()
    else:
        raise Exception(f"Directory '{dir_path}' is already being processed.")

def calculate_directory_size(root_dir, max_depth=5):
    """
    Calculate the total size of files in a directory and count the total number of image and video files.
    Stops traversal after reaching the maximum specified depth.
    """
    try:
        with directory_lock(root_dir):  
            total_size = 0
            image_count = 0
            video_count = 0

            def traverse_directory(current_dir, current_depth):
                nonlocal total_size, image_count, video_count

                if current_depth > max_depth:
                    return

                for item in os.listdir(current_dir):
                    item_path = os.path.join(current_dir, item)

                    if os.path.isfile(item_path):
                        total_size += os.path.getsize(item_path)

                        if is_image(item_path):
                            image_count += 1
                        elif is_video(item_path):
                            video_count += 1
                    elif os.path.isdir(item_path):
                        traverse_directory(item_path, current_depth + 1)

            traverse_directory(root_dir, 1)

            return total_size, image_count, video_count

    except Exception as e:
        print(f"Error: {e}")
        return None, None, None













@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))





@app.route('/register', methods=['POST'])
def register():
    username = request.form.get('username', '')  
    password = request.form.get('password', '')  

    if not username or not password:
        flash("Username and password are required", 'danger')
        return redirect(url_for('register'))  

    hashed_password = generate_password_hash(password)

    conn = pool.get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (username, password) VALUES (%s, %s)",
            (username, hashed_password)
        )
        conn.commit() 
        flash("User registered successfully!", 'success') 
    except mysql.connector.IntegrityError:
        flash("Username already exists!", 'danger') 
    except mysql.connector.Error as err:
        flash(f"Database error: {err}", 'danger')  
    finally:
        conn.close()  

    return redirect(url_for('login'))  







if __name__ == '__main__':
#    init_db() 
    start_cache_check_thread()
    os.environ['FLASK_ENV'] = 'production'
    app.run(debug=False,host='0.0.0.0')

