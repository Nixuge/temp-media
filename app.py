#!./.venv/bin/python

# -*- coding: utf-8 -*-

import random
import shutil
import string
import threading
import time
from flask import Flask, render_template, request, send_from_directory
import os
from gevent.pywsgi import WSGIServer
import json
import subprocess

app = Flask(__name__)


def load_vars(config_filename: str = "config.json"):
    try:
        data = None
        with open(config_filename) as json_file:
            data = json.load(json_file)

        VARS.secret = data["secret"]
        VARS.website_root = data["website_root"]
        VARS.media_serve_url_panel = data["media_serve_url_panel"]
        VARS.media_serve_url_embed = data["media_serve_url_embed"]
        VARS.media_path = data["media_path"]
        VARS.meta_subfolder = data["meta_subfolder"]
        VARS.symlink_subfolder = data["symlink_subfolder"]
        VARS.server_port = data["server_port"]

        if os.path.exists(f"{VARS.media_path}/{VARS.meta_subfolder}/symlinks.json"):
            with open(f"{VARS.media_path}/{VARS.meta_subfolder}/symlinks.json") as f:
                VARS.symlinks = json.load(f)
        
        if os.path.exists(f"{VARS.media_path}/{VARS.meta_subfolder}/comments.json"):
            with open(f"{VARS.media_path}/{VARS.meta_subfolder}/comments.json") as f:
                VARS.comments = json.load(f)
        
        # Check if all symlinks present should be present.
        all_known_links = []
        for _media_name, files in VARS.symlinks.items():
            for symlink_name in files.keys():
                all_known_links.append(symlink_name)
        
        all_known_thumbs = []
        for link in all_known_links:
            if is_video(link):
                all_known_thumbs.append(link + "-thumb.png")

        all_known_links += all_known_thumbs
        for file in os.listdir(f"{VARS.media_path}/{VARS.symlink_subfolder}"):
            if file not in all_known_links:
                print("Symlink file has nothing to do here: " + file)
                os.remove(f"{VARS.media_path}/{VARS.symlink_subfolder}/{file}")

        return True
    
    except Exception as e: 
        return e

class VARS: #default vars, you still need a json.
    secret: str
    website_root: str
    media_serve_url_panel: str
    media_serve_url_embed: str
    media_path: str
    meta_subfolder: str
    symlink_subfolder: str
    server_port: int
    thread_running = True
    comments: dict[str, str] = {} #TOOD: IMPLEMENT
    symlinks: dict[str, dict[str, dict[str, str | int]]] = {} 
    # {original_filename: {symlinks_name1: {expiry: ..., name: ...}, {symlink_name2: ...}} }
    external_to_remove: list[tuple[str, str]] = []


def is_video(filename: str):
    filename = filename.lower()
    return filename.endswith(".mov") or filename.endswith(".mp4")

def is_image(filename: str):
    filename = filename.lower()
    return filename.endswith(".png") or filename.endswith(".jpg") or filename.endswith(".heic") or filename.endswith(".jpeg")


def has_thumb(filename: str):
    return os.path.exists(f"{VARS.media_path}/{VARS.meta_subfolder}/{filename}-thumb.png")


def gen_thumb(filename: str):
    duration = get_length(filename)
    middle_time = duration / 2

    os.system(f'ffmpeg -i "{VARS.media_path}/{filename}" -ss {middle_time} -frames:v 1 "{VARS.media_path}/{VARS.meta_subfolder}/{filename}-thumb.png"')


# Thanks to https://stackoverflow.com/a/3844467/10321409
def get_length(filename: str):
    duration_path = f"{VARS.media_path}/{VARS.meta_subfolder}/{filename}-duration.txt"
    
    try:
        if os.path.exists(duration_path):
            with open(duration_path) as f:
                return float(f.read())
    except: pass

    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                             "format=duration", "-of",
                             "default=noprint_wrappers=1:nokey=1", f"{VARS.media_path}/{filename}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT)
    
    out = result.stdout

    with open(duration_path, "w") as f:
        f.write(str(float(out)))
    
    return float(out)


def list_all_files():
    files = [os.path.join(VARS.media_path, f) for f in os.listdir(VARS.media_path)]
    # for file in files:
        # if not os.path.isfile(file):
    files = list(filter(os.path.isfile, files))
    files.sort(key=lambda x: os.path.getmtime(x))
    for i, f in enumerate(files):
        files[i] = f.replace(f"{VARS.media_path}/", "").replace(f"{VARS.media_path}", "")

    files.reverse()

    # Note: before this func was generating the length,
    # but not really needed here tbh, can just skip. (at least for now, until maybe implement in webui root).

    all = []
    for file in files:
        if is_video(file):
            if not has_thumb(file):
                gen_thumb(file)
            # all.append((file, get_length(file)))
            all.append((file, None))
        
        elif is_image(file):
            all.append((file, None))

    res = []
    for file in all:
        res.append({
            "filename": file[0],
            # "duration": file[1],
            "comment": VARS.comments.get(file[0])
        })

    return res




