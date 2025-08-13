from dotenv import load_dotenv
load_dotenv()

from flask import Flask, render_template, request, jsonify, redirect, url_for, make_response, session, send_from_directory, abort
import random
import string
import hashlib
import time
import os
import json
import session_module as account_mg
import chat_module as chatMD
from flask_session import Session
from datetime import timedelta, timezone
import datetime
from route_mount import *
from db_module import * 
import db_module as db
from markupsafe import escape
import jwt
from decimal import Decimal
import unicodedata
import shutil
import requests
from bs4 import BeautifulSoup
import mimetypes
import base64
from urllib.parse import urlparse
from werkzeug.utils import secure_filename
from pricin_update import get_dexscreener_price, get_token_price_cached
import jwt, requests, math
import threading
import re
from solana_utils import get_token_balance_owner, verify_transfer_signature
from update_charts import start_background_updater

app = Flask(__name__)
app.config['SESSION_TYPE'] = 'filesystem'
# Set to False for development over HTTP, otherwise session cookie is not sent.
app.config['SESSION_COOKIE_SECURE'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY_SERVER')

@app.context_processor
def inject_getenv():
    return dict(getenv=os.getenv)

Session(app)

# Ensure temp_media exists
os.makedirs(os.path.join('static', 'temp_media'), exist_ok=True)

# Initialize database
db_builder = AccountsDBTools(
    user_db=os.getenv('USERDB'),
    password_db=os.getenv('PASSWORDDB'),
    host_db=os.getenv('DBHOST'),
    port_db=os.getenv('PORTDB'),
    database="strawberry_platform"
)
class ChatSessionManager:
    def __init__(self):
        self.ChatHistory = {}
        self.chat_module = {}
        self.chattimes = {}
        self.sessions_online = {}
        self.account_sessions_global = {}
        self.sesion_remove_inactive_time = 15*60 # 15 minutes
        self.hashAvalible = []
        self.hash_invite_sessions = {}
        self.hash_apunt = {}
        self.hash_sesions_index = []
        self.session_pricings = {}
        self.hash_invite_session_avalible = {}


chat_sessions = ChatSessionManager()
# Global variables
class GlobalVariables:
    def __init__(self):
        # Rate limiting: per-website fixed 1-hour window counters
        # { site_name: { 'window': epoch_floor_to_hour, 'count': int } }
        self.web_rate_limiter = {}
        self.web_rate_lock = threading.Lock()

global_vars = GlobalVariables()

def get_user_language():
    return request.accept_languages.best_match(['en', 'es', 'zh'])

def sanitize_filename(name):
    """Sanitizes a string to be used as a filename.
    - Remove accents/diacritics and strange characters
    - Convert to lowercase
    - Keep only [a-z0-9-.] and replace whitespace with '-'
    """
    if not name:
        return ''
    # Normalize and remove diacritics
    name = unicodedata.normalize('NFD', name)
    name = ''.join(c for c in name if unicodedata.category(c) != 'Mn')
    # Lowercase
    name = name.lower()
    # Replace any whitespace sequence with single hyphen
    name = '-'.join(name.split())
    # Keep only allowed chars
    allowed = set('abcdefghijklmnopqrstuvwxyz0123456789-.')
    name = ''.join(c for c in name if c in allowed)
    return name.strip('-.') or 'site'


# --- Helpers for publishing ---
def _filename_from_url(u: str, default_prefix: str = 'asset') -> str:
    try:
        parsed = urlparse(u)
        base = os.path.basename(parsed.path) if parsed.path else ''
        if not base or '.' not in base:
            base = f"{default_prefix}-" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
        return base
    except Exception:
        return f"{default_prefix}-" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))


def _is_http_url(u: str) -> bool:
    return isinstance(u, str) and (u.startswith('http://') or u.startswith('https://'))


def _save_data_uri(data_uri: str, dest_dir: str, default_prefix: str) -> str:
    try:
        header, b64data = data_uri.split(',', 1)
        # Extract mime
        mime = 'application/octet-stream'
        if ';' in header and header.startswith('data:'):
            mime = header.split(';')[0][5:]
        ext = mimetypes.guess_extension(mime) or '.bin'
        fname = f"{default_prefix}-" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=8)) + ext
        os.makedirs(dest_dir, exist_ok=True)
        with open(os.path.join(dest_dir, fname), 'wb') as f:
            f.write(base64.b64decode(b64data))
        return fname
    except Exception:
        return None


def _download_file(url: str, dest_dir: str, default_prefix: str) -> str:
    try:
        os.makedirs(dest_dir, exist_ok=True)
        fname = _filename_from_url(url, default_prefix)
        dest_path = os.path.join(dest_dir, fname)
        # If already exists, reuse existing file and avoid duplicate writes
        if os.path.exists(dest_path):
            return fname
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        with open(dest_path, 'wb') as f:
            f.write(r.content)
        return fname
    except Exception as e:
        print(f"Failed to download {url}: {e}")
        return None


def _resolve_temp_media_local_path(u: str) -> str | None:
    """If the given URL points to /static/temp_media, return local filesystem path."""
    try:
        if not isinstance(u, str):
            return None
        # If absolute URL, extract path
        path = u
        if _is_http_url(u):
            path = urlparse(u).path or ''
        # Normalize potential prefixes
        if path.startswith('/static/temp_media/'):
            local_rel = path.lstrip('/')
        elif path.startswith('static/temp_media/'):
            local_rel = path
        else:
            return None
        local_fs = os.path.join(*local_rel.split('/'))  # normalize separators
        return local_fs if os.path.isfile(local_fs) else None
    except Exception:
        return None


def analyze_images_needed(html: str, site_folder: str) -> int:
    """Count how many new image files would be saved into site_folder.
    Only counts <img src> and SVG <image href/xlink:href>. Does not count audio/video.
    NOTE: This function is pure and MUST NOT create the destination folder to avoid
    false positives when checking if a site already exists.
    """
    try:
        soup = BeautifulSoup(html or '', 'html.parser')
        dest_dir = site_folder
        # IMPORTANT: Do NOT create dest_dir here. We only want to simulate whether files would be new.

        def will_need_new_file(src: str) -> bool:
            if not src:
                return False
            # data URI will always create a new file
            if src.startswith('data:'):
                return True
            # temp_media
            local_src = _resolve_temp_media_local_path(src)
            if local_src:
                fname = os.path.basename(local_src)
                return not os.path.exists(os.path.join(dest_dir, fname))
            # remote
            if _is_http_url(src):
                fname = _filename_from_url(src, 'img')
                return not os.path.exists(os.path.join(dest_dir, fname))
            return False

        count = 0
        # IMG tags
        for tag in soup.find_all('img'):
            src = tag.get('src')
            if will_need_new_file(src):
                count += 1
        # SVG image tags
        for tag in soup.find_all('image'):
            href = tag.get('href') or tag.get('{http://www.w3.org/1999/xlink}href') or tag.get('xlink:href')
            if will_need_new_file(href):
                count += 1
        return count
    except Exception as e:
        print(f"Error analyzing images: {e}")
        return 0


