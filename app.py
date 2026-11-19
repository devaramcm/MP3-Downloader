import os
import tempfile
import zipfile
import re
import shutil
import threading
from uuid import uuid4
from urllib.parse import urlparse

import yt_dlp
from fastapi import FastAPI, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from starlette.background import BackgroundTask


app = FastAPI(title="YouTube MP3 Cloud")

MAX_TRACKS = 100

jobs = {}
jobs_lock = threading.Lock()


def update_job(job_id, **kwargs):
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id].update(kwargs)


def set_track(job_id, index, state):
    """Set one track's state and recompute the downloaded count."""
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return

        tracks = job["tracks"]

        if not 1 <= index <= len(tracks):
            return

        track = tracks[index - 1]

        # Never move a finished track backwards.
        if track["state"] == "done":
            return

        track["state"] = state
        job["downloaded"] = sum(1 for t in tracks if t["state"] == "done")


def clean_zip_name(name):
    """Turn user input into a safe ZIP file name (without extension)."""
    name = (name or "").strip()

    if name.lower().endswith(".zip"):
        name = name[:-4]

    # Drop characters that are invalid in file names on common systems.
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", name)
    name = re.sub(r"\s+", " ", name).strip(" .")

    return name[:100] or "playlist_mp3_320kbps"


def validate_url(url):
    host = (urlparse(url).hostname or "").lower()

    allowed = {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtu.be",
    }

    return host in allowed


