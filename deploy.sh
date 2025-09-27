#!/bin/bash
#
# This script deploys or uninstalls a robust, multi-container File Proxy System.
# It features properly decoupled install/uninstall logic to prevent errors.
#
set -e

# --- Static Configuration ---
PROJECT_DIR="file-proxy-system"
CONFIG_FILE="config.ini"
ENV_FILE=".env"
DOMAIN="fps.safepass.icu"
LETSENCRYPT_EMAIL="schmidt.gertrud.78@gmail.com"

# --- Colors for beautiful output ---
C_RESET='\033[0m'
C_RED='\033[0;31m'
C_GREEN='\033[0;32m'
C_YELLOW='\033[0;33m'
C_BLUE='\033[0;34m'

# --- Helper Functions ---
log() {
    echo -e "${C_BLUE}==>${C_RESET} ${1}"
}
log_success() {
    echo -e "${C_GREEN}✓ SUCCESS:${C_RESET} ${1}"
}
log_error() {
    echo -e "${C_RED}✗ ERROR:${C_RESET} ${1}" >&2
    exit 1
}

# --- Core Logic Functions ---
show_usage() {
    echo "Usage: $0 [install|uninstall]"
    echo "  install   (Default) Deploys or updates the file proxy system."
    echo "  uninstall Completely removes the system, its data, and configuration."
    exit 1
}

check_dependencies() {
    log "Checking for dependencies..."
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed. Please install Docker to continue."
    fi
    if ! docker info &> /dev/null; then
        log_error "The Docker daemon is not running. Please start Docker and try again."
    fi
    log_success "Dependencies are satisfied."
}

handle_config() {
    if [ -f "$CONFIG_FILE" ] && [ -f "$ENV_FILE" ]; then
        log "Configuration files found. Skipping setup."
        return
    fi

    log "--- First-Time Setup ---"
    read -p "Enter the dashboard admin username: " ADMIN_USERNAME
    while true; do
        read -s -p "Enter the dashboard admin password: " ADMIN_PASSWORD; echo
        read -s -p "Confirm password: " ADMIN_PASSWORD_CONFIRM; echo
        [ "$ADMIN_PASSWORD" = "$ADMIN_PASSWORD_CONFIRM" ] && break
        echo "Passwords do not match. Please try again."
    done

    log "Please provide your Cloudflare API Token (DNS Edit permission) for automatic SSL."
    read -s -p "Enter Cloudflare API Token: " CLOUDFLARE_API_TOKEN; echo

    log "Generating configuration files..."
    cat <<EOF > "$CONFIG_FILE"
# Public configuration
DOMAIN="$DOMAIN"
LETSENCRYPT_EMAIL="$LETSENCRYPT_EMAIL"
EOF
    FLASK_SECRET_KEY=$(openssl rand -hex 16)
    # FIX: Added ADMIN_USERNAME to .env file to make it available to the container
    cat <<EOF > "$ENV_FILE"
# Secret values
ADMIN_USERNAME="$ADMIN_USERNAME"
ADMIN_PASSWORD="$ADMIN_PASSWORD"
SECRET_KEY="$FLASK_SECRET_KEY"
CLOUDFLARE_DNS_API_TOKEN="$CLOUDFLARE_API_TOKEN"
EOF
    log_success "Configuration saved to $CONFIG_FILE and $ENV_FILE."
}

generate_all_files() {
    log "Creating project directory structure..."
    mkdir -p proxy/templates traefik cron

    log "Creating Traefik (SSL) configuration..."
    touch traefik/acme.json
    chmod 600 traefik/acme.json

    log "Creating core application files..."

    cat <<'EOF' > proxy/app.py
import os
import re
import threading
import uuid
from datetime import datetime
from flask import Flask, send_from_directory, abort, render_template, request, redirect, url_for, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import psutil
import requests

# --- App Initialization & Config ---
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'default-secret-key-for-dev')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////data/proxy.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
DOWNLOADS_DIR = '/data/downloads'

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- Thread-safe Global State for Download Tracking ---
active_downloads = {}
downloads_lock = threading.Lock()

# --- Database Models ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)

class Setting(db.Model):
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.String(150), nullable=False)

class DownloadLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), unique=True, nullable=False)
    remote_url = db.Column(db.String(2048), nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- Authentication Routes ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username')).first()
        if user and check_password_hash(user.password, request.form.get('password')):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid username or password')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# --- Dashboard & API Routes ---
@app.route('/')
@login_required
def dashboard():
    return render_template('dashboard.html')

@app.route('/api/stats')
@login_required
def api_stats():
    stored_files, total_stored_size = [], 0
    if os.path.exists(DOWNLOADS_DIR):
        for f in os.listdir(DOWNLOADS_DIR):
            file_path = os.path.join(DOWNLOADS_DIR, f)
            if os.path.isfile(file_path) and not f.endswith('.tmp'):
                size = os.path.getsize(file_path)
                stored_files.append({"name": f, "size": size})
                total_stored_size += size
    
    total_traffic = db.session.query(db.func.sum(DownloadLog.size_bytes)).scalar() or 0
    with downloads_lock:
        current_downloads = active_downloads.copy()

    return jsonify({
        "system": {"cpu_percent": psutil.cpu_percent(), "memory_percent": psutil.virtual_memory().percent},
        "proxy": {
            "active_downloads": current_downloads,
            "stored_files": sorted(stored_files, key=lambda x: x['name']),
            "total_stored_size": total_stored_size,
            "total_traffic": total_traffic,
        }
    })

@app.route('/api/proxy', methods=['POST'])
@login_required
def start_proxy_download():
    remote_url = request.json.get('url')
    if not remote_url:
        return jsonify({"error": "URL is required"}), 400

    try:
        with requests.get(remote_url, stream=True, timeout=10) as r:
            r.raise_for_status()
            unsafe_filename = get_filename_from_headers(r.headers) or remote_url.split('/')[-1].split('?')[0]
            if not unsafe_filename:
                 return jsonify({"error": "Could not determine filename from URL"}), 400
            
            filename = secure_filename(unsafe_filename)
            total_size = int(r.headers.get('content-length', 0))

        if DownloadLog.query.filter_by(filename=filename).first():
            return jsonify({"message": f"File '{filename}' already exists or is queued."}), 200

        log_entry = DownloadLog(filename=filename, remote_url=remote_url, size_bytes=total_size)
        db.session.add(log_entry)
        db.session.commit()

        thread = threading.Thread(target=download_thread_target, args=(remote_url, filename, total_size))
        thread.start()
        return jsonify({"message": f"Download for '{filename}' started."}), 202

    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Failed to connect to remote source: {e}"}), 502
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": f"File '{filename}' already exists."}), 409
    except Exception as e:
        return jsonify({"error": f"An internal error occurred: {e}"}), 500

@app.route('/api/files/<filename>', methods=['DELETE'])
@login_required
def delete_file(filename):
    safe_filename = secure_filename(filename)
    log_entry = DownloadLog.query.filter_by(filename=safe_filename).first_or_404()
    
    file_path = os.path.join(DOWNLOADS_DIR, safe_filename)
    if os.path.exists(file_path):
        os.remove(file_path)

    db.session.delete(log_entry)
    db.session.commit()
    return jsonify({"success": True}), 200

@app.route('/api/settings', methods=['GET', 'POST'])
@login_required
def manage_settings():
    setting = Setting.query.filter_by(key='cleanup_interval').first()
    if request.method == 'POST':
        interval = request.json.get('cleanup_interval')
        if interval and interval.isdigit():
            setting.value = str(interval)
            db.session.commit()
    return jsonify({"cleanup_interval": setting.value})

# --- File Proxy & Download Logic ---

def get_filename_from_headers(headers):
    if cd := headers.get('content-disposition'):
        if filenames := re.findall('filename="(.+?)"', cd):
            return filenames[0]
    return None

def download_thread_target(url, filename, total_size):
    unique_id = uuid.uuid4().hex
    temp_filepath = os.path.join(DOWNLOADS_DIR, f"{filename}.{unique_id}.tmp")
    final_filepath = os.path.join(DOWNLOADS_DIR, filename)
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)

    try:
        with downloads_lock:
            active_downloads[filename] = {"size": total_size, "progress": 0}
        
        with requests.get(url, stream=True, timeout=300) as r: # Long timeout for big files
            r.raise_for_status()
            with open(temp_filepath, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
                    with downloads_lock:
                        if filename in active_downloads:
                            active_downloads[filename]['progress'] += len(chunk)
        
        os.rename(temp_filepath, final_filepath) # Atomic operation

    except Exception as e:
        print(f"Error downloading {filename}: {e}")
        if os.path.exists(temp_filepath):
            os.remove(temp_filepath)
    finally:
        with downloads_lock:
            if filename in active_downloads:
                del active_downloads[filename]

# FIX: Hardened download endpoint against directory traversal
@app.route('/download/<path:filename>')
def download_file(filename):
    safe_filename = secure_filename(filename)
    
    # Additional security: ensure filename doesn't contain path separators
    if '/' in safe_filename or '\\' in safe_filename or '..' in safe_filename:
        abort(400, "Invalid filename")
    
    if not DownloadLog.query.filter_by(filename=safe_filename).first():
        abort(404, "File not found in proxy records.")
    
    file_path = os.path.join(DOWNLOADS_DIR, safe_filename)
    if not os.path.exists(file_path):
        abort(404, "Physical file not found on disk.")
    
    return send_from_directory(DOWNLOADS_DIR, safe_filename, as_attachment=True)

# --- Initial Setup ---
# FIX: Implemented fcntl file lock to prevent database init race condition
def setup_database(app):
    # This import is scoped locally as fcntl is not available on Windows
    import fcntl
    lock_file = '/data/db_init.lock'
    
    with app.app_context():
        try:
            with open(lock_file, 'w') as f:
                # Get an exclusive, non-blocking lock
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                
                db.create_all()
                
                # Create admin user if it doesn't exist
                if not User.query.first():
                    username = os.environ.get('ADMIN_USERNAME')
                    password = os.environ.get('ADMIN_PASSWORD')
                    if username and password:
                        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
                        db.session.add(User(username=username, password=hashed_password))
                        db.session.commit()
                
                # Create default setting if it doesn't exist
                if not Setting.query.filter_by(key='cleanup_interval').first():
                    db.session.add(Setting(key='cleanup_interval', value='60'))
                    db.session.commit()

        except (IOError, IntegrityError) as e:
            # This will happen if another worker has already acquired the lock
            print(f"Database setup likely handled by another process: {e}")
            db.session.rollback()
        except Exception as e:
            print(f"An unexpected error occurred during DB setup: {e}")
            db.session.rollback()


# --- Main Entry ---
if __name__ == '__main__':
    setup_database(app)
    app.run(host='0.0.0.0', port=8000)
else: # For Gunicorn
    setup_database(app)
EOF

    cat <<'EOF' > proxy/templates/login.html
<!DOCTYPE html><html lang="en" class="h-full bg-slate-50"><head><meta charset="UTF-8"><title>Login - File Proxy System</title><meta name="viewport" content="width=device-width, initial-scale=1.0"><script src="https://cdn.tailwindcss.com"></script></head><body class="h-full"><div class="flex min-h-full flex-col items-center justify-center py-12 px-4 sm:px-6 lg:px-8"><div class="w-full max-w-md space-y-8"><div><svg class="mx-auto h-12 w-auto text-indigo-600" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 16.5V9.75m0 0l-3 3m3-3l3 3M6.75 19.5a4.5 4.5 0 01-1.41-8.775 5.25 5.25 0 0110.33-2.33 3 3 0 013.75 5.25c0 1.52-.962 2.824-2.372 3.295M15 19.5a4.5 4.5 0 01-9 0" /></svg><h2 class="mt-6 text-center text-3xl font-bold tracking-tight text-slate-900">File Proxy System</h2></div>{% with messages = get_flashed_messages() %}{% if messages %}<div class="rounded-md bg-red-50 p-4"><div class="flex"><div class="flex-shrink-0"><svg class="h-5 w-5 text-red-400" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z" clip-rule="evenodd" /></svg></div><div class="ml-3"><h3 class="text-sm font-medium text-red-800">{{ messages[0] }}</h3></div></div></div>{% endif %}{% endwith %}<form class="mt-8 space-y-6" method="POST"><div class="space-y-4 rounded-md shadow-sm"><div><label for="username" class="sr-only">Username</label><input id="username" name="username" type="text" autocomplete="username" required class="relative block w-full appearance-none rounded-md border border-slate-300 px-3 py-3 text-slate-900 placeholder-slate-500 focus:z-10 focus:border-indigo-500 focus:outline-none focus:ring-indigo-500 sm:text-sm" placeholder="Username"></div><div><label for="password" class="sr-only">Password</label><input id="password" name="password" type="password" autocomplete="current-password" required class="relative block w-full appearance-none rounded-md border border-slate-300 px-3 py-3 text-slate-900 placeholder-slate-500 focus:z-10 focus:border-indigo-500 focus:outline-none focus:ring-indigo-500 sm:text-sm" placeholder="Password"></div></div><div><button type="submit" class="group relative flex w-full justify-center rounded-md border border-transparent bg-indigo-600 py-3 px-4 text-sm font-semibold text-white hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2">Sign in</button></div></form></div></div></body></html>
EOF
    cat <<'EOF' > proxy/templates/dashboard.html
<!DOCTYPE html><html lang="en" class="h-full bg-slate-100"><head><meta charset="UTF-8"><title>Dashboard - File Proxy System</title><meta name="viewport" content="width=device-width, initial-scale=1.0"><script src="https://cdn.tailwindcss.com"></script><script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script></head><body class="h-full"><div x-data="dashboard()" x-init="init()" class="min-h-full"><header class="bg-white shadow-sm"><div class="mx-auto max-w-7xl py-4 px-4 sm:px-6 lg:px-8 flex justify-between items-center"><h1 class="text-xl font-bold tracking-tight text-slate-900">File Proxy Dashboard</h1><a href="/logout" class="text-sm font-medium text-slate-600 hover:text-indigo-600">Logout</a></div></header><main class="mx-auto max-w-7xl py-8 px-4 sm:px-6 lg:px-8"><div class="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4"><div class="overflow-hidden rounded-lg bg-white px-4 py-5 shadow sm:p-6"><dt class="truncate text-sm font-medium text-slate-500">CPU Usage</dt><dd class="mt-1 text-3xl font-semibold tracking-tight text-slate-900" x-text="stats.system ? `${stats.system.cpu_percent}%` : '...'"></dd></div><div class="overflow-hidden rounded-lg bg-white px-4 py-5 shadow sm:p-6"><dt class="truncate text-sm font-medium text-slate-500">Memory Usage</dt><dd class="mt-1 text-3xl font-semibold tracking-tight text-slate-900" x-text="stats.system ? `${stats.system.memory_percent}%` : '...'"></dd></div><div class="overflow-hidden rounded-lg bg-white px-4 py-5 shadow sm:p-6"><dt class="truncate text-sm font-medium text-slate-500">Total Traffic</dt><dd class="mt-1 text-3xl font-semibold tracking-tight text-slate-900" x-text="stats.proxy ? formatBytes(stats.proxy.total_traffic) : '...'"></dd></div><div class="overflow-hidden rounded-lg bg-white px-4 py-5 shadow sm:p-6"><dt class="truncate text-sm font-medium text-slate-500">Stored Files</dt><dd class="mt-1 text-3xl font-semibold tracking-tight text-slate-900" x-text="stats.proxy ? `${stats.proxy.stored_files.length} (${formatBytes(stats.proxy.total_stored_size)})` : '...'"></dd></div></div><div class="mt-8 grid grid-cols-1 items-start gap-8 lg:grid-cols-3"><div class="lg:col-span-2 space-y-8"><section class="bg-white shadow-sm ring-1 ring-slate-900/5 rounded-lg"><header class="p-4 sm:px-6"><h2 class="text-lg font-medium leading-6 text-slate-900">Proxy a New File</h2></header><form @submit.prevent="proxyUrl" class="p-4 sm:px-6 border-t border-slate-200 flex flex-col sm:flex-row gap-4"><input x-model="newUrl" type="url" placeholder="Enter remote file URL to proxy..." required class="flex-grow p-3 border rounded-md shadow-sm border-slate-300 focus:ring-indigo-500 focus:border-indigo-500"><button type="submit" class="rounded-md bg-indigo-600 px-4 py-3 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500">Proxy File</button></form></section><section class="bg-white shadow-sm ring-1 ring-slate-900/5 rounded-lg"><header class="p-4 sm:px-6"><h2 class="text-lg font-medium leading-6 text-slate-900">Stored Files</h2></header><div class="overflow-x-auto border-t border-slate-200"><table class="min-w-full"><thead class="bg-slate-50"><tr><th class="py-2 px-6 text-left text-sm font-semibold text-slate-600">Filename</th><th class="py-2 px-6 text-left text-sm font-semibold text-slate-600">Size</th><th class="py-2 px-6 text-right text-sm font-semibold text-slate-600">Actions</th></tr></thead><tbody class="bg-white divide-y divide-slate-200"><template x-for="file in stats.proxy?.stored_files || []" :key="file.name"><tr><td class="py-3 px-6 text-sm font-mono text-slate-700" x-text="file.name"></td><td class="py-3 px-6 text-sm text-slate-500" x-text="formatBytes(file.size)"></td><td class="py-3 px-6 text-right space-x-4"><a :href="`/download/${file.name}`" class="text-indigo-600 hover:text-indigo-800 font-semibold">Download</a><button @click="deleteFile(file.name)" class="text-red-500 hover:text-red-700 font-semibold">Delete</button></td></tr></template><template x-if="!stats.proxy || stats.proxy.stored_files.length === 0"><tr><td colspan="3" class="py-8 px-6 text-center text-sm text-slate-500">No files stored yet.</td></tr></template></tbody></table></div></section></div><div class="space-y-8"><section class="bg-white shadow-sm ring-1 ring-slate-900/5 rounded-lg"><header class="p-4 sm:px-6"><h2 class="text-lg font-medium leading-6 text-slate-900">Active Downloads</h2></header><div class="p-4 sm:px-6 border-t border-slate-200 space-y-4"><template x-if="stats.proxy && Object.keys(stats.proxy.active_downloads).length > 0"><template x-for="(dl, filename) in stats.proxy.active_downloads" :key="filename"><div><p class="truncate font-mono text-sm text-slate-700" x-text="filename"></p><div class="w-full bg-slate-200 rounded-full h-2.5 mt-1"><div class="bg-indigo-600 h-2.5 rounded-full" :style="{width: (dl.progress / (dl.size || 1) * 100) + '%'}"></div></div><p class="text-xs text-slate-500 text-right mt-1" x-text="`${formatBytes(dl.progress)} / ${formatBytes(dl.size)}`"></p></div></template></template><template x-if="!stats.proxy || Object.keys(stats.proxy.active_downloads).length === 0"><p class="text-center text-sm text-slate-500 py-4">No active downloads.</p></template></div></section><section class="bg-white shadow-sm ring-1 ring-slate-900/5 rounded-lg"><header class="p-4 sm:px-6"><h2 class="text-lg font-medium leading-6 text-slate-900">Settings</h2></header><div class="p-4 sm:px-6 border-t border-slate-200"><div id="alert-box" class="hidden mb-4 p-3 text-sm text-white rounded-md transition-opacity duration-300"></div><label class="block text-sm font-medium text-slate-700">File Cleanup Interval (minutes)</label><div class="mt-1 flex gap-2"><input x-model="settings.cleanup_interval" type="number" class="flex-grow p-2 border rounded-md shadow-sm border-slate-300"><button @click="saveSettings" class="rounded-md bg-emerald-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-emerald-500">Save</button></div></div></section></div></div></main></div><script>function dashboard(){return{stats:{},settings:{cleanup_interval:60},newUrl:"",init(){this.fetchData();this.fetchSettings();setInterval(()=>this.fetchData(),2500)},showAlert(message,isError=false){const el=document.getElementById('alert-box');el.textContent=message;el.className=`p-3 text-sm text-white rounded-md mb-4 ${isError?'bg-red-500':'bg-green-500'}`;el.classList.remove('hidden');setTimeout(()=>el.classList.add('hidden'),4000)},async fetchData(){try{const r=await fetch("/api/stats");this.stats=await r.json()}catch(e){console.error("Failed to fetch stats",e)}},async fetchSettings(){try{const r=await fetch("/api/settings");this.settings=await r.json()}catch(e){console.error("Failed to fetch settings",e)}},async proxyUrl(){if(!this.newUrl)return;try{const r=await fetch("/api/proxy",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({url:this.newUrl})});const result=await r.json();if(r.ok){this.showAlert(result.message||'Request accepted!');this.newUrl=""}else{this.showAlert(result.error||'An unknown error occurred.',true)}}catch(e){this.showAlert('Failed to submit URL.',true)}this.fetchData()},async deleteFile(filename){if(confirm(`Are you sure you want to delete '${filename}'? This cannot be undone.`)){await fetch(`/api/files/${filename}`,{method:"DELETE"});this.fetchData()}},async saveSettings(){await fetch("/api/settings",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(this.settings)});this.showAlert('Settings saved!');this.fetchSettings()},formatBytes(b,d=2){if(!+b)return"0 Bytes";const k=1024,i=Math.floor(Math.log(b)/Math.log(k));return`${parseFloat((b/Math.pow(k,i)).toFixed(d<0?0:d))} ${['B','KB','MB','GB','TB'][i]}`}}}
</script></body></html>
EOF

    cat <<'EOF' > proxy/Dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN pip install Flask Flask-SQLAlchemy Flask-Login gunicorn psutil requests Werkzeug