def localize_multimedia(html: str, site_folder: str, public_prefix: str) -> tuple[str, int]:
    """
    Downloads/moves multimedia assets into site_folder and rewrites URLs to public_prefix.
    Also moves any files referenced from /static/temp_media into the site folder.
    Returns (updated HTML string, images_moved_count) where images_moved_count includes only image assets (img, svg image).
    Ensures that after publish/republish, all image references in HTML (including srcset and inline styles) point to the website folder.
    Now also rewrites common lazy-load attributes (data-src, data-original, data-bg, data-background, data-image, data-srcset).
    """
    images_moved_count = 0
    try:
        soup = BeautifulSoup(html or '', 'html.parser')
        dest_dir = site_folder

        def is_already_site_url(src: str) -> bool:
            if not isinstance(src, str) or not src:
                return False
            # Extract path for absolute URLs
            path = src
            if _is_http_url(src):
                try:
                    path = urlparse(src).path or ''
                except Exception:
                    path = src
            # Normalize public prefix without leading slash
            pp = public_prefix.lstrip('/') if isinstance(public_prefix, str) else ''
            # Accept both with and without leading slash for the website folder
            if path.startswith(public_prefix + '/') or path == public_prefix:
                return True
            if path.startswith(pp) or path.startswith('/' + pp):
                return True
            # Consider site-relative paths (e.g., images/foo.jpg, ./img/x.png, ../assets/y.webp)
            # as already site content, as long as they are not explicitly temp_media or data URIs
            if not _is_http_url(src) and not (path.startswith('/static/temp_media') or path.startswith('static/temp_media')):
                if path.startswith('./') or path.startswith('../'):
                    return True
                # No leading slash and not data/absolute => likely site-relative
                if not path.startswith('/') and not src.startswith('data:'):
                    return True
            return False

        def copy_from_temp_or_download(src: str, default_prefix: str) -> str | None:
            nonlocal images_moved_count
            # Leave intact if it already points to the current website folder
            if is_already_site_url(src):
                return ''  # signal no change
            moved = False
            # First, try to resolve from temp_media
            local_src = _resolve_temp_media_local_path(src)
            if local_src:
                try:
                    os.makedirs(dest_dir, exist_ok=True)
                    orig_name = os.path.basename(local_src)
                    target = os.path.join(dest_dir, orig_name)
                    before = set(os.listdir(dest_dir)) if os.path.isdir(dest_dir) else set()
                    if not os.path.exists(target):
                        # Move from temp_media so it won't be deleted at midnight
                        shutil.move(local_src, target)
                        moved = True
                    # If exists, we reuse existing and do not move
                    after = set(os.listdir(dest_dir)) if os.path.isdir(dest_dir) else set()
                    if len(after - before) > 0:
                        images_moved_count += 1
                    return orig_name if (moved or os.path.exists(target)) else None
                except Exception as e:
                    print(f"Failed to move from temp_media {local_src}: {e}")
            # Then, handle data URIs or remote URLs
            if src and src.startswith('data:'):
                before = set(os.listdir(dest_dir)) if os.path.isdir(dest_dir) else set()
                fname = _save_data_uri(src, dest_dir, default_prefix)
                after = set(os.listdir(dest_dir)) if os.path.isdir(dest_dir) else set()
                if fname and len(after - before) > 0:
                    images_moved_count += 1
                return fname
            if _is_http_url(src):
                before = set(os.listdir(dest_dir)) if os.path.isdir(dest_dir) else set()
                fname = _download_file(src, dest_dir, default_prefix)
                after = set(os.listdir(dest_dir)) if os.path.isdir(dest_dir) else set()
                if fname and len(after - before) > 0:
                    images_moved_count += 1
                return fname
            return None

        def rewrite_style_urls(style_val: str) -> str:
            # Replace url(...) occurrences inside inline styles
            def repl(m):
                url_inner = m.group(1).strip().strip("'\"")
                newfname = copy_from_temp_or_download(url_inner, 'img')
                newurl = f"{public_prefix}/{newfname}" if newfname else url_inner
                return f"url('{newurl}')"
            # match url("..."), url('...') or url(...)
            return re.sub(r"url\(([^)]+)\)", repl, style_val or '')

        def rewrite_srcset(val: str) -> str:
            # Parse srcset: comma-separated, each item: URL [descriptor]
            items = [x.strip() for x in (val or '').split(',') if x.strip()]
            out = []
            for it in items:
                parts = it.split()
                if not parts:
                    continue
                urlp = parts[0]
                desc = ' '.join(parts[1:])
                fname = copy_from_temp_or_download(urlp, 'img')
                newu = f"{public_prefix}/{fname}" if fname else urlp
                out.append((newu + (f" {desc}" if desc else '')).strip())
            return ', '.join(out)

        def rewrite_attr(tag, attr_name: str, default_prefix: str = 'img'):
            if not tag.has_attr(attr_name):
                return
            val = tag.get(attr_name)
            if not val:
                return
            if attr_name.endswith('srcset'):
                tag[attr_name] = rewrite_srcset(val)
            else:
                fname = copy_from_temp_or_download(val, default_prefix)
                if fname:
                    tag[attr_name] = f"{public_prefix}/{fname}"

        # IMG tags (src and srcset and lazy variants)
        for tag in soup.find_all('img'):
            for a in ['src', 'data-src', 'data-original', 'data-url', 'data-image', 'data-bg', 'data-background']:
                rewrite_attr(tag, a, 'img')
            for a in ['srcset', 'data-srcset', 'data-responsive-srcset']:
                rewrite_attr(tag, a, 'img')
            # Inline style background-image, etc.
            if tag.has_attr('style'):
                tag['style'] = rewrite_style_urls(tag.get('style', ''))

        # PICTURE/SOURCE for responsive images (srcset and lazy variants)
        for tag in soup.find_all('source'):
            for a in ['srcset', 'data-srcset']:
                rewrite_attr(tag, a, 'img')
            if tag.has_attr('style'):
                tag['style'] = rewrite_style_urls(tag.get('style', ''))

        # SVG <image> tags (xlink:href or href)
        for tag in soup.find_all('image'):
            href = tag.get('href') or tag.get('{http://www.w3.org/1999/xlink}href') or tag.get('xlink:href')
            if href:
                fname = copy_from_temp_or_download(href, 'img')
                if fname:
                    newv = f"{public_prefix}/{fname}"
                    tag['href'] = newv
                    if '{http://www.w3.org/1999/xlink}href' in tag.attrs:
                        tag['{http://www.w3.org/1999/xlink}href'] = newv
                    if 'xlink:href' in tag.attrs:
                        tag['xlink:href'] = newv
            if tag.has_attr('style'):
                tag['style'] = rewrite_style_urls(tag.get('style', ''))

        # Also rewrite inline styles globally on common containers
        for tag in soup.find_all(True):
            if tag.has_attr('style'):
                tag['style'] = rewrite_style_urls(tag.get('style', ''))

        # Rewrite URLs inside <style> tags content
        for sty in soup.find_all('style'):
            if sty.string:
                try:
                    sty.string.replace_with(rewrite_style_urls(sty.string))
                except Exception as e:
                    print(f"Failed to rewrite <style> content urls: {e}")

        # LINK tags that reference images (preload icons etc.)
        for l in soup.find_all('link'):
            rel = ' '.join(l.get('rel') or []).lower()
            as_attr = (l.get('as') or '').lower()
            href = l.get('href')
            if not href:
                continue
            is_image_link = ('icon' in rel) or ('apple-touch-icon' in rel) or (as_attr == 'image')
            if is_image_link:
                fname = copy_from_temp_or_download(href, 'img')
                if fname:
                    l['href'] = f"{public_prefix}/{fname}"

        # AUDIO and VIDEO tags (src, poster)
        for tag in soup.find_all(['audio', 'video']):
            src = tag.get('src')
            if src:
                fname = copy_from_temp_or_download(src, 'media')
                if fname:
                    tag['src'] = f"{public_prefix}/{fname}"
            poster = tag.get('poster')
            if poster:
                fname = copy_from_temp_or_download(poster, 'poster')
                if fname:
                    tag['poster'] = f"{public_prefix}/{fname}"
            for s in tag.find_all('source'):
                ssrc = s.get('src')
                if not ssrc:
                    continue
                fname = copy_from_temp_or_download(ssrc, 'media')
                if fname:
                    s['src'] = f"{public_prefix}/{fname}"

        return str(soup), images_moved_count
    except Exception as e:
        print(f"Error localizing multimedia: {e}")
        return html, images_moved_count

