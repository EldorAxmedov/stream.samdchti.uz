import os
import json
import yaml
import secrets
import jwt
import datetime
from flask import Flask, request, jsonify
from functools import wraps

app = Flask(__name__)

# === CONFIG ===
CONFIG_DIR = 'config'
CONFIG_FILE = os.path.join(CONFIG_DIR, 'mediamtx.yml')
TOKENS_FILE = os.path.join(CONFIG_DIR, 'tokens.json')
ROOMS_FILE = os.path.join(CONFIG_DIR, 'rooms.json')
USERS_FILE = os.path.join(CONFIG_DIR, 'users.json')
STREAM_BASE = 'https://stream.samdchti.uz'

app.config['SECRET_KEY'] = 'super-secret-key'  # Change this in production!

os.makedirs(CONFIG_DIR, exist_ok=True)
# === Foydalanuvchi fayllari ===
def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE) as f:
        return json.load(f)

def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=4)

# === UTIL FUNCTIONS ===
def get_tokens():
    if not os.path.exists(TOKENS_FILE):
        return {}
    with open(TOKENS_FILE) as f:
        return json.load(f)

def save_tokens(tokens):
    with open(TOKENS_FILE, 'w') as f:
        json.dump(tokens, f, indent=4)

def get_users():
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE) as f:
        return json.load(f)

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {'hlsAddress': ':8888', 'hlsPartDuration': '1s', 'hlsSegmentDuration': '4s', 'paths': {}}
    with open(CONFIG_FILE) as f:
        return yaml.safe_load(f)

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        yaml.dump(config, f)

def get_rooms():
    if not os.path.exists(ROOMS_FILE):
        return {}
    with open(ROOMS_FILE) as f:
        return json.load(f)

def save_rooms(rooms):
    with open(ROOMS_FILE, 'w') as f:
        json.dump(rooms, f, indent=4)

# === AUTH DECORATOR ===
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            if auth_header.startswith("Bearer "):
                token = auth_header.split(" ")[1]

        if not token:
            return jsonify({'error': 'Token required'}), 401

        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401

        return f(*args, **kwargs)
    return decorated

# === Register ===
@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400

    users = load_users()
    if username in users:
        return jsonify({'error': 'Username already exists'}), 400

    users[username] = password
    save_users(users)
    return jsonify({'message': 'User registered successfully'})
# === AUTH ENDPOINTS ===
@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    users = get_users()

    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400

    if username not in users or users[username] != password:
        return jsonify({'error': 'Invalid credentials'}), 401

    token = jwt.encode({
        'username': username,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=12)
    }, app.config['SECRET_KEY'], algorithm="HS256")

    return jsonify({'token': token})

# === CAMERA API ===
@app.route('/api/home', methods=['GET'])
def list_rooms():
    rooms = get_rooms()
    return jsonify({'rooms': list(rooms.keys())})

@app.route('/api/home/cameras', methods=['GET'])
@token_required
def all_room_cameras():
    return jsonify(get_rooms())

@app.route('/api/add', methods=['POST'])
@token_required
def add_camera():
    data = request.json
    name, url, building, room = data.get('name'), data.get('url'), data.get('building'), data.get('room')
    if not name or not url or not room or not building:
        return jsonify({'error': 'name, url, room, and building are required'}), 400

    config = load_config()
    config.setdefault('paths', {})[name] = {
        'source': url,
        'rtspTransport': 'tcp',
        'sourceOnDemand': True,
        'sourceOnDemandCloseAfter': '10s'
    }
    save_config(config)

    full_room = f"{building}/{room}"
    rooms = get_rooms()
    rooms.setdefault(full_room, [])
    if name not in rooms[full_room]:
        rooms[full_room].append(name)
    save_rooms(rooms)

    return jsonify({'message': f'Camera {name} added to room {full_room}'})

@app.route('/api/delete', methods=['POST'])
@token_required
def delete_camera():
    name = request.json.get('name')
    if not name:
        return jsonify({'error': 'name is required'}), 400

    config = load_config()
    paths = config.get('paths', {})
    paths.pop(name, None)
    save_config(config)

    tokens = get_tokens()
    tokens = {k: v for k, v in tokens.items() if v != name}
    save_tokens(tokens)

    rooms = get_rooms()
    for room in rooms.values():
        if name in room:
            room.remove(name)
    save_rooms(rooms)

    return jsonify({'message': f'Camera {name} deleted successfully'})