lock = threading.Lock()
def write_new_symlink_dict_to_json():
    with lock:
        with open(f"{VARS.media_path}/{VARS.meta_subfolder}/symlinks.json", "w") as f:
            json.dump(VARS.symlinks, f)




def add_to_dict(original_filename: str, symlink_filename: str, expires_on: int):
    if not original_filename in VARS.symlinks.keys():
        VARS.symlinks[original_filename] = {}

    VARS.symlinks[original_filename][symlink_filename] = {
        "filename": symlink_filename,
        "expires_on": expires_on
    }
    
    write_new_symlink_dict_to_json()


def add_symlink(filename: str, expires_on: int) -> str:
    if not os.path.exists(f"{VARS.media_path}/{filename}"):
        raise Exception("File does not exist.")

    symlink_name = ''.join(random.choices(string.ascii_uppercase + string.digits, k=20))
    ext = filename.split(".")[-1]
    symlink_filename = f"{symlink_name}.{ext}"

    os.system(f'ln -s "{VARS.media_path}/{filename}" "{VARS.media_path}/{VARS.symlink_subfolder}/{symlink_filename}"')
    if is_video(filename):
        os.system(f'ln -s "{VARS.media_path}/{VARS.meta_subfolder}/{filename}-thumb.png" "{VARS.media_path}/{VARS.symlink_subfolder}/{symlink_filename}-thumb.png"')

    if not os.path.exists(f"{VARS.media_path}/{VARS.symlink_subfolder}/{symlink_filename}"):
        raise Exception("New symlink does not exist.")
    
    add_to_dict(filename, symlink_filename, expires_on)

    return symlink_filename
    

# ========== PANEL ROUTES ==========
@app.route("/")
def index():
    if request.cookies.get("authToken") != VARS.secret:
        return render_template("auth.html")
    
    return render_template(
        "index.html",
        media_serve_url_panel = VARS.media_serve_url_panel,
        symlink_subfolder = VARS.symlink_subfolder,
        meta_subfolder = VARS.meta_subfolder,
        files = list_all_files(),
        token = VARS.secret
    )


@app.route("/upload")
def upload_page():
    if request.cookies.get("authToken") != VARS.secret:
        return render_template("auth.html")
    
    return render_template(
        "upload.html",
        website_root = VARS.website_root,
        token = VARS.secret
    )

@app.route("/file/<filename>")
def file_data(filename: str):
    if request.cookies.get("authToken") != VARS.secret:
        return render_template("auth.html")
    
    duration = 0
    if is_video(filename):
        duration = get_length(filename)

    return render_template(
        "media.html",
        website_root = VARS.website_root,
        media_serve_url_embed = VARS.media_serve_url_embed,
        media_serve_url_panel = VARS.media_serve_url_panel,
        symlink_subfolder = VARS.symlink_subfolder,
        meta_subfolder = VARS.meta_subfolder,
        duration = duration,
        symlinks = VARS.symlinks.get(filename),
        comments = VARS.comments.get(filename),
        filename = filename,
        token = VARS.secret
    )



# ========== API ROUTES ==========
@app.route("/api/create_symlink", methods = ["POST"])
def create_symlink():
    if request.json["token"] != VARS.secret: #type: ignore
        return "Bad auth token", 403

    filename = request.json["filename"] #type: ignore
    expires_in_seconds = request.json["expires_in_seconds"] #type: ignore

    return add_symlink(filename, expires_in_seconds + (time.time_ns() / 1000000000))


@app.route("/api/delete_symlink", methods = ["POST"])
def delete_symlink():
    if request.json["token"] != VARS.secret: #type: ignore
        return "Bad auth token", 403
    
    filename = request.json["filename"] #type: ignore
    symlink_name = request.json["symlink_name"] #type: ignore

    VARS.external_to_remove.append((filename, symlink_name))
    VARS.symlinks[filename].pop(symlink_name) # Have it disappear instantly from the ui.

    # write_new_symlink_dict_to_json() # Updated in thread anyways, not required.
    return "success"


@app.route("/api/set_comment", methods = ["POST"])
def set_comment():
    if request.json["token"] != VARS.secret: #type: ignore
        return "Bad auth token", 403

    filename = request.json["filename"] #type: ignore
    new_comment = request.json["new_comment"] #type: ignore
    print(filename)
    print(new_comment)
    VARS.comments[filename] = new_comment
    with open(f"{VARS.media_path}/{VARS.meta_subfolder}/comments.json", "w") as f:
        json.dump(VARS.comments, f)
    
    return "success"