# --- Image upload endpoint ---
ALLOWED_IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'}

def _looks_like_image(uploaded_file, ext: str) -> bool:
    try:
        pos = uploaded_file.stream.tell()
        head = uploaded_file.stream.read(512)
        uploaded_file.stream.seek(pos)
        if not head:
            return False
        # JPEG
        if ext in {'.jpg', '.jpeg'} and head.startswith(b"\xFF\xD8\xFF"):
            return True
        # PNG
        if ext == '.png' and head.startswith(b"\x89PNG\r\n\x1a\n"):
            return True
        # GIF
        if ext == '.gif' and (head.startswith(b"GIF87a") or head.startswith(b"GIF89a")):
            return True
        # WEBP (RIFF....WEBP)
        if ext == '.webp' and head[:4] == b'RIFF' and head[8:12] == b'WEBP':
            return True
        # SVG (text-based). Allow xml preamble; quick heuristic.
        if ext == '.svg':
            text = head.decode('utf-8', errors='ignore').lower()
            if '<svg' in text:
                return True
        return False
    except Exception:
        return False

@app.route('/upload_image', methods=['POST'])
def upload_image():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    # Support both single 'image' and first item of 'images[]'
    file = None
    if 'image' in request.files:
        file = request.files['image']
    elif 'images[]' in request.files:
        # pick first if sent as array
        file = request.files.getlist('images[]')[0]
    if not file:
        return jsonify({'success': False, 'error': 'No image provided'}), 400
    if not file or file.filename == '':
        return jsonify({'success': False, 'error': 'Empty filename'}), 400

    # Enforce MIME type image/*
    mtype = getattr(file, 'mimetype', None)
    if not mtype or not mtype.startswith('image/'):
        return jsonify({'success': False, 'error': 'Unsupported media type. Only images are allowed.'}), 400

    filename = secure_filename(file.filename)
    _, ext = os.path.splitext(filename)
    ext = ext.lower()
    if ext not in ALLOWED_IMAGE_EXTS:
        return jsonify({'success': False, 'error': 'Unsupported file type'}), 400

    # Magic-bytes check to avoid disguised files
    if not _looks_like_image(file, ext):
        return jsonify({'success': False, 'error': 'Invalid image file'}), 400

    unique = datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S') + '-' + ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
    final_name = f"{unique}{ext}"

    # Optional: save directly under a website folder when editing an existing site
    # Accept either 'site' (sanitized folder) or 'website_name' (will be sanitized)
    requested_site = (request.form.get('site') or request.form.get('website_name') or '').strip()
    site_folder_name = sanitize_filename(requested_site) if requested_site else ''
    save_dir = None
    relative_url = None

    if site_folder_name:
        site_dir = os.path.join('static', 'websites', site_folder_name)
        try:
            owns_site = False
            try:
                # Best-effort ownership check via DB record
                rec = db_builder.get_website_by_file(session['user_id'], f"{site_folder_name}/index.html")
                owns_site = bool(rec)
            except Exception:
                owns_site = False
            # If folder exists and passes (or DB unavailable), allow saving there
            if os.path.isdir(site_dir) and (owns_site or True):
                save_dir = site_dir
                relative_url = f"/static/websites/{site_folder_name}/{final_name}"
        except Exception:
            save_dir = None

    # Default to temp_media if no valid site folder
    if not save_dir:
        save_dir = os.path.join('static', 'temp_media')
        relative_url = url_for('static', filename=f'temp_media/{final_name}')

    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, final_name)
    try:
        file.save(save_path)
    except Exception as e:
        return jsonify({'success': False, 'error': f'Failed to save image: {e}'}), 500

    base_url = os.getenv('BASE_URL', 'http://localhost:8080').rstrip('/')
    public_url = f"{base_url}{relative_url}"
    return jsonify({'success': True, 'url': relative_url, 'public_url': public_url})

# --- Daily cleanup of temp_media at 00:00 ---

def cleanup_temp_media():
    folder = os.path.join('static', 'temp_media')
    try:
        if not os.path.isdir(folder):
            return
        for entry in os.listdir(folder):
            p = os.path.join(folder, entry)
            try:
                if os.path.isfile(p) or os.path.islink(p):
                    os.remove(p)
                elif os.path.isdir(p):
                    shutil.rmtree(p)
            except Exception as e:
                print(f"Failed to remove {p}: {e}")
        print('[cleanup] temp_media emptied')
    except Exception as e:
        print(f"Error cleaning temp_media: {e}")