@app.get("/", response_class=HTMLResponse)
def home():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <title>MP3 Cloud</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">

        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link
            href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700;800&display=swap"
            rel="stylesheet"
        >

        <style>
            :root {
                --bg: #0E0E10;
                --surface: #17171B;
                --surface-2: #202027;
                --text: #F2F2F5;
                --muted: #9A9AA8;
                --line: #2A2A33;
                --accent: #8B7CFF;
                --accent-hover: #A093FF;
                --pink: #FF6FA5;
                --error: #FF7A7A;
            }

            * { box-sizing: border-box; }

            body {
                margin: 0;
                min-height: 100vh;
                background:
                    radial-gradient(900px 420px at 15% -10%, rgba(139,124,255,0.22), transparent 70%),
                    var(--bg);
                color: var(--text);
                font-family: "Outfit", system-ui, -apple-system, "Segoe UI", sans-serif;
                line-height: 1.5;
            }

            [hidden] { display: none !important; }

            :focus-visible {
                outline: 2px solid var(--accent-hover);
                outline-offset: 2px;
            }

            .wrap {
                max-width: 900px;
                margin: 0 auto;
                padding: 28px 20px 150px;
            }

            .brand {
                font-weight: 800;
                font-size: 1.25rem;
            }

            .brand span { color: var(--accent); }

            h1 {
                margin: 48px 0 8px;
                font-size: clamp(2rem, 6vw, 3.2rem);
                font-weight: 800;
                line-height: 1.1;
            }

            .lede {
                margin: 0 0 24px;
                color: var(--muted);
                font-size: 1.05rem;
            }

            form {
                display: flex;
                gap: 10px;
            }

            input[type="url"] {
                flex: 1;
                min-width: 0;
                padding: 14px 20px;
                font: inherit;
                color: var(--text);
                background: var(--surface-2);
                border: 1px solid var(--line);
                border-radius: 999px;
            }

            input[type="url"]::placeholder { color: #6E6E7C; }

            input[type="url"]:focus {
                outline: none;
                border-color: var(--accent);
            }

            .button {
                display: inline-block;
                padding: 14px 28px;
                font: inherit;
                font-weight: 700;
                color: #0E0E10;
                background: var(--accent);
                border: none;
                border-radius: 999px;
                cursor: pointer;
                text-decoration: none;
                white-space: nowrap;
                transition: background-color 0.15s ease, transform 0.15s ease;
            }

            .button:hover { background: var(--accent-hover); }
            .button:active { transform: scale(0.97); }

            .button:disabled {
                opacity: 0.5;
                cursor: not-allowed;
                transform: none;
            }

            #error {
                margin-top: 14px;
                color: var(--error);
                font-weight: 500;
            }

            /* Playlist header */
            .hero {
                display: flex;
                align-items: flex-end;
                gap: 24px;
                margin-top: 44px;
            }

            .cover {
                flex: none;
                width: 150px;
                height: 150px;
                display: grid;
                place-items: center;
                border-radius: 10px;
                background: linear-gradient(135deg, var(--accent), var(--pink));
                box-shadow: 0 18px 40px rgba(0,0,0,0.5);
            }

            .cover svg {
                width: 64px;
                height: 64px;
                fill: rgba(255,255,255,0.92);
            }

            .hero-text { min-width: 0; }

            #playlist-title {
                margin: 0;
                font-size: clamp(1.6rem, 5vw, 2.8rem);
                font-weight: 800;
                line-height: 1.1;
                overflow-wrap: anywhere;
            }

            .chips {
                display: flex;
                flex-wrap: wrap;
                gap: 10px;
                margin-top: 14px;
            }

            .chip {
                padding: 6px 14px;
                background: var(--surface-2);
                border-radius: 999px;
                color: var(--muted);
                font-size: 0.95rem;
            }

            .chip b {
                color: var(--text);
                font-weight: 700;
                font-variant-numeric: tabular-nums;
            }

            .chip.live b { color: var(--accent-hover); }

            #finish { margin-top: 24px; }

            #finish .button {
                padding: 16px 36px;
                font-size: 1.05rem;
            }

            .name-field {
                display: flex;
                align-items: center;
                max-width: 460px;
                margin-bottom: 14px;
                background: var(--surface-2);
                border: 1px solid var(--line);
                border-radius: 999px;
                padding-right: 18px;
            }

            .name-field:focus-within { border-color: var(--accent); }

            .name-field input {
                flex: 1;
                min-width: 0;
                padding: 12px 6px 12px 20px;
                font: inherit;
                color: var(--text);
                background: transparent;
                border: none;
            }

            .name-field input:focus { outline: none; }

            .name-field span { color: var(--muted); }

            .name-label {
                display: block;
                margin-bottom: 8px;
                color: var(--muted);
                font-size: 0.95rem;
            }

            #finish p {
                margin: 10px 0 0;
                color: var(--muted);
                font-size: 0.9rem;
            }

            /* Track list */
            .list-head,
            #tracklist li {
                display: grid;
                grid-template-columns: 40px 1fr 110px;
                gap: 12px;
                align-items: center;
                padding: 10px 14px;
            }

            .list-head {
                margin-top: 32px;
                color: var(--muted);
                font-size: 0.9rem;
                border-bottom: 1px solid var(--line);
            }

            .list-head div:last-child,
            #tracklist .state { text-align: right; }

            #tracklist {
                list-style: none;
                margin: 8px 0 0;
                padding: 0;
            }

            #tracklist li {
                border-radius: 8px;
                font-size: 1rem;
            }

            #tracklist .num {
                position: relative;
                text-align: center;
                color: var(--muted);
                font-variant-numeric: tabular-nums;
            }

            #tracklist .name {
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }

            #tracklist .state {
                color: var(--muted);
                font-size: 0.9rem;
            }

            #tracklist li[data-state="active"],
            #tracklist li[data-state="converting"] {
                background: var(--surface);
            }

            #tracklist li[data-state="active"] .name,
            #tracklist li[data-state="converting"] .name,
            #tracklist li[data-state="active"] .state,
            #tracklist li[data-state="converting"] .state {
                color: var(--accent-hover);
                font-weight: 600;
            }

            #tracklist li[data-state="done"] .name { color: var(--text); }
            #tracklist li[data-state="done"] .state { color: var(--accent-hover); }
            #tracklist li[data-state="pending"] .name { color: var(--muted); }

            /* Equalizer bars replace the number on the live row */
            .eq {
                display: none;
                align-items: flex-end;
                justify-content: center;
                gap: 2px;
                height: 16px;
            }

            .eq i {
                display: block;
                width: 3px;
                height: 100%;
                background: var(--accent-hover);
                transform-origin: bottom;
                animation: eq 0.9s ease-in-out infinite;
            }

            .eq i:nth-child(2) { animation-delay: 0.2s; }
            .eq i:nth-child(3) { animation-delay: 0.4s; }

            @keyframes eq {
                0%, 100% { transform: scaleY(0.3); }
                50% { transform: scaleY(1); }
            }

            li[data-state="active"] .eq,
            li[data-state="converting"] .eq { display: flex; }

            li[data-state="active"] .idx,
            li[data-state="converting"] .idx { display: none; }

            /* Player bar */
            #player {
                position: fixed;
                left: 0;
                right: 0;
                bottom: 0;
                padding: 14px 20px 18px;
                background: rgba(23,23,27,0.94);
                backdrop-filter: blur(12px);
                border-top: 1px solid var(--line);
            }

            .player-inner {
                max-width: 900px;
                margin: 0 auto;
            }

            .player-top {
                display: flex;
                justify-content: space-between;
                gap: 16px;
                align-items: baseline;
            }

            #current {
                min-width: 0;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
                font-weight: 600;
            }

            #status {
                flex: none;
                color: var(--muted);
                font-size: 0.9rem;
            }

            .bar-row {
                display: flex;
                align-items: center;
                gap: 12px;
                margin-top: 10px;
            }

            .bar {
                flex: 1;
                height: 5px;
                background: var(--line);
                border-radius: 5px;
                overflow: hidden;
            }

            #bar-fill {
                height: 100%;
                width: 0%;
                background: linear-gradient(90deg, var(--accent), var(--pink));
                border-radius: 5px;
                transition: width 0.3s ease;
            }

            #percent {
                min-width: 3.5ch;
                text-align: right;
                font-size: 0.9rem;
                font-weight: 600;
                font-variant-numeric: tabular-nums;
            }

            @media (max-width: 600px) {
                form { flex-direction: column; }
                .hero { flex-direction: column; align-items: flex-start; }
                .cover { width: 110px; height: 110px; }
                .list-head,
                #tracklist li { grid-template-columns: 30px 1fr 84px; padding: 10px 8px; }
                .player-top { flex-direction: column; gap: 2px; }
            }

            @media (prefers-reduced-motion: reduce) {
                .eq i { animation: none; transform: scaleY(0.7); }
                #bar-fill { transition: none; }
            }
        </style>
    </head>

    <body>
        <main class="wrap">

            <div class="brand">MP3<span>Cloud</span></div>

            <h1>Turn any YouTube playlist into MP3s.</h1>

            <p class="lede">
                320 kbps files with cover art and tags, delivered as one ZIP.
            </p>

            <form id="download-form">
                <input
                    type="url"
                    name="url"
                    placeholder="Paste a YouTube playlist link"
                    aria-label="YouTube playlist link"
                    required
                >
                <button class="button" id="submit-button" type="submit">
                    Download playlist
                </button>
            </form>

            <div id="error" role="alert"></div>

            <section id="panel" hidden>

                <div class="hero">
                    <div class="cover" aria-hidden="true">
                        <svg viewBox="0 0 24 24"><path d="M12 3v10.55A4 4 0 1 0 14 17V7h4V3h-6z"/></svg>
                    </div>

                    <div class="hero-text">
                        <h2 id="playlist-title">Playlist</h2>

                        <div class="chips">
                            <div class="chip"><b id="total">0</b> songs in playlist</div>
                            <div class="chip live"><b id="downloaded">0</b> songs downloaded</div>
                        </div>
                    </div>
                </div>

                <div id="finish" hidden>
                    <label class="name-label" for="zip-name">Name your ZIP</label>
                    <div class="name-field">
                        <input
                            type="text"
                            id="zip-name"
                            maxlength="100"
                            autocomplete="off"
                            placeholder="My playlist"
                        >
                        <span>.zip</span>
                    </div>
                    <a class="button" id="download-link" href="#">Save playlist ZIP</a>
                    <p>The ZIP is removed from the server after you save it.</p>
                </div>

                <div class="list-head">
                    <div>#</div>
                    <div>Title</div>
                    <div>Status</div>
                </div>

                <ol id="tracklist"></ol>

            </section>

        </main>

        <div id="player" hidden aria-live="polite">
            <div class="player-inner">
                <div class="player-top">
                    <div id="current">Preparing playlist...</div>
                    <div id="status"></div>
                </div>
                <div class="bar-row">
                    <div class="bar"><div id="bar-fill"></div></div>
                    <div id="percent">0%</div>
                </div>
            </div>
        </div>

        <script>
            const $ = (id) => document.getElementById(id);

            const form = $("download-form");
            const button = $("submit-button");
            const panel = $("panel");
            const player = $("player");
            const errorText = $("error");
            const list = $("tracklist");

            const STATE_LABELS = {
                pending: "Waiting",
                active: "Downloading",
                converting: "Converting",
                done: "Done"
            };

            let polling = false;
            let lastActive = -1;
            let resultUrl = "";

            function updateLink() {
                const name = $("zip-name").value.trim();

                $("download-link").href = name
                    ? resultUrl + "?name=" + encodeURIComponent(name)
                    : resultUrl;
            }

            $("zip-name").addEventListener("input", updateLink);

            $("zip-name").addEventListener("keydown", (event) => {
                if (event.key === "Enter") {
                    event.preventDefault();
                    $("download-link").click();
                }
            });

            function resetPanel() {
                panel.hidden = false;
                player.hidden = false;
                $("finish").hidden = true;
                $("zip-name").value = "";
                $("playlist-title").textContent = "Reading playlist";
                $("current").textContent = "Preparing playlist...";
                $("status").textContent = "";
                $("downloaded").textContent = "0";
                $("total").textContent = "0";
                $("bar-fill").style.width = "0%";
                $("percent").textContent = "0%";
                list.replaceChildren();
                lastActive = -1;
            }

            function buildTracks(tracks) {
                list.replaceChildren();

                tracks.forEach((track, i) => {
                    const li = document.createElement("li");

                    const num = document.createElement("span");
                    num.className = "num";

                    const idx = document.createElement("span");
                    idx.className = "idx";
                    idx.textContent = i + 1;

                    const eq = document.createElement("span");
                    eq.className = "eq";
                    eq.innerHTML = "<i></i><i></i><i></i>";

                    num.append(idx, eq);

                    const name = document.createElement("span");
                    name.className = "name";
                    name.textContent = track.title;
                    name.title = track.title;

                    const state = document.createElement("span");
                    state.className = "state";

                    li.append(num, name, state);
                    list.appendChild(li);
                });
            }

            function renderTracks(tracks) {
                if (!tracks || !tracks.length) return;

                if (list.children.length !== tracks.length) {
                    buildTracks(tracks);
                }

                let active = -1;

                tracks.forEach((track, i) => {
                    const li = list.children[i];

                    if (li.dataset.state !== track.state) {
                        li.dataset.state = track.state;
                        li.querySelector(".state").textContent =
                            STATE_LABELS[track.state] || "";
                    }

                    if (track.state === "active" || track.state === "converting") {
                        active = i;
                    }
                });

                if (active !== -1 && active !== lastActive) {
                    lastActive = active;
                    list.children[active].scrollIntoView({
                        block: "center",
                        behavior: "smooth"
                    });
                }
            }

            form.addEventListener("submit", async (event) => {
                event.preventDefault();

                if (polling) return;

                polling = true;
                button.disabled = true;
                button.textContent = "Starting...";
                errorText.textContent = "";

                resetPanel();

                try {
                    const response = await fetch("/download", {
                        method: "POST",
                        body: new FormData(form)
                    });

                    const data = await response.json();

                    if (!response.ok) {
                        throw new Error(data.detail || "Could not start the download.");
                    }

                    button.textContent = "Downloading...";
                    pollProgress(data.job_id);

                } catch (error) {
                    showError(error.message);
                }
            });

            async function pollProgress(jobId) {
                try {
                    const response = await fetch("/status/" + jobId);

                    if (!response.ok) {
                        throw new Error("Could not read download progress.");
                    }

                    const data = await response.json();

                    const progress = Math.min(
                        100,
                        Math.max(0, Number(data.progress) || 0)
                    );

                    if (data.playlist_title) {
                        $("playlist-title").textContent = data.playlist_title;
                    }

                    $("downloaded").textContent = data.downloaded;
                    $("total").textContent = data.total;
                    $("current").textContent = data.track || data.message || data.status;
                    $("status").textContent = data.message || "";
                    $("bar-fill").style.width = progress + "%";
                    $("percent").textContent = Math.round(progress) + "%";

                    renderTracks(data.tracks);

                    if (data.status === "completed") {
                        $("current").textContent = "Your playlist is ready";
                        $("finish").hidden = false;
                        resultUrl = data.download_url;

                        if (!$("zip-name").value) {
                            $("zip-name").value = data.playlist_title || "";
                        }

                        updateLink();
                        $("zip-name").focus();
                        $("zip-name").select();

                        button.disabled = false;
                        button.textContent = "Download another playlist";
                        polling = false;
                        return;
                    }

                    if (data.status === "error") {
                        throw new Error(data.message);
                    }

                    setTimeout(() => pollProgress(jobId), 800);

                } catch (error) {
                    showError(error.message);
                }
            }

            function showError(message) {
                errorText.textContent = message;
                button.disabled = false;
                button.textContent = "Try again";
                polling = false;
            }
        </script>

    </body>
    </html>
    """


def process_playlist(job_id, url):

    workdir = tempfile.mkdtemp(prefix="mp3cloud_")
    audio_dir = os.path.join(workdir, "audio")
    os.makedirs(audio_dir)

    zip_path = os.path.join(workdir, "playlist.zip")

    update_job(
        job_id,
        workdir=workdir,
        status="preparing",
        message="Checking playlist...",
        progress=0,
    )

    try:

        # Read the playlist's track list before downloading (fast, no media).
        probe_options = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
        }

        with yt_dlp.YoutubeDL(probe_options) as ydl:
            info = ydl.extract_info(url, download=False)

        entries = [e for e in (info.get("entries") or []) if e] if info else []

        if entries:
            titles = [e.get("title") or "Untitled" for e in entries]
        else:
            titles = [(info or {}).get("title") or "Untitled"]

        titles = titles[:MAX_TRACKS]
        total_tracks = len(titles)

        playlist_title = (info or {}).get("title") or "Playlist"

        update_job(
            job_id,
            playlist_title=playlist_title,
            total=total_tracks,
            downloaded=0,
            tracks=[{"title": t, "state": "pending"} for t in titles],
            status="downloading",
            message=f"Found {total_tracks} songs. Starting download...",
        )

        # Live download progress hook.
        def progress_hook(data):

            info_dict = data.get("info_dict") or {}

            index = info_dict.get("playlist_index") or 1
            title = info_dict.get("title") or "Downloading audio"

            if data["status"] == "downloading":

                set_track(job_id, index, "active")

                downloaded = data.get("downloaded_bytes", 0)

                total = (
                    data.get("total_bytes")
                    or data.get("total_bytes_estimate")
                    or 0
                )

                if total:
                    track_progress = downloaded / total
                else:
                    track_progress = 0

                overall = (
                    ((index - 1) + track_progress)
                    / max(total_tracks, 1)
                ) * 95

                update_job(
                    job_id,
                    status="downloading",
                    progress=round(min(overall, 95), 1),
                    message=f"Downloading song {index} of {total_tracks}",
                    track=title,
                )

            elif data["status"] == "finished":

                set_track(job_id, index, "converting")

                overall = (index / max(total_tracks, 1)) * 95

                update_job(
                    job_id,
                    progress=round(min(overall, 95), 1),
                    message=f"Converting song {index} of {total_tracks}",
                    track=title,
                )

        # Conversion and artwork hook. EmbedThumbnail is the last step,
        # so when it finishes the song is complete.
        def postprocessor_hook(data):

            info_dict = data.get("info_dict") or {}
            index = info_dict.get("playlist_index") or 1

            if (
                data.get("status") == "finished"
                and data.get("postprocessor") == "EmbedThumbnail"
            ):
                set_track(job_id, index, "done")

            else:
                update_job(
                    job_id,
                    status="processing",
                    message="Converting MP3 and embedding artwork...",
                )

        options = {
            "format": "bestaudio/best",

            "outtmpl": os.path.join(
                audio_dir,
                "%(playlist_index)03d - %(title).150B.%(ext)s"
            ),

            "ignoreerrors": False,
            "noplaylist": False,
            "playlist_items": f"1-{MAX_TRACKS}",

            "writethumbnail": True,
            "convertthumbnails": "jpg",

            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "320",
                },
                {"key": "FFmpegMetadata"},
                {"key": "EmbedThumbnail"},
            ],

            "progress_hooks": [progress_hook],
            "postprocessor_hooks": [postprocessor_hook],

            "quiet": True,
            "no_warnings": True,
        }

        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([url])

        # Every track finished without error, so make sure all show as done.
        with jobs_lock:
            job = jobs.get(job_id)

            if job:
                for track in job["tracks"]:
                    track["state"] = "done"

                job["downloaded"] = len(job["tracks"])

        # Find generated MP3 files.
        mp3_files = sorted(
            filename
            for filename in os.listdir(audio_dir)
            if filename.lower().endswith(".mp3")
            and os.path.isfile(os.path.join(audio_dir, filename))
        )

        if not mp3_files:
            raise RuntimeError("No MP3 files were produced.")

        # Create ZIP archive.
        update_job(
            job_id,
            status="zipping",
            progress=97,
            message="Creating your playlist ZIP...",
            track="",
        )

        with zipfile.ZipFile(
            zip_path,
            "w",
            zipfile.ZIP_DEFLATED
        ) as archive:

            for filename in mp3_files:
                filepath = os.path.join(audio_dir, filename)
                archive.write(filepath, arcname=filename)

        update_job(
            job_id,
            status="completed",
            progress=100,
            message=f"Done. {len(mp3_files)} MP3 files are ready.",
            download_url=f"/result/{job_id}",
        )

    except Exception as error:

        shutil.rmtree(workdir, ignore_errors=True)

        update_job(
            job_id,
            status="error",
            message=str(error),
        )


@app.post("/download")
def download_playlist(url: str = Form(...)):

    if not validate_url(url):
        raise HTTPException(
            status_code=400,
            detail="Only YouTube URLs are supported.",
        )

    job_id = str(uuid4())

    with jobs_lock:
        jobs[job_id] = {
            "status": "queued",
            "progress": 0,
            "message": "Preparing download...",
            "track": "",
            "playlist_title": "",
            "total": 0,
            "downloaded": 0,
            "tracks": [],
        }

    thread = threading.Thread(
        target=process_playlist,
        args=(job_id, url),
        daemon=True,
    )

    thread.start()

    return JSONResponse({"job_id": job_id})


@app.get("/status/{job_id}")
def get_status(job_id: str):

    with jobs_lock:
        job = jobs.get(job_id)

        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        return {
            "status": job["status"],
            "progress": job["progress"],
            "message": job["message"],
            "track": job.get("track", ""),
            "playlist_title": job.get("playlist_title", ""),
            "total": job.get("total", 0),
            "downloaded": job.get("downloaded", 0),
            "tracks": [dict(t) for t in job.get("tracks", [])],
            "download_url": job.get("download_url", ""),
        }


def cleanup_job(job_id, workdir):

    shutil.rmtree(workdir, ignore_errors=True)

    with jobs_lock:
        jobs.pop(job_id, None)


@app.get("/result/{job_id}")
def get_result(job_id: str, name: str = Query(default="")):

    with jobs_lock:
        job = jobs.get(job_id)

        if not job or job["status"] != "completed":
            raise HTTPException(
                status_code=404,
                detail="Download is not ready.",
            )

        zip_path = os.path.join(job["workdir"], "playlist.zip")
        workdir = job["workdir"]

    if not os.path.isfile(zip_path):
        raise HTTPException(status_code=404, detail="ZIP file not found")

    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"{clean_zip_name(name)}.zip",
        background=BackgroundTask(cleanup_job, job_id, workdir),
    )


if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
    )
