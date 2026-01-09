#
# Mae's Writer - Full featured e-ink typewriter with non-blocking refresh
#

import time
import keyboard
import keymaps
from PIL import Image, ImageDraw, ImageFont
import new4in26part as epd_driver
import subprocess
import signal
import os
import shutil
import json
import requests
import threading

# ============================================================
# CONFIG
# ============================================================
CLOUD_API_URL = "https://notebook-1bqd.onrender.com"
CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'data', 'config.json')
FILES_DIR = os.path.join(os.path.dirname(__file__), 'data', 'files')
CACHE_FILE = os.path.join(os.path.dirname(__file__), 'data', 'cache.txt')

os.makedirs(FILES_DIR, exist_ok=True)
os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)

# ============================================================
# DISPLAY SETUP
# ============================================================
epd = epd_driver.EPD()
epd.init()
epd.Clear()

display_image = Image.new('1', (epd.width, epd.height), 255)
display_draw = ImageDraw.Draw(display_image)

try:
    font_main = ImageFont.truetype('Courier Prime.ttf', 26)
    font_small = ImageFont.truetype('Courier Prime.ttf', 18)
except:
    font_main = ImageFont.load_default()
    font_small = font_main

# ============================================================
# LAYOUT CONSTANTS
# ============================================================
CHARS_PER_LINE = 48
VISIBLE_LINES = 12
LINE_HEIGHT = 34
TEXT_AREA_TOP = 30
STATUS_BAR_Y = 450

# ============================================================
# MODE CONSTANTS
# ============================================================
MODE_HOME = 0
MODE_TYPING = 1
MODE_FILESYSTEM = 2
MODE_FS_NEW_FILE = 3
MODE_FS_NEW_FOLDER = 4
MODE_FS_DELETE = 5
MODE_FS_RENAME = 6
MODE_WIFI_LIST = 7
MODE_WIFI_PASS = 8
MODE_WIFI_RESULT = 9
MODE_CLOUD_LOGIN = 10

# ============================================================
# STATE
# ============================================================
current_mode = MODE_HOME

# Editor state
lines = [""]
line_is_continuation = [False]  # True if line is continuation of previous (soft wrap)
current_line = 0
cursor_col = 0
scroll_offset = 0
current_file_path = None
console_message = ""

# Display state
display_lock = threading.Lock()
needs_refresh = threading.Event()
running = True

# Modifier state
shift_active = False
ctrl_active = False

# Filesystem state
fs_current_path = []
fs_items = []
fs_selected_index = 0
fs_page = 0
FS_ITEMS_PER_PAGE = 9
fs_modal_text = ""
fs_delete_selection = 0
came_from_filesystem = False  # Track if we entered typing from filesystem

# WiFi state
wifi_networks = []
wifi_selected_index = 0
wifi_password = ""
wifi_result_message = ""

# Cloud state
cloud_password = ""
cloud_message = ""

# ============================================================
# CLOUD FUNCTIONS
# ============================================================
def load_config():
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
    except:
        pass
    return {}

def save_config(config):
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f)
    except:
        pass