def schedule_temp_media_cleanup():
    def worker():
        while True:
            now = datetime.datetime.now()
            next_midnight = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            sleep_seconds = max(1, int((next_midnight - now).total_seconds()))
            time.sleep(sleep_seconds)
            try:
                cleanup_temp_media()
            except Exception as e:
                print(f"Cleanup error: {e}")
    t = threading.Thread(target=worker, daemon=True)
    t.start()

# Start the cleanup scheduler
schedule_temp_media_cleanup()
start_background_updater()

@app.route('/api/spl_price')
def api_spl_price():
    """Diagnostic endpoint: returns live Dexscreener price, cached, and DB stored metrics.
    Helps debug anomalies (e.g., USDC showing 0.004)."""
    mint = os.getenv('SPL_TOKEN_MINT','')
    live = get_dexscreener_price(mint) if mint else None
    cached = get_token_price_cached(mint) if mint else None
    metrics = None
    try:
        metrics = db_builder.fetch_token_metrics(mint) if mint else None
    except Exception:
        metrics = None
    return jsonify({
        'mint': mint,
        'live_price_usd': live,
        'cached_price_usd': cached,
        'db_metrics': metrics,
        'price_source_note': 'live is direct Dexscreener robust; cached is last in-memory; db_metrics from periodic updater',
    })

@app.route('/sign-up')
def signup():
    if 'username' in session:
        return redirect(url_for('chat'))
    return render_template('signup.html')

@app.route('/')
def index():
    if 'username' in session:
        return redirect(url_for('chat'))
    return render_template('login.html')

@app.route('/login')
def login():
    if 'username' in session:
        return redirect(url_for('chat'))
    return render_template('login.html')

@app.route('/confirm_and_signup', methods=['POST'])
def confirm_and_signup():
    try:
        data = request.get_json()
        username = escape(data.get('username', ''))
        password = escape(data.get('password', ''))

        if not (username and password):
            return jsonify({'success': False, 'error': 'All fields are required'}), 400

        db_tool = AccountsDBTools(
            user_db=os.getenv('USERDB'),
            password_db=os.getenv('PASSWORDDB'),
            host_db=os.getenv('DBHOST'),
            port_db=os.getenv('PORTDB'),
            database="strawberry_platform"
        )
        result = db_tool.register_new_user(username, password)

        if "successfully" in result:
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': result}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': 'An unexpected error occurred'}), 500

@app.route('/login_action', methods=['POST'])
def login_action():
    data = request.get_json()
    username = escape(data.get('username', ''))
    password = escape(data.get('password', ''))
    type_gpt_select = "Strawberry_01"

    if not (username and password):
        return jsonify({'error': 'Username and password are required'}), 400

    login_process = AccountsDBTools(
        user_db=os.getenv('USERDB'),
        password_db=os.getenv('PASSWORDDB'),
        host_db=os.getenv('DBHOST'),
        port_db=os.getenv('PORTDB'),
        database="strawberry_platform"
    )

    result = login_process.login_session(username, password)
    result_json = json.loads(result)

    if "error" not in result_json:
        user_id = result_json["user_id"]
        session['username'] = result_json["username"]
        session['user_id'] = user_id
        session.permanent = True
        
        return jsonify({'success': True})
    else:
        return jsonify({'error': result_json['error']}), 401

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/chat')
@app.route('/chat/<hashchat>')
def chat(hashchat=None):
    if 'username' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    balance = db_builder.get_user_balance(user_id)

    if not hashchat:
        # If no hash is provided, try to load the latest chat
        latest_chat = db_builder.get_latest_chat(user_id)
        if latest_chat:
            return redirect(url_for('chat', hashchat=latest_chat))
        else:
            # No chats exist for the user, show a welcome/empty state
            return render_template('chatweb.html', username=session['username'], hashchat=None, balance=balance)

    # Load existing chat
    history = db_builder.load_chat_history(hashchat, user_id)
    if history is not None:
        chat_sessions.ChatHistory[hashchat] = history
        session['hashchat'] = hashchat
        return render_template('chatweb.html',
                               username=session['username'],
                               hashchat=hashchat,
                               balance=balance,
                               hash_invited=session.get('hash_invite'))
    else:
        # Chat does not exist or does not belong to the user
        return redirect(url_for('chat'))

@app.route('/new_chat', methods=['POST'])
def new_chat():
    if 'username' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    hashchat = ''.join(random.choices(string.ascii_letters + string.digits, k=18))
    chat_sessions.ChatHistory[hashchat] = []
    db_builder.save_chat_history(session['user_id'], hashchat, f"New Chat {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}", [])
    
    return jsonify({'success': True, 'hashchat': hashchat})

@app.route('/chat_history')
def chat_history():
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template('chat_history.html', username=session['username'])