@app.route('/api/token/<name>', methods=['GET'])
@token_required
def get_or_create_token(name):
    tokens = get_tokens()
    for token, cam in tokens.items():
        if cam == name:
            return jsonify({'token': token})
    token = secrets.token_hex(8)
    tokens[token] = name
    save_tokens(tokens)
    return jsonify({'token': token})

@app.route('/api/camera/rename', methods=['POST'])
@token_required
def rename_camera():
    data = request.json
    old_name = data.get('old_name')
    new_name = data.get('new_name')
    if not old_name or not new_name:
        return jsonify({'error': 'old_name and new_name are required'}), 400

    config = load_config()
    paths = config.get('paths', {})
    if old_name not in paths:
        return jsonify({'error': 'Old camera not found'}), 404

    paths[new_name] = paths.pop(old_name)
    save_config(config)

    tokens = get_tokens()
    for token, cam in tokens.items():
        if cam == old_name:
            tokens[token] = new_name
    save_tokens(tokens)

    rooms = get_rooms()
    for room, cams in rooms.items():
        if old_name in cams:
            cams.remove(old_name)
            cams.append(new_name)
    save_rooms(rooms)

    return jsonify({'message': f'Renamed camera {old_name} → {new_name}'})

@app.route('/api/room/rename', methods=['POST'])
@token_required
def rename_room():
    data = request.json
    old_room = data.get('old_name')
    new_room = data.get('new_name')
    if not old_room or not new_room:
        return jsonify({'error': 'old_name and new_name are required'}), 400

    rooms = get_rooms()
    if old_room not in rooms:
        return jsonify({'error': 'Old room not found'}), 404

    rooms[new_room] = rooms.pop(old_room)
    save_rooms(rooms)
    return jsonify({'message': f'Renamed room {old_room} → {new_room}'})

@app.route('/api/buildings', methods=['GET'])
@token_required
def get_all_buildings():
    rooms = get_rooms()
    config = load_config()
    paths = config.get('paths', {})

    result = {}
    for full_room_name, camera_list in rooms.items():
        try:
            building, room = full_room_name.split("/", 1)
        except ValueError:
            continue  # Skip invalid entries

        if building not in result:
            result[building] = {}
        result[building][room] = []

        for cam_name in camera_list:
            cam_url = paths.get(cam_name, {}).get('source', '')
            result[building][room].append({
                'name': cam_name,
                'url': cam_url
            })

    return jsonify(result)


@app.route('/api/building/<building_name>', methods=['GET'])
@token_required
def get_building_rooms(building_name):
    rooms = get_rooms()
    config = load_config()
    paths = config.get('paths', {})

    result = {}
    for full_room, cams in rooms.items():
        if full_room.startswith(f"{building_name}/"):
            # Extract room name only (after slash)
            room_name = full_room.split("/", 1)[1]
            result[room_name] = []
            for cam in cams:
                result[room_name].append({
                    'name': cam,
                    'url': paths.get(cam, {}).get('source', '')
                })

    if not result:
        return jsonify({'error': 'Building not found'}), 404

    return jsonify({'rooms': result})


@app.route('/api/building/<building_name>/<room_name>', methods=['GET'])
@token_required
def get_specific_room_in_building(building_name, room_name):
    rooms = get_rooms()
    config = load_config()
    paths = config.get('paths', {})

    full_room_name = f"{building_name}/{room_name}"

    if full_room_name not in rooms:
        return jsonify({'error': 'Room not found in this building'}), 404

    cameras = rooms[full_room_name]
    result = {
        full_room_name: [
            {
                'name': cam,
                'url': paths.get(cam, {}).get('source', '')
            }
            for cam in cameras
        ]
    }

    return jsonify(result)


@app.route('/api/embed/<name>', methods=['GET'])
@token_required
def embed_single_iframe(name):
    tokens = get_tokens()
    for token, cam in tokens.items():
        if cam == name:
            current_token = token
            break
    else:
        current_token = secrets.token_hex(8)
        tokens[current_token] = name
        save_tokens(tokens)

    iframe_code = f'<iframe src="https://mediamtx.samdchti.uz/embed_single?token={current_token}" width="800" height="450" style="border:none;"></iframe>'
    return jsonify({
        'camera': name,
        'token': current_token,
        'iframe_code': iframe_code
    })

@app.route('/api/generate-token/<name>', methods=['GET'])
@token_required
def generate_token(name):
    tokens = get_tokens()
    for token, cam in tokens.items():
        if cam == name:
            return jsonify({'camera': name, 'token': token})

    new_token = secrets.token_hex(8)
    tokens[new_token] = name
    save_tokens(tokens)
    return jsonify({'camera': name, 'token': new_token})

if __name__ == '__main__':
    app.run(debug=True)