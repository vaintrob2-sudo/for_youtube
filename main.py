from flask import Flask, request, jsonify
import yt_dlp
import os
import tempfile
import threading
import uuid
import requests

app = Flask(__name__)
API_KEY = os.environ.get("API_KEY", "changeme")

# מאגר סטטוס jobs
jobs = {}

def get_access_token():
    """מקבל access token מהר באמצעות refresh token"""
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
    """מעלה קובץ לדרייב ישירות"""
    metadata = {"name": filename}
    if folder_id:
        metadata["parents"] = [folder_id]

    with open(file_path, 'rb') as f:
        resp = requests.post(
            "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart",
            headers={"Authorization": "Bearer " + access_token},
            files={
                "metadata": ("metadata", str(metadata).replace("'", '"'), "application/json"),
                "file": (filename, f, "video/mp4")
            }
        )
    return resp.json()

def download_and_upload(job_id, video_url, quality, filename, folder_id):
    """מוריד מיוטיוב ומעלה לדרייב ברקע"""
    try:
        jobs[job_id]["status"] = "DOWNLOADING"

        # בחירת פורמט
        if quality == "audio":
            fmt = "bestaudio[ext=m4a]/bestaudio"
            ext = "m4a"
        elif quality == "1080":
            fmt = "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]"
            ext = "mp4"
        elif quality == "480":
            fmt = "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480]"
            ext = "mp4"
        elif quality == "360":
            fmt = "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360]"
            ext = "mp4"
        else:
            fmt = "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]"
            ext = "mp4"

        # תיקיית הורדה זמנית
        tmp_dir = tempfile.mkdtemp()
        out_path = os.path.join(tmp_dir, "video.%(ext)s")

        cookies_file = get_cookies_file()

        ydl_opts = {
            "format": fmt,
            "outtmpl": out_path,
            "quiet": True,
            "no_warnings": True,
            "merge_output_format": "mp4",
        }
        if cookies_file:
            ydl_opts["cookiefile"] = cookies_file

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            title = info.get("title", "video")

        # מצא את הקובץ שהורד
        downloaded_file = None
        for f in os.listdir(tmp_dir):
            downloaded_file = os.path.join(tmp_dir, f)
            break

        if not downloaded_file:
            jobs[job_id]["status"] = "FAILED"
            jobs[job_id]["error"] = "הקובץ לא נמצא אחרי הורדה"
            return

        jobs[job_id]["status"] = "UPLOADING"

        # קבל access token והעלה לדרייב
        access_token = get_access_token()
        final_filename = filename or (title + "." + ext)
        result = upload_to_drive(downloaded_file, final_filename, folder_id, access_token)

        # נקה קובץ זמני
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

    # מריץ ברקע
    t = threading.Thread(target=download_and_upload, args=(job_id, video_url, quality, filename, folder_id))
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