@app.route('/publish_website', methods=['POST'])
def publish_website():
    data = request.get_json()
    html_content = data.get('html_content', '')
    website_name = escape(data.get('website_name', ''))
    republish_flag = bool(data.get('republish', False))
    hashchat = data.get('hashchat') or None

    if not all([html_content, website_name]):
        return jsonify({'success': False, 'error': 'Missing parameters'}), 400

    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'User not logged in'}), 401
    
    user_id = session['user_id']

    # Normalize and sanitize the website name
    sanitized_name = sanitize_filename(website_name)
    if not sanitized_name:
        return jsonify({'success': False, 'error': 'Nombre de la web inválido. Usa letras, números y guiones.'}), 400

    websites_root = os.path.join('static', 'websites')
    os.makedirs(websites_root, exist_ok=True)
    site_folder = os.path.join(websites_root, sanitized_name)

    price_per_publish = Decimal(os.getenv('PRICE_PER_PUBLISH_USD', '50'))
    price_per_republish = Decimal(os.getenv('PRICE_PER_REPUBLISH_USD', '0.10'))
    price_per_image = Decimal(os.getenv('PRICE_PER_IMAGE_SAVE_USD', '0.04'))

    balance = db_builder.get_user_balance(user_id)
    recharge_url = os.getenv('RECHARGE_URL')

    # Debug logs about inputs and paths
    print(f"[publish_website] user_id={user_id} website_name_raw='{website_name}' sanitized='{sanitized_name}' republish={republish_flag}")
    print(f"[publish_website] websites_root='{websites_root}' site_folder='{site_folder}' exists? {os.path.exists(site_folder)}")

    if not republish_flag:
        # Check case-insensitively for existing folder BEFORE any side effects
        try:
            existing_dirs_lower = {d.lower() for d in os.listdir(websites_root) if os.path.isdir(os.path.join(websites_root, d))}
        except FileNotFoundError:
            existing_dirs_lower = set()
        print(f"[publish_website] existing_dirs_lower={sorted(existing_dirs_lower)}")
        if sanitized_name.lower() in existing_dirs_lower or os.path.isdir(site_folder):
            msg = 'No se pudo publicar el sitio: Esta web ya existe (carpeta). Elige otro nombre o usa Republish.'
            print(f"[publish_website][error] {msg}")
            return jsonify({
                'success': False,
                'error': 'Esta web ya existe (carpeta). Elige otro nombre o usa Republish.',
                'debug': {
                    'sanitized_name': sanitized_name,
                    'websites_root': websites_root,
                    'site_folder_exists': os.path.isdir(site_folder)
                }
            }), 400

        # Only analyze images after confirming the folder does not exist
        images_to_save = analyze_images_needed(html_content, site_folder)
        images_cost = price_per_image * Decimal(images_to_save)
        print(f"[publish_website] images_to_save={images_to_save} images_cost={images_cost}")

        total_cost = price_per_publish + images_cost
        if balance is None or balance < total_cost:
            print(f"[publish_website][error] Insufficient balance. balance={balance} needed={total_cost}")
            return jsonify({'success': False, 'error': f'Insufficient balance. Need ${total_cost} USD.', 'recharge_url': recharge_url}), 402
        # Deduct first
        db_builder.update_user_balance(user_id, balance - total_cost)

        # Create folder now that we're certain it doesn't exist
        os.makedirs(site_folder, exist_ok=True)
        public_prefix = f"/static/websites/{sanitized_name}"
        processed_html, moved_images = localize_multimedia(html_content, site_folder, public_prefix)

        # Save index.html
        index_path = os.path.join(site_folder, 'index.html')
        with open(index_path, 'w', encoding='utf-8') as f:
            f.write(processed_html)

        # Update the active chat session document so recall_html returns the finalized HTML
        if hashchat and hashchat in chat_sessions.sessions_online:
            try:
                chat_sessions.sessions_online[hashchat].current_document = processed_html
            except Exception as e:
                print(f"[publish_website] Failed to update current_document for {hashchat}: {e}")

        relative_url = url_for('static', filename=f'websites/{sanitized_name}/index.html')
        base_url = os.getenv('BASE_URL', 'http://localhost:8080').rstrip('/')
        public_url = f"{base_url}{relative_url}"

        db_builder.save_website(user_id, relative_url, website_name, f"{sanitized_name}/index.html")
        return jsonify({'success': True, 'url': public_url, 'republish': False, 'images_saved': int(moved_images), 'images_charged': int(images_to_save)})

    # Republish flow
    existing_website = None
    try:
        existing_website = db_builder.get_website_by_file(user_id, f"{sanitized_name}/index.html")
    except Exception as e:
        print(f"[publish_website] get_website_by_file error: {e}")
        existing_website = None
    if not existing_website:
        try:
            existing_website = db_builder.get_website_by_name(user_id, website_name)
        except Exception as e:
            print(f"[publish_website] get_website_by_name error: {e}")
            existing_website = None
    if not existing_website:
        print("[publish_website][error] Republish denied: website not found for this user")
        return jsonify({'success': False, 'error': 'Solo puedes republicar sitios que te pertenecen. Abre el historial y usa el botón Republish.'}), 403

    # Analyze images for republish
    images_to_save = analyze_images_needed(html_content, site_folder)
    images_cost = price_per_image * Decimal(images_to_save)
    print(f"[republish] images_to_save={images_to_save} images_cost={images_cost}")

    total_cost = price_per_republish + images_cost
    if balance is None or balance < total_cost:
        print(f"[republish][error] Insufficient balance. balance={balance} needed={total_cost}")
        return jsonify({'success': False, 'error': f'Insufficient balance. Need ${total_cost} USD.', 'recharge_url': recharge_url}), 402
    db_builder.update_user_balance(user_id, balance - total_cost)

    os.makedirs(site_folder, exist_ok=True)

    public_prefix = f"/static/websites/{sanitized_name}"
    processed_html, moved_images = localize_multimedia(html_content, site_folder, public_prefix)

    index_path = os.path.join(site_folder, 'index.html')
    with open(index_path, 'w', encoding='utf-8') as f:
        f.write(processed_html)

    # Update the active chat session document so recall_html returns the finalized HTML (republish)
    if hashchat and hashchat in chat_sessions.sessions_online:
        try:
            chat_sessions.sessions_online[hashchat].current_document = processed_html
        except Exception as e:
            print(f"[republish] Failed to update current_document for {hashchat}: {e}")

    relative_url = url_for('static', filename=f'websites/{sanitized_name}/index.html')
    base_url = os.getenv('BASE_URL', 'http://localhost:8080').rstrip('/')
    public_url = f"{base_url}{relative_url}"

    try:
        db_builder.update_website_by_file(user_id, f"{sanitized_name}/index.html", website_name, f"{sanitized_name}/index.html")
    except Exception as e:
        print(f"[republish] update_website_by_file failed, fallback to save_website: {e}")
        db_builder.save_website(user_id, relative_url, website_name, f"{sanitized_name}/index.html")

    return jsonify({'success': True, 'url': public_url, 'republish': True, 'images_saved': int(moved_images), 'images_charged': int(images_to_save)})

@app.route('/update_messages_history', methods=['POST'])
def update_messages_history():
    try:
        data = request.get_json()
        hashchat = escape(data.get("hashsesion", ''))
        len_list_history = int(data.get("len_list_history", 0))

        if 'user_id' not in session:
            return jsonify({'error': "Unauthorized"}), 401

        history = chat_sessions.ChatHistory.get(hashchat)
        if history is None:
            history = db_builder.load_chat_history(hashchat, session['user_id'])
            if history is None:
                return jsonify({'message': "not_update_history_chat", "audio_autoplay": None, "deploy_item": None, "role": "system"})
            chat_sessions.ChatHistory[hashchat] = history

        if len(history) <= len_list_history:
            return jsonify({'message': "not_update_history_chat", "audio_autoplay": None, "deploy_item": None, "role": "system"})
        else:
            return jsonify(history)
    except Exception as e:
        print(f"Error en update_messages_history: {e}")
        return jsonify({'message': "Internal server error. Please try again later.", "audio_autoplay": None, "deploy_item": None, "role": "server"}), 500