COPY . .
EXPOSE 8000
CMD ["gunicorn", "--workers", "4", "--bind", "0.0.0.0:8000", "app:app"]
EOF
    # FIX: Replaced cleanup script with a more robust, POSIX-compliant version
    cat <<'EOF' > cron/cleanup.sh
#!/bin/sh
set -e
DATA_DIR="/data"
DB_FILE="${DATA_DIR}/proxy.db"
DOWNLOADS_DIR="${DATA_DIR}/downloads"

if [ ! -f "${DB_FILE}" ]; then
    echo "Database not found, skipping cleanup."
    exit 0
fi

# Use sqlite3 to get cleanup interval, with a fallback of 60 if it fails
CLEANUP_MINUTES=$(sqlite3 "${DB_FILE}" "SELECT value FROM setting WHERE key = 'cleanup_interval';" 2>/dev/null || echo "60")

# Simple numeric check for sh (more portable than bash regex)
case "$CLEANUP_MINUTES" in
    ''|*[!0-9]*) CLEANUP_MINUTES=60 ;;
esac

echo "Running cleanup. Deleting files in ${DOWNLOADS_DIR} older than ${CLEANUP_MINUTES} minutes..."
# Redirect find's potential errors to null in case the directory is empty, but still proceed
find "${DOWNLOADS_DIR}" -type f -mmin "+${CLEANUP_MINUTES}" -not -name "*.tmp" -print -delete 2>/dev/null || true
echo "Cleanup finished."
EOF
    chmod +x cron/cleanup.sh
    cat <<'EOF' > cron/Dockerfile
