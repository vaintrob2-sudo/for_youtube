from flask import Flask, request, jsonify
import yt_dlp
import os
import tempfile

# בתחילת הקובץ, אחרי הimports
def get_cookies_file():
    cookies_content = os.environ.get("YOUTUBE_COOKIES", "")
    if not cookies_content:
        return None
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
    tmp.write(cookies_content)
    tmp.close()
    return tmp.name


app = Flask(__name__)
API_KEY = os.environ.get("API_KEY", "changeme")

@app.route("/get-url")
def get_url():
    if request.headers.get("X-API-Key") != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    video_url = request.args.get("url")
    quality = request.args.get("quality", "720")

    if not video_url:
        return jsonify({"error": "Missing url parameter"}), 400

    # בחירת פורמט לפי איכות
    if quality == "audio":
        fmt = "bestaudio[ext=m4a]/bestaudio"
    elif quality == "1080":
        fmt = "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]"
    elif quality == "480":
        fmt = "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480]"
    elif quality == "360":
        fmt = "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360]"
    else:  # 720 default
        fmt = "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]"

    ydl_opts = {
        "format": fmt,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,          # חשוב! רק חילוץ URL, לא הורדה
        "extract_flat": False,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)

        # אם יש video+audio נפרדים, מחזירים את ה-video (Apps Script ימזג אם צריך)
        # אבל בד"כ best[...] מחזיר קובץ מאוחד
        direct_url = info.get("url") or (info.get("requested_formats") or [{}])[0].get("url")
        title = info.get("title", "")
        duration = info.get("duration", 0)
        filesize = info.get("filesize") or info.get("filesize_approx") or 0

        return jsonify({
            "success": True,
            "url": direct_url,
            "title": title,
            "duration": duration,
            "filesize": filesize,
            "ext": info.get("ext", "mp4")
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