@app.route('/chat/message', methods=['POST'])
def message():
    data = request.get_json()
    hashchat = escape(data.get('hashchat', ''))
    # Original user-visible text
    message_text = escape(data.get('message', ''))
    username = escape(data.get('usernickname', ''))
    user_lang = get_user_language()
    current_html = data.get('current_html', '') # Get current HTML from the request
    url_images = data.get('url_images', []) or []

    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    user_id = session['user_id']

    # Check user balance
    balance = db_builder.get_user_balance(user_id)
    recharge_url = os.getenv('RECHARGE_URL')
    if balance is None or balance <= 0:
        return jsonify({'error': 'Insufficient balance. Please recharge your account.', 'recharge_url': recharge_url}), 402

    # Check if assistant exists and is active
    if hashchat not in chat_sessions.sessions_online or \
       (time.time() - chat_sessions.chattimes.get(hashchat, 0)) > chat_sessions.sesion_remove_inactive_time:
        
        # Create new assistant
        type_gpt_select = "Strawberry_01"
        
        initial_instruction = "Hello! I'm ready to help you build or edit your website. What would you like to do?"
        if current_html:
            initial_instruction = f"This is the current website I am editing:\n\n{current_html}\n\nPlease continue helping me with this. I'm ready for your instructions."
        # Reinforce path handling rules for edits
        initial_instruction += ("\n\nImportant editing rules:" 
                                 "\n- Preserve existing image URLs that already point to /static/websites/... or are site-relative."
                                 "\n- Do not change them to /static/temp_media."
                                 "\n- When adding new images, keep all existing images and their URLs unchanged.")

        session_gpt = account_mg.flow_login_session(username, type_gpt_select)
        session_gpt_instance = session_gpt.try_login_session(initial_instruction, user_id)

        if isinstance(session_gpt_instance, str):
            return jsonify({'error': session_gpt_instance}), 500
        
        with open(os.path.join(route_mount, f'json_files/templates_structures/gpt_configs/{type_gpt_select}.json'), 'r') as f:
            data_config = json.load(f)
        
        instruction_minimalist = data_config.get('function_minimalist_instruct', '')
        
        chat_sessions.sessions_online[hashchat] = chatMD.gpt_run_session(
            hashchat,
            session_gpt_instance,
            0.0,
            0.0,
            0.0,
            instruction_minimalist,
            user_lang,
            balance
        )

    chat_sessions.chattimes[hashchat] = time.time()
    
    # Build the message to the assistant (with images list if provided) but keep history with original user text
    message_for_model = message_text
    if isinstance(url_images, list) and len(url_images) > 0:
        # Normalize to strings and avoid empties
        urls = [str(u) for u in url_images if u]
        if urls:
            joined = '\n'.join(urls)
            message_for_model = f"{message_text}\n\nademas debes incluir estas imagenes: aca van todas las url:\n{joined}"

    if hashchat not in chat_sessions.ChatHistory:
        loaded_history = db_builder.load_chat_history(hashchat, user_id)
        if loaded_history is None:
             # This case means the user is trying to access a chat that doesn't belong to them
             # or the hash is invalid. We can clear their session and redirect.
            session.clear()
            return jsonify({'error': 'Unauthorized'}), 401
        chat_sessions.ChatHistory[hashchat] = loaded_history

    # Store only the original user text (no noisy system instructions)
    chat_sessions.ChatHistory[hashchat].append({
        'role': 'user',
        'message': message_text
    })

    recive_msg, audio_recive, html_return = chat_sessions.sessions_online[hashchat].push_new_msg_user(
        f'{username}: {message_for_model}', None, []
    )
    
    recive_msg = escape(recive_msg)

    if html_return:
        chat_sessions.ChatHistory[hashchat].append({
            'role': 'deploy_item',
            'message': html_return,
            "deploy_item": True,
        })
    else:
        chat_sessions.ChatHistory[hashchat].append({
            'role': 'server',
            'message': recive_msg,
            "deploy_item": False,
        })

    # Save history
    if chat_sessions.ChatHistory[hashchat]:
        title = chat_sessions.ChatHistory[hashchat][0]['message'][:50] # First user message as title
        db_builder.save_chat_history(user_id, hashchat, title, chat_sessions.ChatHistory[hashchat])

    return jsonify({'success': True})

@app.route('/history')
def history():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    user_history = db_builder.get_user_history(session['user_id'])
    
    base_url = os.getenv('BASE_URL', 'http://localhost:8080').rstrip('/')
    if 'websites' in user_history and user_history['websites']:
        fixed = []
        for website in user_history['websites']:
            file_name = (website.get('file_name') or '').strip()
            name = (website.get('name') or '').strip()

            # Always rebuild the URL from file_name or sanitized name to avoid legacy malformed URLs
            if file_name:
                if not file_name.startswith('websites/') and not file_name.startswith('/static/websites/'):
                    path = f"/static/websites/{file_name}"
                elif file_name.startswith('websites/'):
                    path = f"/static/{file_name}"
                else:
                    path = file_name if file_name.startswith('/') else '/' + file_name
            else:
                folder = sanitize_filename(name)
                path = f"/static/websites/{folder}/index.html"

            website['url'] = f"{base_url}{path}"
            fixed.append(website)

        user_history['websites'] = fixed
            
    return jsonify(user_history)

@app.route('/delete_website', methods=['POST'])
def delete_website():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    data = request.get_json()
    website_name = escape(data.get('name', ''))
    
    if not website_name:
        return jsonify({'success': False, 'error': 'Missing website name'}), 400
        
    user_id = session['user_id']
    website = db_builder.get_website_by_name(user_id, website_name)
    
    if not website:
        return jsonify({'success': False, 'error': 'Website not found'}), 404
        
    # Delete folder from server (prefer folder deletion)
    file_name = website.get('file_name', '') or ''
    # Expected pattern: "<folder>/index.html"; fall back to plain file
    folder = file_name.split('/')[0] if '/' in file_name else None
    if folder:
        folder_path = os.path.join('static', 'websites', folder)
        if os.path.isdir(folder_path):
            try:
                shutil.rmtree(folder_path)
            except Exception as e:
                print(f"Error deleting folder {folder_path}: {e}")
        else:
            # If not a directory, try removing the file_name path
            file_path = os.path.join('static', 'websites', file_name)
            if os.path.exists(file_path):
                os.remove(file_path)
    else:
        # Old format: single file websites
        file_path = os.path.join('static', 'websites', file_name or f"{sanitize_filename(website_name)}.html")
        if os.path.exists(file_path):
            os.remove(file_path)
        
    # Delete from database
    if db_builder.delete_website(user_id, website_name):
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': 'Failed to delete website from database'}), 500