FROM alpine:latest
RUN apk add --no-cache dcron sqlite
COPY cleanup.sh /usr/local/bin/cleanup.sh
RUN chmod +x /usr/local/bin/cleanup.sh
RUN echo "*/5 * * * * /usr/local/bin/cleanup.sh >> /var/log/cron.log 2>&1" > /etc/crontabs/root
RUN touch /var/log/cron.log
CMD crond -f -L /var/log/cron.log
EOF

    log_success "All project files have been generated."
}

install_system() {
    log "--- Starting File Proxy System Deployment ---"
    
    check_dependencies

    mkdir -p "$PROJECT_DIR"
    cd "$PROJECT_DIR"
    
    log "[1/4] Initializing configuration..."
    handle_config
    
    log "[2/4] Generating application files..."
    generate_all_files
    
    log "[3/4] Creating Docker Compose configuration..."
    cat <<EOF > docker-compose.yml
services:
  traefik:
    image: traefik:v2.9
    container_name: ${PROJECT_DIR}-traefik
    restart: unless-stopped
    ports:
      # FIX: Changed host port from 8080 to 80 for standard HTTP
      - "8088:80"
      - "8443:443"
    environment:
      - CLOUDFLARE_DNS_API_TOKEN
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./traefik/acme.json:/acme.json
    command:
      - "--providers.docker=true"
      - "--providers.docker.exposedbydefault=false"
      - "--entrypoints.web.address=:80"
      - "--entrypoints.websecure.address=:443"
      - "--certificatesresolvers.myresolver.acme.dnschallenge=true"
      - "--certificatesresolvers.myresolver.acme.dnschallenge.provider=cloudflare"
      - "--certificatesresolvers.myresolver.acme.email=${LETSENCRYPT_EMAIL}"
      - "--certificatesresolvers.myresolver.acme.storage=/acme.json"

  proxy_app:
    build: ./proxy
    container_name: ${PROJECT_DIR}-app
    restart: unless-stopped
    volumes:
      - app_data:/data
    # FIX: Ensures all variables from the .env file are passed to the container
    env_file:
      - .env
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.proxy_app_secure.rule=Host(\`${DOMAIN}\`)"
      - "traefik.http.routers.proxy_app_secure.entrypoints=websecure"
      - "traefik.http.routers.proxy_app_secure.tls.certresolver=myresolver"
      - "traefik.http.services.proxy_app.loadbalancer.server.port=8000"
      - "traefik.http.routers.proxy_app_insecure.rule=Host(\`${DOMAIN}\`)"
      - "traefik.http.routers.proxy_app_insecure.entrypoints=web"
      - "traefik.http.routers.proxy_app_insecure.middlewares=redirect-to-https@docker"
      - "traefik.http.middlewares.redirect-to-https.redirectscheme.scheme=https"
      - "traefik.http.middlewares.redirect-to-https.redirectscheme.port=8443"
      - "traefik.http.middlewares.redirect-to-https.redirectscheme.permanent=true"

  cleanup_cron:
    build: ./cron
    container_name: ${PROJECT_DIR}-cron
    restart: unless-stopped
    volumes:
      - app_data:/data

volumes:
  app_data:
    name: ${PROJECT_DIR}_app_data
EOF
    log_success "Docker Compose file created."

    log "[4/4] Building and launching application..."
    docker compose up -d --build --remove-orphans

    echo
    log_success "--- Deployment Complete ---"
    echo
    echo -e "Your File Proxy System should now be running!"
    echo -e "Please allow a minute for the SSL certificate to be generated."
    echo -e "  ${C_YELLOW}Access your dashboard at: https://${DOMAIN}:8443${C_RESET}"
    echo
    local current_dir
    current_dir=$(pwd)
    echo -e "To view live logs, run: ${C_GREEN}cd ${current_dir} && docker compose logs -f${C_RESET}"
    echo -e "To stop the system, run: ${C_GREEN}cd ${current_dir} && docker compose down${C_RESET}"
}

uninstall_system() {
    log "--- Uninstalling File Proxy System ---"
    
    if [ ! -d "$PROJECT_DIR" ]; then
        log_success "Project directory '$PROJECT_DIR' not found. Nothing to do."
        exit 0
    fi

    echo -e "${C_YELLOW}This will permanently remove all containers, data, logs, and configuration for '$PROJECT_DIR'.${C_RESET}"
    read -p "Are you absolutely sure you want to continue? [y/N] " -n 1 -r; echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Uninstall cancelled."
        exit 1
    fi

    cd "$PROJECT_DIR"
    if [ ! -f "docker-compose.yml" ]; then
        log_error "Could not find 'docker-compose.yml'. The directory may be corrupted. Manual removal of the '$PROJECT_DIR' directory is required."
    fi

    log "Shutting down containers and removing all associated data (volumes, images)..."
    docker compose down --volumes --rmi all
    
    cd ..
    log "Deleting project directory..."
    rm -rf "$PROJECT_DIR"

    log_success "Uninstallation complete. All traces removed. 👋"
}


# --- Main Script Router ---
case "$1" in
    install|"")
        install_system
        ;;
    uninstall)
        uninstall_system
        ;;
    *)
        show_usage
        ;;
esac