def cloud_login(password):
    try:
        response = requests.post(
            f"{CLOUD_API_URL}/api/login",
            json={"password": password},
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            if 'token' in data:
                config = load_config()
                config['auth_token'] = data['token']
                save_config(config)
                return True, "Logged in!"
        return False, "Invalid password"
    except requests.exceptions.Timeout:
        return False, "Timeout"
    except:
        return False, "Error"

def cloud_upload(file_path):
    config = load_config()
    token = config.get('auth_token')
    if not token or not os.path.exists(file_path):
        return False, "Not logged in"
    try:
        # Get the folder path for this file
        try:
            rel_path = os.path.relpath(file_path, FILES_DIR)
            dir_part = os.path.dirname(rel_path)
            if not dir_part or dir_part == '.':
                folder_path = "/"
            else:
                folder_path = "/" + dir_part.replace(os.sep, "/")
        except:
            folder_path = "/"

        with open(file_path, 'rb') as f:
            files = {'file': (os.path.basename(file_path), f, 'text/plain')}
            data = {'path': folder_path}
            headers = {'Authorization': f'Bearer {token}'}
            response = requests.patch(f"{CLOUD_API_URL}/api/notes", files=files, data=data, headers=headers, timeout=15)
        if response.status_code in [200, 201]:
            return True, "Synced!"
        elif response.status_code == 401:
            config['auth_token'] = None
            save_config(config)
            return False, "Login expired"
        return False, "Failed"
    except:
        return False, "Error"

def cloud_delete_folder(folder_path):
    """Delete a folder and all its contents from cloud"""
    config = load_config()
    token = config.get('auth_token')
    if not token:
        return False
    try:
        headers = {'Authorization': f'Bearer {token}'}
        response = requests.delete(
            f"{CLOUD_API_URL}/api/folders",
            params={'path': folder_path},
            headers=headers,
            timeout=15
        )
        return response.status_code == 200
    except:
        return False

def cloud_delete_file(title, folder_path):
    """Delete a file from cloud by title and path"""
    config = load_config()
    token = config.get('auth_token')
    if not token:
        return False
    try:
        headers = {'Authorization': f'Bearer {token}'}
        response = requests.delete(
            f"{CLOUD_API_URL}/api/notes/by-title",
            params={'title': title, 'path': folder_path},
            headers=headers,
            timeout=15
        )
        return response.status_code == 200
    except:
        return False

# ============================================================
# WIFI FUNCTIONS
# ============================================================
def wifi_scan_networks():
    try:
        # Use nmcli to scan
        subprocess.run(['sudo', 'nmcli', 'device', 'wifi', 'rescan'], timeout=10, capture_output=True)
        time.sleep(2)
        result = subprocess.run(
            ['nmcli', '-t', '-f', 'SSID', 'device', 'wifi', 'list'],
            capture_output=True, text=True, timeout=15
        )
        nets = []
        for line in result.stdout.splitlines():
            ssid = line.strip()
            if ssid and ssid not in nets:
                nets.append(ssid)
        return nets if nets else ["No networks found"]
    except:
        return ["Scan error"]

def wifi_try_connect(ssid, password):
    try:
        # Use nmcli to connect
        result = subprocess.run(
            ['sudo', 'nmcli', 'device', 'wifi', 'connect', ssid, 'password', password],
            capture_output=True, text=True, timeout=30
        )

        if result.returncode == 0 and 'successfully' in result.stdout.lower():
            return True, "Connected!"
        else:
            error_msg = result.stderr.strip() if result.stderr else "Failed"
            return False, error_msg[:20] if len(error_msg) > 20 else error_msg
    except subprocess.TimeoutExpired:
        return False, "Timeout"
    except Exception as e:
        return False, "Error"

# ============================================================
# FILESYSTEM FUNCTIONS
# ============================================================
def fs_get_full_path():
    return os.path.join(FILES_DIR, *fs_current_path)

def fs_get_display_path():
    if not fs_current_path:
        return "/"
    return "/" + "/".join(fs_current_path)

def fs_load_items():
    global fs_items, fs_selected_index, fs_page

    full_path = fs_get_full_path()
    os.makedirs(full_path, exist_ok=True)

    items = []
    try:
        for name in os.listdir(full_path):
            item_path = os.path.join(full_path, name)
            is_folder = os.path.isdir(item_path)
            items.append({'name': name, 'is_folder': is_folder})
    except:
        pass

    items.sort(key=lambda x: (0 if x['is_folder'] else 1, x['name'].lower()))
    fs_items = items
    fs_selected_index = min(fs_selected_index, max(0, len(fs_items) - 1))
    max_page = max(0, (len(fs_items) - 1) // FS_ITEMS_PER_PAGE)
    fs_page = min(fs_page, max_page)

def fs_create_file(name):
    if not name.strip():
        return False
    if not name.endswith('.txt'):
        name = name + '.txt'
    try:
        with open(os.path.join(fs_get_full_path(), name), 'w') as f:
            f.write('')
        return True
    except:
        return False

def fs_create_folder(name):
    if not name.strip():
        return False
    try:
        os.makedirs(os.path.join(fs_get_full_path(), name), exist_ok=True)
        return True
    except:
        return False

def fs_delete_item(index):
    if index < 0 or index >= len(fs_items):
        return False
    item = fs_items[index]
    full_path = os.path.join(fs_get_full_path(), item['name'])
    try:
        if item['is_folder']:
            # Delete from cloud first
            cloud_folder_path = fs_get_display_path()
            if cloud_folder_path == '/':
                cloud_folder_path = '/' + item['name']
            else:
                cloud_folder_path = cloud_folder_path + '/' + item['name']
            cloud_delete_folder(cloud_folder_path)
            # Then delete locally
            shutil.rmtree(full_path)
        else:
            # Delete file from cloud first
            cloud_folder_path = fs_get_display_path()
            file_name = item['name'].replace('.txt', '')
            cloud_delete_file(file_name, cloud_folder_path)
            # Then delete locally
            os.remove(full_path)
        return True
    except:
        return False

def fs_rename_item(index, new_name):
    if index < 0 or index >= len(fs_items):
        return False
    if not new_name.strip():
        return False

    item = fs_items[index]
    old_path = os.path.join(fs_get_full_path(), item['name'])

    # For files, ensure .txt extension
    if not item['is_folder'] and not new_name.endswith('.txt'):
        new_name = new_name + '.txt'

    new_path = os.path.join(fs_get_full_path(), new_name)

    try:
        # Rename locally
        os.rename(old_path, new_path)

        # For cloud, we'd need to update the note title
        # This is complex, so for now just re-upload if it's a file
        if not item['is_folder']:
            cloud_upload(new_path)

        return True
    except:
        return False

def fs_enter_item(index):
    global fs_current_path, fs_selected_index, fs_page, current_mode
    global current_file_path, lines, current_line, cursor_col, scroll_offset
    global came_from_filesystem

    if index < 0 or index >= len(fs_items):
        return

    item = fs_items[index]

    if item['is_folder']:
        fs_current_path.append(item['name'])
        fs_selected_index = 0
        fs_page = 0
        fs_load_items()
        trigger_refresh()
    else:
        full_path = os.path.join(fs_get_full_path(), item['name'])
        load_document(full_path)
        came_from_filesystem = True
        current_mode = MODE_TYPING
        trigger_refresh()

def fs_go_back():
    global fs_current_path, fs_selected_index, fs_page

    if fs_current_path:
        fs_current_path.pop()
        fs_selected_index = 0
        fs_page = 0
        fs_load_items()
        trigger_refresh()

# ============================================================
# FILE FUNCTIONS
# ============================================================
def get_content_for_save():
    """Join lines, keeping only hard breaks (Enter key), not soft wraps"""
    result = []
    current_paragraph = ""

    for i, line in enumerate(lines):
        if i == 0 or not line_is_continuation[i]:
            # This is a new paragraph (hard break before it)
            if current_paragraph or i > 0:
                result.append(current_paragraph)
            current_paragraph = line
        else:
            # This is a continuation (soft wrap) - join with space
            if current_paragraph and not current_paragraph.endswith(' '):
                current_paragraph += ' '
            current_paragraph += line

    # Don't forget the last paragraph
    result.append(current_paragraph)

    return '\n'.join(result)

def save_document():
    global console_message, current_file_path

    if not current_file_path:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        current_file_path = os.path.join(FILES_DIR, f"note_{timestamp}.txt")

    try:
        content = get_content_for_save()
        with open(current_file_path, 'w') as f:
            f.write(content)
        console_message = "[Saved]"
        trigger_refresh()

        success, msg = cloud_upload(current_file_path)
        console_message = "[Synced!]" if success else "[Local]"
        trigger_refresh()
    except:
        console_message = "[Error]"
        trigger_refresh()

def load_document(path):
    global lines, line_is_continuation, current_line, cursor_col, scroll_offset, current_file_path

    try:
        with open(path, 'r') as f:
            content = f.read()
        raw_lines = content.splitlines() if content else [""]
        if not raw_lines:
            raw_lines = [""]
    except:
        raw_lines = [""]

    # Re-wrap long lines for display
    lines = []
    line_is_continuation = []

    for raw_line in raw_lines:
        if len(raw_line) <= CHARS_PER_LINE:
            # Line fits, add as-is
            lines.append(raw_line)
            line_is_continuation.append(False if len(lines) == 1 or line_is_continuation[-1] == False else False)
            # First line of each paragraph is not a continuation
            if len(line_is_continuation) == 1:
                line_is_continuation[0] = False
            else:
                line_is_continuation[-1] = False
        else:
            # Line needs wrapping
            remaining = raw_line
            first_chunk = True
            while remaining:
                if len(remaining) <= CHARS_PER_LINE:
                    lines.append(remaining)
                    line_is_continuation.append(not first_chunk)
                    remaining = ""
                else:
                    # Find wrap point
                    wrap_point = remaining.rfind(' ', 0, CHARS_PER_LINE)
                    if wrap_point == -1:
                        wrap_point = CHARS_PER_LINE

                    lines.append(remaining[:wrap_point])
                    line_is_continuation.append(not first_chunk)
                    remaining = remaining[wrap_point:].lstrip()
                    first_chunk = False

    if not lines:
        lines = [""]
        line_is_continuation = [False]

    current_file_path = path
    # Position cursor at end of document
    current_line = len(lines) - 1
    cursor_col = len(lines[current_line])
    # Scroll to show the cursor
    if current_line >= VISIBLE_LINES:
        scroll_offset = current_line - VISIBLE_LINES + 1
    else:
        scroll_offset = 0

def load_cache():
    global current_file_path, lines, line_is_continuation, current_line, cursor_col, scroll_offset
    current_file_path = None
    if os.path.exists(CACHE_FILE):
        load_document(CACHE_FILE)
        current_file_path = None  # Reset so it stays as cache
    else:
        lines = [""]
        line_is_continuation = [False]
        current_line = 0
        cursor_col = 0
        scroll_offset = 0

def save_cache():
    try:
        content = get_content_for_save()
        with open(CACHE_FILE, 'w') as f:
            f.write(content)
    except:
        pass

# ============================================================
# DISPLAY FUNCTIONS
# ============================================================
def trigger_refresh():
    needs_refresh.set()

def get_visible_range():
    global scroll_offset

    if current_line < scroll_offset:
        scroll_offset = current_line
    elif current_line >= scroll_offset + VISIBLE_LINES:
        scroll_offset = current_line - VISIBLE_LINES + 1

    max_scroll = max(0, len(lines) - VISIBLE_LINES)
    scroll_offset = max(0, min(scroll_offset, max_scroll))

    return scroll_offset, min(scroll_offset + VISIBLE_LINES, len(lines))

def render_editor():
    display_draw.rectangle((0, 0, 800, 480), fill=255)

    # Header with filename
    if current_file_path:
        fname = os.path.basename(current_file_path)
        display_draw.text((10, 5), f"File: {fname}", font=font_small, fill=0)
    else:
        display_draw.text((10, 5), "Quick Write (cache)", font=font_small, fill=0)

    display_draw.line((0, 25, 800, 25), fill=0, width=1)

    # Get visible lines
    start_line, end_line = get_visible_range()

    # Draw text area
    y = TEXT_AREA_TOP
    for i in range(start_line, end_line):
        line = lines[i] if i < len(lines) else ""

        # Truncate display if too long
        display_text = line[:CHARS_PER_LINE]
        display_draw.text((10, y), display_text, font=font_main, fill=0)

        # Draw cursor if this is current line
        if i == current_line:
            text_before_cursor = line[:cursor_col]
            if text_before_cursor:
                bbox = font_main.getbbox(text_before_cursor)
                cursor_x = 10 + bbox[2]
            else:
                cursor_x = 10
            display_draw.line((cursor_x, y, cursor_x, y + LINE_HEIGHT - 6), fill=0, width=2)

        y += LINE_HEIGHT

    # Status bar
    display_draw.line((0, STATUS_BAR_Y - 5, 800, STATUS_BAR_Y - 5), fill=0, width=1)

    # Left: shortcuts
    display_draw.text((10, STATUS_BAR_Y), "^S:Save  ^R:Refresh  Esc:Home", font=font_small, fill=0)

    # Center: console message
    if console_message:
        display_draw.text((380, STATUS_BAR_Y), console_message, font=font_small, fill=0)

    # Right: line/col
    status = f"Ln:{current_line+1}/{len(lines)} Col:{cursor_col+1}"
    display_draw.text((670, STATUS_BAR_Y), status, font=font_small, fill=0)

def render_home():
    display_draw.rectangle((0, 0, 800, 480), fill=255)

    display_draw.text((280, 40), "Mae's Writer", font=font_main, fill=0)
    display_draw.line((100, 90, 700, 90), fill=0, width=2)

    config = load_config()
    cloud_status = "Logged In" if config.get('auth_token') else "Not Connected"

    y = 110
    display_draw.text((100, y), "Enter      = Quick Write", font=font_main, fill=0)
    y += 45
    display_draw.text((100, y), "Ctrl+F     = File System", font=font_main, fill=0)
    y += 45
    display_draw.text((100, y), "Ctrl+W     = WiFi Settings", font=font_main, fill=0)
    y += 45
    display_draw.text((100, y), "Ctrl+L     = Cloud Login", font=font_main, fill=0)
    y += 45
    display_draw.text((100, y), "Ctrl+R     = Refresh Screen", font=font_main, fill=0)
    y += 45
    display_draw.text((100, y), "Ctrl+Shift+Esc = Shutdown", font=font_main, fill=0)

    display_draw.line((100, 400, 700, 400), fill=0, width=1)
    display_draw.text((100, 415), f"Cloud: {cloud_status}", font=font_small, fill=0)
    display_draw.text((100, 445), "Esc = Home from anywhere", font=font_small, fill=0)

def render_filesystem():
    display_draw.rectangle((0, 0, 800, 480), fill=255)

    path_str = fs_get_display_path()
    if len(path_str) > 50:
        path_str = "..." + path_str[-47:]
    display_draw.text((10, 10), f"Path: {path_str}", font=font_small, fill=0)
    display_draw.line((0, 35, 800, 35), fill=0, width=2)

    start_idx = fs_page * FS_ITEMS_PER_PAGE
    end_idx = min(start_idx + FS_ITEMS_PER_PAGE, len(fs_items))

    y = 45
    for i in range(start_idx, end_idx):
        item = fs_items[i]
        if i == fs_selected_index:
            display_draw.rectangle((0, y - 2, 800, y + 38), fill=220)
        arrow = ">" if i == fs_selected_index else " "
        icon = "[D]" if item['is_folder'] else "[F]"
        name = item['name'][:40]
        display_draw.text((10, y), f"{arrow} {icon} {name}", font=font_main, fill=0)
        y += 42

    if not fs_items:
        display_draw.text((10, 50), "  (empty folder)", font=font_main, fill=0)

    total_pages = max(1, (len(fs_items) + FS_ITEMS_PER_PAGE - 1) // FS_ITEMS_PER_PAGE)
    display_draw.text((700, 10), f"Pg {fs_page + 1}/{total_pages}", font=font_small, fill=0)

    display_draw.line((0, 420, 800, 420), fill=0, width=2)
    display_draw.text((10, 430), "^N:New  ^G:Folder  ^D:Del  ^J:Rename", font=font_small, fill=0)
    display_draw.text((10, 455), "Enter:Open  Bksp:Back  Esc:Home", font=font_small, fill=0)

def render_fs_modal(title):
    display_draw.rectangle((0, 0, 800, 480), fill=255)
    display_draw.rectangle((50, 150, 750, 330), outline=0, width=3)
    display_draw.text((100, 170), title, font=font_main, fill=0)
    display_draw.rectangle((70, 220, 730, 280), outline=0, width=2)
    display_draw.text((80, 235), fs_modal_text + "_", font=font_main, fill=0)
    display_draw.text((100, 295), "Enter=Confirm  Esc=Cancel", font=font_small, fill=0)

def render_fs_rename():
    display_draw.rectangle((0, 0, 800, 480), fill=255)
    display_draw.rectangle((50, 150, 750, 330), outline=0, width=3)

    if fs_selected_index < len(fs_items):
        item = fs_items[fs_selected_index]
        item_type = "folder" if item['is_folder'] else "file"
        display_draw.text((100, 170), f"Rename {item_type}:", font=font_main, fill=0)

    display_draw.rectangle((70, 220, 730, 280), outline=0, width=2)
    display_draw.text((80, 235), fs_modal_text + "_", font=font_main, fill=0)
    display_draw.text((100, 295), "Enter=Rename  Esc=Cancel", font=font_small, fill=0)

def render_fs_delete():
    display_draw.rectangle((0, 0, 800, 480), fill=255)
    display_draw.rectangle((50, 150, 750, 330), outline=0, width=3)

    if fs_selected_index < len(fs_items):
        item = fs_items[fs_selected_index]
        name = item['name'][:30]
        item_type = "folder" if item['is_folder'] else "file"
        display_draw.text((100, 170), f"Delete {item_type}:", font=font_main, fill=0)
        display_draw.text((100, 210), f'"{name}"?', font=font_main, fill=0)

    cancel_prefix = ">" if fs_delete_selection == 0 else " "
    delete_prefix = ">" if fs_delete_selection == 1 else " "

    display_draw.text((200, 270), f"{cancel_prefix} Cancel", font=font_main, fill=0)
    display_draw.text((450, 270), f"{delete_prefix} Delete", font=font_main, fill=0)

def render_wifi():
    display_draw.rectangle((0, 0, 800, 480), fill=255)

    if current_mode == MODE_WIFI_LIST:
        display_draw.text((10, 10), "WiFi Networks:", font=font_main, fill=0)
        display_draw.line((0, 50, 800, 50), fill=0, width=2)
        y = 60
        for i, network in enumerate(wifi_networks[:10]):
            if i == wifi_selected_index:
                display_draw.rectangle((0, y - 2, 800, y + 38), fill=220)
            arrow = ">" if i == wifi_selected_index else " "
            display_draw.text((10, y), f"{arrow} {network}", font=font_main, fill=0)
            y += 40
        display_draw.text((10, 440), "Enter=Select | Esc=Home", font=font_small, fill=0)

    elif current_mode == MODE_WIFI_PASS:
        ssid = wifi_networks[wifi_selected_index] if wifi_networks else ""
        display_draw.text((10, 50), f"Network: {ssid}", font=font_main, fill=0)
        display_draw.text((10, 120), "Password:", font=font_main, fill=0)
        display_draw.rectangle((10, 170, 790, 230), outline=0, width=2)
        masked = "*" * len(wifi_password)
        display_draw.text((20, 185), masked + "_", font=font_main, fill=0)
        display_draw.text((10, 440), "Enter=Connect | Esc=Back", font=font_small, fill=0)

    elif current_mode == MODE_WIFI_RESULT:
        display_draw.text((200, 200), wifi_result_message, font=font_main, fill=0)
        display_draw.text((10, 440), "Esc=Home", font=font_small, fill=0)

def render_cloud_login():
    display_draw.rectangle((0, 0, 800, 480), fill=255)

    display_draw.text((280, 60), "Cloud Login", font=font_main, fill=0)
    display_draw.line((100, 110, 700, 110), fill=0, width=2)

    display_draw.text((100, 150), "Password:", font=font_main, fill=0)
    display_draw.rectangle((100, 200, 700, 260), outline=0, width=2)
    masked = "*" * len(cloud_password)
    display_draw.text((110, 215), masked + "_", font=font_main, fill=0)

    if cloud_message:
        display_draw.text((100, 300), cloud_message, font=font_main, fill=0)

    display_draw.text((100, 440), "Enter=Login | Esc=Cancel", font=font_small, fill=0)

def do_render():
    with display_lock:
        if current_mode == MODE_HOME:
            render_home()
        elif current_mode == MODE_TYPING:
            render_editor()
        elif current_mode == MODE_FILESYSTEM:
            render_filesystem()
        elif current_mode == MODE_FS_NEW_FILE:
            render_fs_modal("New File Name:")
        elif current_mode == MODE_FS_NEW_FOLDER:
            render_fs_modal("New Folder Name:")
        elif current_mode == MODE_FS_DELETE:
            render_fs_delete()
        elif current_mode == MODE_FS_RENAME:
            render_fs_rename()
        elif current_mode in (MODE_WIFI_LIST, MODE_WIFI_PASS, MODE_WIFI_RESULT):
            render_wifi()
        elif current_mode == MODE_CLOUD_LOGIN:
            render_cloud_login()

def display_thread():
    global running

    render_home()
    buf = epd.getbuffer(display_image)
    epd.display_Base(buf)
    epd.init_Partial()

    while running:
        needs_refresh.wait(timeout=0.1)

        if not running:
            break

        if needs_refresh.is_set():
            needs_refresh.clear()
            do_render()
            buf = epd.getbuffer(display_image)
            epd.display_Partial(buf)

def full_refresh_screen():
    do_render()
    buf = epd.getbuffer(display_image)
    epd.display_Base(buf)
    epd.init_Partial()

# ============================================================
# EDITOR FUNCTIONS
# ============================================================
def insert_char(char):
    global lines, line_is_continuation, cursor_col, current_line

    line = lines[current_line]
    lines[current_line] = line[:cursor_col] + char + line[cursor_col:]
    cursor_col += 1

    # Auto-wrap at CHARS_PER_LINE chars
    if len(lines[current_line]) > CHARS_PER_LINE:
        line = lines[current_line]
        # Find last space before limit
        wrap_point = line.rfind(' ', 0, CHARS_PER_LINE)
        if wrap_point == -1:
            wrap_point = CHARS_PER_LINE

        # Split the line
        before = line[:wrap_point]
        after = line[wrap_point:].lstrip()

        lines[current_line] = before
        lines.insert(current_line + 1, after)
        # Mark new line as continuation (soft wrap)
        line_is_continuation.insert(current_line + 1, True)

        # Move cursor to new line if it was past wrap point
        if cursor_col > wrap_point:
            current_line += 1
            cursor_col = cursor_col - wrap_point - 1
            if cursor_col < 0:
                cursor_col = 0

    trigger_refresh()

def delete_char():
    global lines, line_is_continuation, cursor_col, current_line

    if cursor_col > 0:
        line = lines[current_line]
        lines[current_line] = line[:cursor_col-1] + line[cursor_col:]
        cursor_col -= 1
    elif current_line > 0:
        prev_line = lines[current_line - 1]
        curr_line = lines[current_line]
        cursor_col = len(prev_line)
        lines[current_line - 1] = prev_line + curr_line
        del lines[current_line]
        del line_is_continuation[current_line]
        current_line -= 1

    trigger_refresh()

def new_line():
    global lines, line_is_continuation, current_line, cursor_col

    line = lines[current_line]
    left = line[:cursor_col]
    right = line[cursor_col:]

    lines[current_line] = left
    lines.insert(current_line + 1, right)
    # Mark as NOT a continuation (hard break from Enter key)
    line_is_continuation.insert(current_line + 1, False)
    current_line += 1
    cursor_col = 0

    trigger_refresh()

def move_up():
    global current_line, cursor_col
    if current_line > 0:
        current_line -= 1
        cursor_col = min(cursor_col, len(lines[current_line]))
        trigger_refresh()

def move_down():
    global current_line, cursor_col
    if current_line < len(lines) - 1:
        current_line += 1
        cursor_col = min(cursor_col, len(lines[current_line]))
        trigger_refresh()

def move_left():
    global current_line, cursor_col
    if cursor_col > 0:
        cursor_col -= 1
        trigger_refresh()
    elif current_line > 0:
        current_line -= 1
        cursor_col = len(lines[current_line])
        trigger_refresh()

def move_right():
    global current_line, cursor_col
    if cursor_col < len(lines[current_line]):
        cursor_col += 1
        trigger_refresh()
    elif current_line < len(lines) - 1:
        current_line += 1
        cursor_col = 0
        trigger_refresh()

# ============================================================
# KEYBOARD HANDLING
# ============================================================
def handle_key_down(e):
    global shift_active, ctrl_active
    if e.name in ('shift', 'left shift', 'right shift'):
        shift_active = True
    elif e.name in ('ctrl', 'left ctrl', 'right ctrl'):
        ctrl_active = True

def handle_key_up(e):
    global shift_active, ctrl_active, current_mode, console_message, running
    global wifi_networks, wifi_selected_index, wifi_password, wifi_result_message
    global fs_selected_index, fs_page, fs_modal_text, fs_delete_selection
    global cloud_password, cloud_message

    # Modifier releases
    if e.name in ('shift', 'left shift', 'right shift'):
        shift_active = False
        return
    elif e.name in ('ctrl', 'left ctrl', 'right ctrl'):
        ctrl_active = False
        return
    if e.name in ('alt', 'left alt', 'right alt'):
        return

    # ===== GLOBAL SHORTCUTS =====
    if e.name == 'r' and ctrl_active:
        epd.init()
        epd.Clear()
        full_refresh_screen()
        return

    if e.name == 'esc' and ctrl_active and shift_active:
        display_draw.rectangle((0, 0, 800, 480), fill=255)
        display_draw.text((300, 220), "Mae's Writer", font=font_main, fill=0)
        buf = epd.getbuffer(display_image)
        epd.display(buf)
        time.sleep(2)
        subprocess.run(['sudo', 'poweroff', '-f'])
        return

    # ===== CLOUD LOGIN =====
    if current_mode == MODE_CLOUD_LOGIN:
        if e.name == 'esc':
            current_mode = MODE_HOME
            cloud_password = ""
            cloud_message = ""
            full_refresh_screen()
        elif e.name == 'enter':
            cloud_message = "Logging in..."
            trigger_refresh()
            time.sleep(0.5)
            success, msg = cloud_login(cloud_password)
            cloud_message = msg
            trigger_refresh()
            time.sleep(1.5)
            if success:
                current_mode = MODE_HOME
                cloud_password = ""
                cloud_message = ""
                full_refresh_screen()
        elif e.name == 'backspace':
            cloud_password = cloud_password[:-1]
            trigger_refresh()
        elif e.name == 'space':
            cloud_password += ' '
            trigger_refresh()
        elif len(e.name) == 1:
            char = keymaps.shift_mapping.get(e.name, e.name.upper()) if shift_active else e.name
            cloud_password += char
            trigger_refresh()
        return

    # ===== FS MODALS =====
    if current_mode == MODE_FS_NEW_FILE:
        if e.name == 'esc':
            current_mode = MODE_FILESYSTEM
            fs_modal_text = ""
            trigger_refresh()
        elif e.name == 'enter':
            if fs_modal_text.strip():
                fs_create_file(fs_modal_text)
                fs_load_items()
            current_mode = MODE_FILESYSTEM
            fs_modal_text = ""
            trigger_refresh()
        elif e.name == 'backspace':
            fs_modal_text = fs_modal_text[:-1]
            trigger_refresh()
        elif e.name == 'space':
            fs_modal_text += ' '
            trigger_refresh()
        elif len(e.name) == 1:
            char = keymaps.shift_mapping.get(e.name, e.name.upper()) if shift_active else e.name
            fs_modal_text += char
            trigger_refresh()
        return

    if current_mode == MODE_FS_NEW_FOLDER:
        if e.name == 'esc':
            current_mode = MODE_FILESYSTEM
            fs_modal_text = ""
            trigger_refresh()
        elif e.name == 'enter':
            if fs_modal_text.strip():
                fs_create_folder(fs_modal_text)
                fs_load_items()
            current_mode = MODE_FILESYSTEM
            fs_modal_text = ""
            trigger_refresh()
        elif e.name == 'backspace':
            fs_modal_text = fs_modal_text[:-1]
            trigger_refresh()
        elif e.name == 'space':
            fs_modal_text += ' '
            trigger_refresh()
        elif len(e.name) == 1:
            char = keymaps.shift_mapping.get(e.name, e.name.upper()) if shift_active else e.name
            fs_modal_text += char
            trigger_refresh()
        return

    if current_mode == MODE_FS_DELETE:
        if e.name == 'esc':
            current_mode = MODE_FILESYSTEM
            trigger_refresh()
        elif e.name in ('left', 'right'):
            fs_delete_selection = 1 - fs_delete_selection
            trigger_refresh()
        elif e.name == 'enter':
            if fs_delete_selection == 1:
                fs_delete_item(fs_selected_index)
                fs_load_items()
            current_mode = MODE_FILESYSTEM
            trigger_refresh()
        return

    if current_mode == MODE_FS_RENAME:
        if e.name == 'esc':
            current_mode = MODE_FILESYSTEM
            fs_modal_text = ""
            trigger_refresh()
        elif e.name == 'enter':
            if fs_modal_text.strip():
                fs_rename_item(fs_selected_index, fs_modal_text)
                fs_load_items()
            current_mode = MODE_FILESYSTEM
            fs_modal_text = ""
            trigger_refresh()
        elif e.name == 'backspace':
            fs_modal_text = fs_modal_text[:-1]
            trigger_refresh()
        elif e.name == 'space':
            fs_modal_text += ' '
            trigger_refresh()
        elif len(e.name) == 1:
            char = keymaps.shift_mapping.get(e.name, e.name.upper()) if shift_active else e.name
            fs_modal_text += char
            trigger_refresh()
        return

    # ===== FILESYSTEM =====
    if current_mode == MODE_FILESYSTEM:
        if e.name == 'esc':
            if fs_current_path:
                # Go back one folder
                fs_current_path.pop()
                fs_selected_index = 0
                fs_page = 0
                fs_load_items()
                trigger_refresh()
            else:
                # At root, go to home
                current_mode = MODE_HOME
                full_refresh_screen()
        elif e.name == 'up':
            if fs_selected_index > 0:
                fs_selected_index -= 1
                if fs_selected_index < fs_page * FS_ITEMS_PER_PAGE:
                    fs_page = max(0, fs_page - 1)
                trigger_refresh()
        elif e.name == 'down':
            if fs_selected_index < len(fs_items) - 1:
                fs_selected_index += 1
                if fs_selected_index >= (fs_page + 1) * FS_ITEMS_PER_PAGE:
                    fs_page += 1
                trigger_refresh()
        elif e.name == 'enter':
            fs_enter_item(fs_selected_index)
        elif e.name == 'backspace':
            fs_go_back()
        elif e.name == 'n' and ctrl_active:
            current_mode = MODE_FS_NEW_FILE
            fs_modal_text = ""
            trigger_refresh()
        elif e.name == 'g' and ctrl_active:
            current_mode = MODE_FS_NEW_FOLDER
            fs_modal_text = ""
            trigger_refresh()
        elif e.name == 'd' and ctrl_active and fs_items:
            current_mode = MODE_FS_DELETE
            fs_delete_selection = 0
            trigger_refresh()
        elif e.name == 'j' and ctrl_active and fs_items:
            current_mode = MODE_FS_RENAME
            # Pre-fill with current name (without .txt for files)
            item = fs_items[fs_selected_index]
            if item['is_folder']:
                fs_modal_text = item['name']
            else:
                fs_modal_text = item['name'].replace('.txt', '')
            trigger_refresh()
        return

    # ===== WIFI =====
    if current_mode == MODE_WIFI_LIST:
        if e.name == 'esc':
            current_mode = MODE_HOME
            full_refresh_screen()
        elif e.name == 'up':
            wifi_selected_index = max(0, wifi_selected_index - 1)
            trigger_refresh()
        elif e.name == 'down':
            wifi_selected_index = min(len(wifi_networks) - 1, wifi_selected_index + 1)
            trigger_refresh()
        elif e.name == 'enter':
            if wifi_networks and not wifi_networks[wifi_selected_index].startswith("["):
                current_mode = MODE_WIFI_PASS
                wifi_password = ""
                trigger_refresh()
        return

    if current_mode == MODE_WIFI_PASS:
        if e.name == 'esc':
            current_mode = MODE_WIFI_LIST
            wifi_password = ""
            trigger_refresh()
        elif e.name == 'backspace':
            wifi_password = wifi_password[:-1]
            trigger_refresh()
        elif e.name == 'enter':
            ssid = wifi_networks[wifi_selected_index]
            display_draw.rectangle((0, 0, 800, 480), fill=255)
            display_draw.text((300, 200), "Connecting...", font=font_main, fill=0)
            buf = epd.getbuffer(display_image)
            epd.display_Partial(buf)
            ok, msg = wifi_try_connect(ssid, wifi_password)
            wifi_result_message = msg
            current_mode = MODE_WIFI_RESULT
            trigger_refresh()
        elif e.name == 'space':
            wifi_password += ' '
            trigger_refresh()
        elif len(e.name) == 1:
            char = keymaps.shift_mapping.get(e.name, e.name.upper()) if shift_active else e.name
            wifi_password += char
            trigger_refresh()
        return

    if current_mode == MODE_WIFI_RESULT:
        if e.name == 'esc':
            current_mode = MODE_HOME
            full_refresh_screen()
        return

    # ===== HOME SCREEN =====
    if current_mode == MODE_HOME:
        if e.name == 'enter':
            global came_from_filesystem
            came_from_filesystem = False
            current_mode = MODE_TYPING
            load_cache()
            trigger_refresh()
        elif e.name == 'f' and ctrl_active:
            current_mode = MODE_FILESYSTEM
            fs_load_items()
            trigger_refresh()
        elif e.name == 'w' and ctrl_active:
            current_mode = MODE_WIFI_LIST
            wifi_selected_index = 0
            display_draw.rectangle((0, 0, 800, 480), fill=255)
            display_draw.text((300, 200), "Scanning...", font=font_main, fill=0)
            buf = epd.getbuffer(display_image)
            epd.display_Partial(buf)
            wifi_networks = wifi_scan_networks()
            trigger_refresh()
        elif e.name == 'l' and ctrl_active:
            current_mode = MODE_CLOUD_LOGIN
            cloud_password = ""
            cloud_message = ""
            trigger_refresh()
        return

    # ===== ESCAPE FROM TYPING =====
    if e.name == 'esc' and current_mode == MODE_TYPING:
        save_cache()
        if came_from_filesystem:
            # Go back to the folder containing this file
            current_mode = MODE_FILESYSTEM
            fs_load_items()
            trigger_refresh()
        else:
            current_mode = MODE_HOME
            full_refresh_screen()
        return

    # ===== ESCAPE TO HOME (other modes) =====
    if e.name == 'esc':
        current_mode = MODE_HOME
        full_refresh_screen()
        return

    # ===== TYPING MODE =====
    if current_mode == MODE_TYPING:
        if ctrl_active:
            if e.name == 's':
                save_document()
                time.sleep(1)
                console_message = ""
                trigger_refresh()
            elif e.name == 'f':
                save_cache()
                current_mode = MODE_FILESYSTEM
                fs_load_items()
                trigger_refresh()
            return

        if e.name == 'up':
            move_up()
        elif e.name == 'down':
            move_down()
        elif e.name == 'left':
            move_left()
        elif e.name == 'right':
            move_right()
        elif e.name == 'backspace':
            delete_char()
        elif e.name == 'enter':
            new_line()
        elif e.name == 'space':
            insert_char(' ')
        elif e.name == 'tab':
            insert_char('    ')
        elif len(e.name) == 1:
            char = keymaps.shift_mapping.get(e.name, e.name.upper()) if shift_active else e.name
            insert_char(char)

def handle_interrupt(sig, frame):
    global running
    running = False
    keyboard.unhook_all()
    epd.init()
    display_draw.rectangle((0, 0, 800, 480), fill=255)
    display_draw.text((300, 220), "Mae's Writer", font=font_main, fill=0)
    buf = epd.getbuffer(display_image)
    epd.display(buf)
    time.sleep(1)
    epd.sleep()
    exit(0)

# ============================================================
# MAIN
# ============================================================
print("Starting Mae's Writer...")

keyboard.on_press(handle_key_down, suppress=False)
keyboard.on_release(handle_key_up, suppress=True)
signal.signal(signal.SIGINT, handle_interrupt)

disp_thread = threading.Thread(target=display_thread, daemon=True)
disp_thread.start()

try:
    while running:
        time.sleep(0.1)
except KeyboardInterrupt:
    pass
finally:
    running = False
    time.sleep(0.5)
    keyboard.unhook_all()
    epd.init()
    display_draw.rectangle((0, 0, 800, 480), fill=255)
    display_draw.text((300, 220), "Mae's Writer", font=font_main, fill=0)
    buf = epd.getbuffer(display_image)
    epd.display(buf)
    time.sleep(1)
    epd.sleep()

# i love you mae :))