@app.route('/delete_chat', methods=['POST'])
def delete_chat():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    data = request.get_json()
    hashchat = escape(data.get('hashchat', ''))
    
    if not hashchat:
        return jsonify({'success': False, 'error': 'Missing chat hash'}), 400
        
    user_id = session['user_id']
    
    if db_builder.delete_chat_history(user_id, hashchat):
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': 'Failed to delete chat history'}), 500

@app.route('/delete_all_chats', methods=['POST'])
def delete_all_chats():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    user_id = session['user_id']
    
    if db_builder.delete_all_chat_history(user_id):
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': 'Failed to delete all chat history'}), 500

@app.route('/api/webhooks/recharge', methods=['POST'])
def webhook_recharge():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({'error': 'Missing or invalid authorization token'}), 401

    token = auth_header.split(' ')[1]
    try:
        decoded_token = jwt.decode(token, os.getenv('JWT_SECRET'), algorithms=['HS256'])
    except jwt.ExpiredSignatureError:
        return jsonify({'error': 'Token has expired'}), 401
    except jwt.InvalidTokenError:
        return jsonify({'error': 'Invalid token'}), 401

    user_id = decoded_token.get('user_id')
    amount_usd = decoded_token.get('amount_usd')

    if not user_id or amount_usd is None:
        return jsonify({'error': 'Missing user_id or amount_usd in token'}), 400

    current_balance = db_builder.get_user_balance(user_id)
    if current_balance is None:
        return jsonify({'error': 'User not found'}), 404

    new_balance = current_balance + Decimal(str(amount_usd))
    db_builder.update_user_balance(user_id, new_balance)

    return jsonify({'success': True, 'new_balance': float(new_balance)}), 200

@app.route('/api/webhooks/recharge_balance', methods=['POST'])
def webhook_recharge_balance():
    """Webhook llamado por el microservicio de pagos.
    Espera JSON: { wallet, amount, signature_tx, ts, jwt }
    Valida JWT y acredita saldo al usuario dueño de la wallet.
    """
    data = request.get_json(force=True, silent=True) or {}
    token = data.get('jwt')
    if not token:
        return jsonify({'error': 'Falta jwt'}), 401
    try:
        decoded = jwt.decode(token, os.getenv('JWT_SECRET'), algorithms=['HS256'])
    except Exception:
        return jsonify({'error': 'JWT invalido'}), 401

    wallet = data.get('wallet') or decoded.get('wallet')
    amount = data.get('amount') or decoded.get('amount')
    signature_tx = data.get('signature_tx') or decoded.get('signature_tx')
    if not all([wallet, amount, signature_tx]):
        return jsonify({'error': 'Faltan campos requeridos'}), 400

    # Buscar usuario por wallet
    try:
        user = db_builder.get_user_by_wallet(wallet)
    except Exception as e:
        return jsonify({'error': 'Fallo buscando wallet'}), 500
    if not user:
        return jsonify({'error': 'Wallet no vinculada a usuario'}), 404

    user_id = user.get('user_id') if isinstance(user, dict) else user[0] if isinstance(user, (list, tuple)) else None
    if not user_id:
        return jsonify({'error': 'Formato de usuario invalido'}), 500

    try:
        current_balance = db_builder.get_user_balance(user_id) or Decimal('0')
        new_balance = Decimal(str(current_balance)) + Decimal(str(amount))
        db_builder.update_user_balance(user_id, new_balance)
    except Exception as e:
        return jsonify({'error': 'No se pudo actualizar balance'}), 500

    return jsonify({'success': True, 'user_id': user_id, 'new_balance': float(new_balance)})

# --- New Solana / SPL integration routes ---
@app.route('/recharge')
def recharge_page():
    return render_template('recharge.html')

@app.route('/api/token_config')
def token_config():
    token_address = os.getenv('SPL_TOKEN_MINT','')
    treasury = os.getenv('PLATFORM_TREASURY_WALLET','')
    # Fetch latest metrics (optional informational) but price MUST come directly from Dexscreener
    metrics = db_builder.fetch_token_metrics(token_address) if token_address else None
    live_price = get_dexscreener_price(token_address) if token_address else None
    if live_price is None:
        # Try cached as secondary (still originally from Dexscreener); no hardcoded default
        live_price = get_token_price_cached(token_address)
    price = live_price  # May be None
    min_signup_usd = Decimal(os.getenv('MIN_SIGNUP_BALANCE_USD','5'))
    min_deposit_usd = Decimal(os.getenv('MIN_DEPOSIT_USD','1'))
    price_decimal = Decimal(str(price)) if price else Decimal('0')
    def tokens_for(usd):
        if price_decimal > 0:
            return f"{(Decimal(usd)/price_decimal):.6f}"
        return "0"
    resp = {
        'token_price_usd': float(price_decimal) if price_decimal else None,
        'min_signup_usd': float(min_signup_usd),
        'min_signup_tokens': tokens_for(min_signup_usd) if price_decimal>0 else None,
        'min_deposit_usd': float(min_deposit_usd),
        'min_deposit_tokens': tokens_for(min_deposit_usd) if price_decimal>0 else None,
        'metrics': metrics,
        'mint_address': token_address,
        'treasury': treasury,
        'price_source': 'dexscreener_live' if price_decimal>0 else 'dexscreener_unavailable'
    }
    if price_decimal == 0:
        return jsonify(resp), 503
    return jsonify(resp)

@app.route('/api/me/balance')
def api_me_balance():
    # Detailed diagnostics for 401 issues
    debug_info = {
        'session_keys': list(session.keys()),
        'has_user_id': 'user_id' in session,
        'cookie_present': bool(request.cookies.get(app.session_cookie_name)),
        'path': request.path,
        'method': request.method,
        'remote_addr': request.remote_addr,
    }
    if 'user_id' not in session:
        print('[api_me_balance][debug] Unauthorized access attempt', debug_info)
        return jsonify({'error':'Unauthorized', 'debug': debug_info}), 401
    try:
        bal = db_builder.get_user_balance(session['user_id']) or 0
    except Exception as e:
        print('[api_me_balance][debug] DB error fetching balance', {**debug_info, 'error': str(e)})
        return jsonify({'error': 'Balance fetch failed'}), 500
    debug_info['balance'] = float(bal)
    print('[api_me_balance][debug] Balance fetched', debug_info)
    return jsonify({'balance': float(bal), 'debug': debug_info})

@app.route('/api/wallet/<wallet_address>/balance')
def api_wallet_balance(wallet_address):
    # Public endpoint to inspect SPL token balance (for debugging)
    from solana_utils import get_token_balance_owner
    bal_tokens = get_token_balance_owner(wallet_address)
    return jsonify({'wallet': wallet_address, 'balance_tokens': float(bal_tokens)})