@app.route('/api/upload_file', methods=['POST'])
def upload_file():
    token = request.form.get('token')
    if not token:
        return 'No token provided', 400
    if token != VARS.secret:
        return "Bad auth token", 403
    
    if 'file' not in request.files:
        return 'No file part', 400

    files = request.files.getlist('file')
    if not files or all(file.filename == '' for file in files):
        return 'No selected file', 400

    for file in files:
        if file.filename != '':
            file.save(f"{VARS.media_path}/{file.filename}")

    file.save(f"{VARS.media_path}/{file.filename}")
    return 'File uploaded successfully'


@app.route('/api/delete_file', methods=['POST'])
def delete_file():
    if request.json["token"] != VARS.secret: #type: ignore
        return "Bad auth token", 403
    
    filename = request.json['filename'] #type: ignore
    
    os.remove(f"{VARS.media_path}/{filename}")
    if is_video(filename):
        os.remove(f"{VARS.media_path}/{VARS.meta_subfolder}/{filename}-thumb.png")
        os.remove(f"{VARS.media_path}/{VARS.meta_subfolder}/{filename}-duration.txt") #Note: May get reworked anyways.
    
    for link in VARS.symlinks.get(filename, {}).keys():
        VARS.external_to_remove.append((filename, link))

    return 'File deleted successfully'


# ========== PUBLIC ROUTES ==========
@app.route('/embed/<filename>')
def embed_page(filename: str):
    if not os.path.exists(f"{VARS.media_path}/{VARS.symlink_subfolder}/{filename}"):
        return render_template("embed_missing.html")
    
    url = f"{VARS.media_serve_url_embed}/{filename}"
    return render_template(
        "embed.html",
        filename = filename,
        is_video = is_video(filename),
        thumb_url = url + "-thumb.png" if is_video(filename) else url,
        url = url
    )


# ========== DEBUG ROUTE ==========
# TO NOT BE USED: Please serve with NGINX or equivalent instead.
@app.route('/temp_media/<path:filename>')
def serve_media(filename: str):
    if request.cookies.get("authToken") != VARS.secret:
        return render_template("auth.html")
    
    return send_from_directory(VARS.media_path, filename)


# ========== END OF FLASK ROUTES ==========



def thread_func():
    while VARS.thread_running:
        current_time = time.time_ns() / 1000000000
        to_remove: list[tuple[str, str]] = []
        for original_filename, symlinks in VARS.symlinks.items():
            for symlink, symlink_data in symlinks.items():
                if current_time >= symlink_data["expires_on"]: #type: ignore
                    to_remove.append((original_filename, symlink))

        if len(to_remove) > 0 or len(VARS.external_to_remove) > 0:
            all_to_remove = to_remove + VARS.external_to_remove
            VARS.external_to_remove.clear()

            for symlink in all_to_remove:
                try:
                    print(f"Trying to delete {symlink}")
                    symlink_name = symlink[1]
                    media_name = symlink[0]
                    os.remove(f"{VARS.media_path}/{VARS.symlink_subfolder}/{symlink_name}")
                    if is_video(media_name):
                        os.remove(f"{VARS.media_path}/{VARS.symlink_subfolder}/{symlink_name}-thumb.png")
                    if not media_name in VARS.symlinks.keys() or not symlink_name in VARS.symlinks[media_name].keys():
                        print("Symlink deleted but couldn't find path in symlink dict.")
                    else:
                        VARS.symlinks[media_name].pop(symlink_name)
                    print("Done deleting symlink.")
                except: 
                    print(f"Failed to remove {symlink}")
                    pass
            try:
                write_new_symlink_dict_to_json()
                print("Updated symlink json")
            except:
                print("Failed to save new symlink json")
            
        time.sleep(10)

if __name__ == "__main__":
    print("Loading config")
    config_res = load_vars()
    if config_res != True:
        print(f"Issue loading the config ! make sure it's there and that everything is set correctly ({config_res})")
        exit(1)
    
    if not os.path.exists(f"{VARS.media_path}/{VARS.meta_subfolder}"):
        os.makedirs(f"{VARS.media_path}/{VARS.meta_subfolder}")
    
    if not os.path.exists(f"{VARS.media_path}/{VARS.symlink_subfolder}"):
        os.makedirs(f"{VARS.media_path}/{VARS.symlink_subfolder}")
    print("Starting thread")
    threading.Thread(target=thread_func).start()

    print("Starting webserver")
    http_server = WSGIServer(('', VARS.server_port), app)
    try:
        http_server.serve_forever()
    except:
        VARS.thread_running = False