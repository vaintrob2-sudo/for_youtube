from flask import Flask, request, jsonify
import yt_dlp
import os
import tempfile
import threading
import uuid
import requests
import json as json_lib

app = Flask(__name__)
API_KEY = os.environ.get("API_KEY", "changeme")

jobs = {}

def get_access_token():
    resp = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": os.environ.get("GOOGLE_CLIENT_ID"),
        "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET"),
        "refresh_token": os.environ.get("GOOGLE_REFRESH_TOKEN"),
        "grant_type": "refresh_token"
    })
    return resp.json().get("access_token")

def get_cookies_file():
    cookies_content = os.environ.get("YOUTUBE_COOKIES", "")
    if not cookies_content:
        return None
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
    tmp.write(cookies_content)
    tmp.close()
    return tmp.name

def upload_to_drive(file_path, filename, folder_id, access_token):
    metadata = {"name": filename}
    if folder_id:
        metadata["parents"] = [folder_id]

    file_size = os.path.getsize(file_path)

    init_resp = requests.post(
        "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable",
        headers={
            "Authorization": "Bearer " + access_token,
            "Content-Type": "application/json",
            "X-Upload-Content-Length": str(file_size),
        },
        data=json_lib.dumps(metadata)
    )

    upload_url = init_resp.headers.get("Location")
    if not upload_url:
        return {"error": "Failed to get upload URL", "details": init_resp.text}

    chunk_size = 10 * 1024 * 1024
    uploaded = 0

    with open(file_path, 'rb') as f:
        while uploaded < file_size:
            chunk = f.read(chunk_size)
            end = uploaded + len(chunk) - 1
            resp = requests.put(
                upload_url,
                headers={
                    "Content-Range": f"bytes {uploaded}-{end}/{file_size}",
                    "Content-Length": str(len(chunk)),
                },
                data=chunk
            )
            uploaded += len(chunk)

            if resp.status_code in (200, 201):
                return resp.json()
            elif resp.status_code == 308:
                continue
            else:
                return {"error": f"Upload failed at {uploaded}", "status": resp.status_code}

    return {"error": "Upload ended without completion"}

def is_youtube(url):
    return "youtube.com" in url or "youtu.be" in url

def download_direct(job_id, video_url, filename, folder_id):
    try:
        jobs[job_id]["status"] = "DOWNLOADING"
        print(f"Starting direct download: {video_url}")

        tmp_dir = tempfile.mkdtemp()

        from urllib.parse import urlparse
        path = urlparse(video_url).path
        ext = os.path.splitext(path)[1] or ".bin"
        base = os.path.basename(path) or "file"
        final_filename = filename or (base if ext in base else base + ext)
        out_path = os.path.join(tmp_dir, final_filename)

        headers = {"User-Agent": "Mozilla/5.0"}
        with requests.get(video_url, stream=True, timeout=3600, headers=headers) as r:
            print(f"HTTP status: {r.status_code}, Content-Length: {r.headers.get('Content-Length')}")
            r.raise_for_status()
            total = 0
            with open(out_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=1024*1024):
                    f.write(chunk)
                    total += len(chunk)
            print(f"Downloaded {total} bytes")

        jobs[job_id]["status"] = "UPLOADING"
        access_token = get_access_token()
        result = upload_to_drive(out_path, final_filename, folder_id, access_token)
        print(f"Upload result: {result}")
        os.remove(out_path)

        if "id" in result:
            jobs[job_id]["status"] = "COMPLETED"
            jobs[job_id]["file_id"] = result["id"]
            jobs[job_id]["title"] = final_filename
        else:
            jobs[job_id]["status"] = "FAILED"
            jobs[job_id]["error"] = str(result)

    except Exception as e:
        print(f"download_direct error: {e}")
        jobs[job_id]["status"] = "FAILED"
        jobs[job_id]["error"] = str(e)

def download_and_upload(job_id, video_url, quality, filename, folder_id):
    try:
        jobs[job_id]["status"] = "DOWNLOADING"
        import subprocess
        result = subprocess.run(["which", "qjs"], capture_output=True, text=True)
        print(f"qjs path: {result.stdout.strip()}")

        if quality == "audio":
            fmt = "bestaudio/best"
            ext = "m4a"
        elif quality == "1080":
            fmt = "best[height<=1080]/best"
            ext = "mp4"
        elif quality == "480":
            fmt = "best[height<=480]/best"
            ext = "mp4"
        elif quality == "360":
            fmt = "best[height<=360]/best"
            ext = "mp4"
        else:
            fmt = "best[height<=720]/best"
            ext = "mp4"

        tmp_dir = tempfile.mkdtemp()
        out_path = os.path.join(tmp_dir, "video.%(ext)s")

        cookies_file = get_cookies_file()

        print(f"fmt: {fmt}")
        print(f"cookies_file exists: {cookies_file is not None}")

        ydl_opts = {
            "format": fmt,
            "outtmpl": out_path,
            "quiet": True,
            "no_warnings": False,
            "verbose": True,
            "merge_output_format": "mp4",
            "format_sort": ["res", "ext:mp4:m4a"],
            "extractor_args": {"youtube": {"player_client": ["web", "tv"]}},
            "socket_timeout": 30,
            "nocheckcertificate": True,
        }
        if cookies_file:
            ydl_opts["cookiefile"] = cookies_file

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            title = info.get("title", "video")

        downloaded_file = None
        for f in os.listdir(tmp_dir):
            downloaded_file = os.path.join(tmp_dir, f)
            break

        if not downloaded_file:
            jobs[job_id]["status"] = "FAILED"
            jobs[job_id]["error"] = "הקובץ לא נמצא אחרי הורדה"
            return

        jobs[job_id]["status"] = "UPLOADING"

        access_token = get_access_token()
        final_filename = filename or (title + "." + ext)
        result = upload_to_drive(downloaded_file, final_filename, folder_id, access_token)

        os.remove(downloaded_file)

        if "id" in result:
            jobs[job_id]["status"] = "COMPLETED"
            jobs[job_id]["file_id"] = result["id"]
            jobs[job_id]["title"] = title
        else:
            jobs[job_id]["status"] = "FAILED"
            jobs[job_id]["error"] = str(result)

    except Exception as e:
        jobs[job_id]["status"] = "FAILED"
        jobs[job_id]["error"] = str(e)

@app.route("/download")
def download():
    if request.headers.get("X-API-Key") != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    video_url = request.args.get("url")
    quality = request.args.get("quality", "720")
    filename = request.args.get("filename", "")
    folder_id = request.args.get("folderId", "")

    if not video_url:
        return jsonify({"error": "Missing url"}), 400

    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "QUEUED"}

    if is_youtube(video_url):
        target = download_and_upload
        args = (job_id, video_url, quality, filename, folder_id)
    else:
        target = download_direct
        args = (job_id, video_url, filename, folder_id)

    t = threading.Thread(target=target, args=args)
    t.daemon = True
    t.start()

    return jsonify({"jobId": job_id, "status": "QUEUED"})

@app.route("/status/<job_id>")
def status(job_id):
    if request.headers.get("X-API-Key") != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    return jsonify(job)

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