@app.route('/api/validate_signup_balance', methods=['POST'])
def validate_signup_balance():
    data = request.get_json(force=True)
    wallet_address = data.get('wallet_address')
    if not wallet_address:
        return jsonify({'error':'wallet_address required'}), 400
    balance_tokens = get_token_balance_owner(wallet_address)
    # Always take live Dexscreener price for validation (no default). Fallback to cached if immediate live fails.
    mint_addr = os.getenv('SPL_TOKEN_MINT','')
    live_price = get_dexscreener_price(mint_addr) if mint_addr else None
    if live_price is None:
        live_price = get_token_price_cached(mint_addr)
    if live_price is None:
        return jsonify({'error': 'Precio de token no disponible (Dexscreener). Intenta mas tarde.'}), 503
    price = Decimal(str(live_price))
    min_signup_usd = Decimal(os.getenv('MIN_SIGNUP_BALANCE_USD','5'))
    usd_value = balance_tokens * (price if price>0 else Decimal('0'))
    valid = usd_value >= min_signup_usd
    return jsonify({'valid': valid, 'balance_tokens': float(balance_tokens), 'usd_value': float(usd_value)})

@app.route('/api/deposit', methods=['POST'])
def api_deposit_proxy():
    """Inicia el proceso de verificación de depósito delegando al microservicio payment_backend.
    Espera: { signature_tx, wallet_address, amount_tokens, amount_usd, mint_address? }
    1. Vincula wallet al usuario (si aún no) para que el webhook pueda acreditar.
    2. Construye payload firmado (JWT) y lo envía a PAYMENT_BACKEND_URL/api/payment/verify.
    3. Espera respuesta del microservicio. El saldo se acreditará vía webhook asíncrono.
    Devuelve estado y balance actual (post-webhook si ya llegó, o pre-webhook si aún no).
    """
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    user_id = session['user_id']
    data = request.get_json(force=True, silent=True) or {}
    signature_tx = data.get('signature_tx')
    wallet_address = data.get('wallet_address')
    amount_tokens = data.get('amount_tokens')  # opcional si el cliente lo calcula
    amount_usd = data.get('amount_usd')  # USD estimado (frontend)
    mint_address = data.get('mint_address') or os.getenv('SPL_TOKEN_MINT','')
    treasury = os.getenv('PLATFORM_TREASURY_WALLET','')
    if not all([signature_tx, wallet_address, treasury, mint_address]):
        return jsonify({'error': 'Missing fields'}), 400

    # Vincular wallet al usuario (si ya pertenece a otro usuario, error)
    try:
        existing_user = db_builder.get_user_by_wallet(wallet_address)
        if existing_user:
            existing_user_id = existing_user.get('user_id') if isinstance(existing_user, dict) else existing_user[0]
            if existing_user_id != user_id:
                return jsonify({'error': 'Wallet already linked to another user'}), 409
        else:
            db_builder.link_wallet_to_user(user_id, wallet_address)
    except Exception as e:
        return jsonify({'error': 'Failed to link wallet'}), 500

    payment_url = os.getenv('PAYMENT_BACKEND_URL', 'http://localhost:8090').rstrip('/') + '/api/payment/verify'
    ts = int(time.time())
    # Construir payload base
    payload_base = {
        'signature_tx': signature_tx,
        'wallet_connected': wallet_address,
        'wallet_recipient': treasury,
        'amount_tokens': str(amount_tokens) if amount_tokens is not None else '',
        'amount_usd': str(amount_usd) if amount_usd is not None else '',
        'mint_address': mint_address,
        'timestamp': ts,
    }
    secret = os.getenv('JWT_SECRET','')
    token_jwt = jwt.encode(payload_base, secret, algorithm='HS256')
    payload_send = dict(payload_base)
    payload_send['token'] = token_jwt

    try:
        resp = requests.post(payment_url, json=payload_send, timeout=25)
        status_code = resp.status_code
        body = {}
        try:
            body = resp.json()
        except Exception:
            body = {'raw': resp.text}
    except Exception as e:
        return jsonify({'error': 'Payment backend unreachable', 'detail': str(e)}), 502

    # Intentar leer balance (por si ya llegó webhook)
    current_balance = db_builder.get_user_balance(user_id)
    return jsonify({'forward_status': status_code, 'payment_response': body, 'balance': float(current_balance) if current_balance is not None else 0})


# --- Per-website rate limiter for static/websites ---
def _get_website_hourly_limit() -> int:
    """Read hourly limit from environment.
    Prefer WEBSITE_HOURLY_LIMIT, fallback to MAX_REQUESTS_PER_HOUR_WEBSITE, default 1000.
    """
    try:
        return int(os.getenv('WEBSITE_HOURLY_LIMIT', os.getenv('MAX_REQUESTS_PER_HOUR_WEBSITE', '1000')))
    except Exception:
        return 1000


def _check_website_rate_limit(site: str) -> bool:
    """Return True if allowed, False if the site exceeded the hourly limit."""
    if not site:
        return True
    limit = _get_website_hourly_limit()
    now = int(time.time())
    current_window = now - (now % 3600)  # floor to current hour
    with global_vars.web_rate_lock:
        rec = global_vars.web_rate_limiter.get(site)
        if not rec or rec.get('window') != current_window:
            rec = {'window': current_window, 'count': 0}
        if rec['count'] >= limit:
            global_vars.web_rate_limiter[site] = rec
            return False
        rec['count'] += 1
        global_vars.web_rate_limiter[site] = rec
        return True


@app.before_request
def websites_rate_limit_guard():
    """Apply per-website hourly limit to any request under /static/websites/*, even when served by Flask static handler."""
    path = request.path or ''
    prefix = '/static/websites/'
    if not path.startswith(prefix):
        return
    rest = path[len(prefix):]
    site = rest.split('/', 1)[0] if rest else ''
    if not _check_website_rate_limit(site):
        return make_response('Rate limit exceeded for this website. Try again later.', 429)


@app.route('/static/websites/<path:filename>')
def serve_rate_limited_website(filename):
    """Serve files under static/websites with per-website hourly rate limit."""
    # Extract the website folder (first path segment)
    site = (filename.split('/', 1)[0] if '/' in filename else filename).strip()
    if not _check_website_rate_limit(site):
        return make_response('Rate limit exceeded for this website. Try again later.', 429)
    # Delegate to Flask's file server from the websites directory
    try:
        return send_from_directory(os.path.join('static', 'websites'), filename)
    except Exception:
        # Preserve behavior similar to default static serving
        abort(404)

if __name__ == '__main__':
    print("Starting server...")
    app.run(debug=True, port=int(os.getenv('PORT', 8080)), host='0.0.0.0')
    print("Server started.")



