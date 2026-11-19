import glob
import os
import shutil
import tempfile
import zipfile
from urllib.parse import urlparse

import yt_dlp
from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from starlette.background import BackgroundTask

app = FastAPI(title="YouTube MP3 Cloud")


def get_ffmpeg_dir():
    """Locate ffmpeg binary if not already present on system PATH."""
    if shutil.which("ffmpeg"):
        return None
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        winget_pattern = os.path.join(
            local_app_data, "Microsoft", "WinGet", "Packages", "*ffmpeg*", "**", "ffmpeg.exe"
        )
        matches = glob.glob(winget_pattern, recursive=True)
        if matches:
            return os.path.dirname(matches[0])
    return None


# Browser interface
@app.get("/", response_class=HTMLResponse)
def home():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>MP3 Downloader</title>
        <style>
            body {
                background: #151515;
                color: white;
                font-family: Arial, sans-serif;
                text-align: center;
                padding: 100px 20px;
            }
            input, button {
                padding: 14px;
                margin: 10px;
                border-radius: 8px;
                border: none;
                font-size: 15px;
            }
            input {
                width: 380px;
                max-width: 90%;
                background: #252525;
                color: white;
                box-sizing: border-box;
            }
            input:focus {
                outline: 2px solid #16a085;
            }
            button {
                background: #16a085;
                color: white;
                cursor: pointer;
                font-weight: bold;
                transition: background 0.2s;
            }
            button:hover {
                background: #138871;
            }
            button:disabled {
                background: #555555;
                cursor: not-allowed;
            }
            #status {
                margin-top: 15px;
                color: #aaa;
                font-size: 14px;
            }
        </style>
    </head>
    <body>
        <h1>YouTube Playlist MP3 Downloader</h1>
        <p>Convert YouTube Playlist or Video to MP3 ZIP</p>

        <form id="downloadForm" action="/download" method="post" onsubmit="handleSubmit()">
            <input
                type="text"
                name="url"
                id="urlInput"
                placeholder="Paste YouTube playlist or video URL"
                required
            >
            <br>
            <button type="submit" id="submitBtn">Download Playlist ZIP</button>
            <div id="status"></div>
        </form>

        <script>
            function handleSubmit() {
                const btn = document.getElementById("submitBtn");
                const status = document.getElementById("status");
                btn.disabled = true;
                btn.innerText = "Downloading & Converting...";
                status.innerText = "Processing audio stream(s). Your ZIP download will begin automatically when ready...";
            }
        </script>
    </body>
    </html>
    """


# Validate and normalize YouTube URL
def normalize_youtube_url(url: str):
    if not url:
        return None

    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        parsed = urlparse(url)
    except Exception:
        return None

    host = (parsed.hostname or "").lower()
    allowed = {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtu.be",
    }

    if host in allowed:
        return url
    return None


# Download and convert playlist
@app.post("/download")
def download_playlist(url: str = Form(...)):
    clean_url = normalize_youtube_url(url)
    if not clean_url:
        raise HTTPException(
            status_code=400,
            detail="Only YouTube URLs are supported."
        )

    workdir = tempfile.mkdtemp(prefix="mp3cloud_")
    audio_dir = os.path.join(workdir, "audio")
    os.makedirs(audio_dir, exist_ok=True)

    zip_path = os.path.join(workdir, "playlist.zip")

    options = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(
            audio_dir, "%(playlist_index&{:03d} - |)s%(title).150B.%(ext)s"
        ),
        "ignoreerrors": True,
        "noplaylist": False,
        "max_downloads": 100,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "quiet": True,
        "no_warnings": True,
    }

    ffmpeg_dir = get_ffmpeg_dir()
    if ffmpeg_dir:
        options["ffmpeg_location"] = ffmpeg_dir

    try:
        # Download and convert
        with yt_dlp.YoutubeDL(options) as ydl:
            try:
                ydl.download([clean_url])
            except yt_dlp.utils.MaxDownloadsReached:
                pass

        # Create ZIP archive
        files = sorted(os.listdir(audio_dir))

        if not files:
            raise RuntimeError("No audio files were produced. The video(s) may be private, age-restricted, or unavailable.")

        with zipfile.ZipFile(
            zip_path, "w", zipfile.ZIP_DEFLATED
        ) as archive:
            for filename in files:
                filepath = os.path.join(audio_dir, filename)
                if os.path.isfile(filepath):
                    archive.write(filepath, arcname=filename)

        # Send ZIP to browser
        return FileResponse(
            zip_path,
            media_type="application/zip",
            filename="playlist_mp3.zip",
            background=BackgroundTask(
                shutil.rmtree, workdir, ignore_errors=True
            )
        )

    except Exception as error:
        shutil.rmtree(workdir, ignore_errors=True)

        raise HTTPException(
            status_code=500,
            detail=f"Processing failed: {str(error)}"
        )


# Start server
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
