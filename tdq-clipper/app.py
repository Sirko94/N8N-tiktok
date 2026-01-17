from flask import Flask, request, jsonify
import subprocess, os, uuid, glob, shutil, time, re

app = Flask(__name__)

RAW_DIR = "/data/raw"
SUB_DIR = "/data/subs"
FINAL_DIR = "/data/final"
N8N_FINAL_DIR = "/n8n-files/final"
LOCK_DIR = "/data/locks"

os.makedirs(RAW_DIR, exist_ok=True)
os.makedirs(SUB_DIR, exist_ok=True)
os.makedirs(FINAL_DIR, exist_ok=True)
os.makedirs(N8N_FINAL_DIR, exist_ok=True)
os.makedirs(LOCK_DIR, exist_ok=True)

# ---- Subtitle styling defaults (9:16 1080x1920)
FONT_NAME = "DejaVu Sans"
FONT_SIZE = 30          # <- réduit ici (avant tu étais énorme)
MARGIN_V = 150          # distance du bas (en px virtuels 1080x1920)
OUTLINE = 3.0
SHADOW = 0.6

# Couleur ASS en BGR &HAABBGGRR
# Violet: 8A2BE2 -> BGR = E22B8A
# BackColour alpha: 55 (~33% opaque) -> &H55E22B8A
BACK_ALPHA = "55"
BACK_VIOLET_BGR = "E22B8A"
BACK_COLOUR = f"&H{BACK_ALPHA}{BACK_VIOLET_BGR}"

PRIMARY_COLOUR = "&H00FFFFFF"  # blanc
OUTLINE_COLOUR = "&H80000000"  # noir semi

TS_RE = re.compile(r"(\d{2}):(\d{2}):(\d{2})\.(\d{3})")
INLINE_TS_RE = re.compile(r"<(\d{2}:\d{2}:\d{2}\.\d{3})>")
TAG_RE = re.compile(r"</?c[^>]*>")

def run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return p.returncode, p.stdout, p.stderr

def is_429(stderr: str) -> bool:
    if not stderr:
        return False
    s = stderr.lower()
    return ("http error 429" in s) or ("too many requests" in s) or (" 429" in s)
    main
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("utf-8"))
            os.close(fd)
            return lock_path
        except FileExistsError:
            if time.time() - start > timeout_sec:
    main
            time.sleep(0.4)

def release_lock(lock_path: str):
    try:
        os.remove(lock_path)
    except:
        pass

def hmsms_to_ms(h, m, s, ms):
    return (((int(h) * 60 + int(m)) * 60) + int(s)) * 1000 + int(ms)

def parse_hmsms(s: str) -> int:
    m = TS_RE.match(str(s).strip())
    if not m:
        raise ValueError(f"invalid time format: {s}")
    return hmsms_to_ms(*m.groups())

def ms_to_hmsms(ms: int) -> str:
    ms = max(0, int(ms))
    total = ms // 1000
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    r = ms % 1000
    return f"{h:02d}:{m:02d}:{s:02d}.{r:03d}"

def yt_dlp_subs(video_id: str, lang: str, tries: int = 4):
    url = f"https://www.youtube.com/watch?v={video_id}"
    out_tpl = f"{SUB_DIR}/{video_id}.%(ext)s"

    for f in glob.glob(f"{SUB_DIR}/{video_id}*.{lang}.vtt"):
        try: os.remove(f)
        except: pass

    cmd = [
        "yt-dlp",
        "--skip-download",
        "--write-subs",
        "--write-auto-subs",
        "--sub-format", "vtt",
        "--sub-langs", lang,
        "--output", out_tpl,
        url
    ]

    backoff = [5, 15, 45, 90]
    last_out, last_err = "", ""

    for attempt in range(tries):
        code, outlog, err = run(cmd)
        last_out, last_err = outlog, err

        if code == 0:
            matches = sorted(glob.glob(f"{SUB_DIR}/{video_id}*.{lang}.vtt"))
            if matches:
                return True, outlog, err, matches[0]
            return False, outlog, err, None

        if is_429(err) and attempt < tries - 1:
            time.sleep(backoff[min(attempt, len(backoff)-1)])
            continue

        return False, outlog, err, None

    return False, last_out, last_err, None

def ensure_raw_mp4(video_id: str):
    raw_mp4 = os.path.join(RAW_DIR, f"{video_id}.mp4")
    if os.path.exists(raw_mp4) and os.path.getsize(raw_mp4) > 1024 * 1024:
        return raw_mp4, None, None

    lock = acquire_lock(f"dl-{video_id}")
    try:
        if os.path.exists(raw_mp4) and os.path.getsize(raw_mp4) > 1024 * 1024:
            return raw_mp4, None, None

        url = f"https://www.youtube.com/watch?v={video_id}"
        out_tpl = os.path.join(RAW_DIR, f"{video_id}.%(ext)s")

        cmd = [
            "yt-dlp",
            "--force-overwrites",
            "--no-part",
            "--retries", "10",
            "--fragment-retries", "10",
            "--concurrent-fragments", "1",
            "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--merge-output-format", "mp4",
            "-o", out_tpl,
            url
        ]
        code, outlog, err = run(cmd)
        if code != 0:
            return None, outlog, err

        candidates = sorted(glob.glob(os.path.join(RAW_DIR, f"{video_id}*.mp4")))
        if not candidates:
            return None, outlog, err

        candidates.sort(key=lambda p: os.path.getsize(p))
        src = candidates[-1]

        if src != raw_mp4:
            try:
                shutil.move(src, raw_mp4)
            except:
                shutil.copyfile(src, raw_mp4)

        if not os.path.exists(raw_mp4) or os.path.getsize(raw_mp4) < 1024 * 1024:
            return None, outlog, err

        return raw_mp4, outlog, err
    finally:
        release_lock(lock)

def trim_and_retime_vtt_keep_inline(vtt_path: str, start_ms: int, end_ms: int, out_path: str) -> bool:
    if not os.path.exists(vtt_path):
        return False

    lines = open(vtt_path, "r", encoding="utf-8", errors="ignore").read().splitlines()
    out = ["WEBVTT", "Kind: captions", "Language: fr", ""]
    wrote = 0
    i = 0

    while i < len(lines):
        line = lines[i].strip()
        if "-->" in line:
            parts = [p.strip() for p in line.split("-->")]
            if len(parts) >= 2:
                s0 = parts[0]
                e0 = parts[1].split()[0]
                m1 = TS_RE.match(s0)
                m2 = TS_RE.match(e0)
                if m1 and m2:
                    cue_s = hmsms_to_ms(*m1.groups())
                    cue_e = hmsms_to_ms(*m2.groups())
                    if cue_e > start_ms and cue_s < end_ms:
                        new_s = max(cue_s, start_ms) - start_ms
                        new_e = min(cue_e, end_ms) - start_ms
                        out.append(f"{ms_to_hmsms(new_s)} --> {ms_to_hmsms(new_e)}")

                        i += 1
                        text_lines = []
                        while i < len(lines) and lines[i].strip() != "":
                            text_lines.append(lines[i])
                            i += 1
                        cue_text = "\n".join(text_lines).strip()

                        def shift_inline(m):
                            t = parse_hmsms(m.group(1))
                            if t < start_ms: t = start_ms
                            if t > end_ms: t = end_ms
                            return f"<{ms_to_hmsms(t - start_ms)}>"

                        cue_text = INLINE_TS_RE.sub(shift_inline, cue_text)
                        out.append(cue_text.strip())
                        out.append("")
                        wrote += 1
        i += 1

    if wrote == 0:
        return False

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(out).strip() + "\n")
    return True

def ass_time(ms: int) -> str:
    cs = max(0, int(round(ms / 10)))
    s = cs // 100
    c = cs % 100
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    return f"{h}:{m:02d}:{sec:02d}.{c:02d}"

def escape_ass(t: str) -> str:
    t = t.replace("{", "\\{").replace("}", "\\}")
    t = t.replace("\n", "\\N")
    return t

def vtt_cues_with_inline(trimmed_vtt: str):
    lines = open(trimmed_vtt, "r", encoding="utf-8", errors="ignore").read().splitlines()
    cues = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if "-->" in line:
            parts = [p.strip() for p in line.split("-->")]
            if len(parts) >= 2:
                s0 = parts[0]
                e0 = parts[1].split()[0]
                if TS_RE.match(s0) and TS_RE.match(e0):
                    s_ms = parse_hmsms(s0)
                    e_ms = parse_hmsms(e0)
                    i += 1
                    text_lines = []
                    while i < len(lines) and lines[i].strip() != "":
                        text_lines.append(lines[i])
                        i += 1
                    txt = "\n".join(text_lines).strip()
                    if txt:
                        cues.append((s_ms, e_ms, txt))
        i += 1
    return cues

def build_karaoke_from_inline_text(cue_text: str, cue_start_ms: int, cue_end_ms: int):
    cue_text = cue_text.strip()
    parts = re.split(r"(<\d{2}:\d{2}:\d{2}\.\d{3}>)", cue_text)

    current_ts = cue_start_ms
    segments = []

    def clean_text(t):
        t = TAG_RE.sub("", t)
        t = re.sub(r"<[^>]+>", "", t)
        t = re.sub(r"\s+", " ", t)
        return t.strip()

    for p in parts:
        if not p:
            continue
        if p.startswith("<") and p.endswith(">") and len(p) == 15:
            t_ms = parse_hmsms(p[1:-1])
            current_ts = max(cue_start_ms, min(t_ms, cue_end_ms))
        else:
            txt = clean_text(p)
            if txt:
                segments.append((current_ts, txt))

    words = []
    for ts, chunk in segments:
        for w in chunk.split(" "):
            if w.strip():
                words.append((ts, w.strip()))

    if not words:
        return None

    out = []
    for idx, (w_s, w_txt) in enumerate(words):
        w_e = cue_end_ms if idx == len(words) - 1 else words[idx + 1][0]
        if w_e < w_s:
            w_e = w_s + 120
        out.append((w_s, w_e, w_txt))
    return out

def make_ass_from_trimmed_vtt_inline(trimmed_vtt: str, out_ass: str):
    cues = vtt_cues_with_inline(trimmed_vtt)
    if not cues:
        return False

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{FONT_NAME},{FONT_SIZE},{PRIMARY_COLOUR},{PRIMARY_COLOUR},{OUTLINE_COLOUR},{BACK_COLOUR},1,0,0,0,100,100,0,0,3,{OUTLINE},{SHADOW},2,70,70,{MARGIN_V},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]

    for cue_s, cue_e, cue_txt in cues:
        words = build_karaoke_from_inline_text(cue_txt, cue_s, cue_e)
        if not words:
            continue

        karaoke = []
        for w_s, w_e, w_txt in words:
            k = max(1, int(round((w_e - w_s) / 10)))  # centiseconds
            karaoke.append(f"{{\\k{k}}}{escape_ass(w_txt)}")

        ass_text = " ".join(karaoke)
        lines.append(f"Dialogue: 0,{ass_time(cue_s)},{ass_time(cue_e)},Default,,0,0,0,,{ass_text}")

    with open(out_ass, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return True

@app.post("/transcript")
def transcript():
    data = request.get_json(force=True)
    video_id = data["videoId"]

    ok_fr, out_fr, err_fr, vtt_fr = yt_dlp_subs(video_id, "fr", tries=4)
    if ok_fr and vtt_fr:
        vtt = open(vtt_fr, "r", encoding="utf-8", errors="ignore").read()
        return jsonify({"ok": True, "videoId": video_id, "lang": "fr", "vttPath": vtt_fr, "vtt": vtt})

    ok_en, out_en, err_en, vtt_en = yt_dlp_subs(video_id, "en", tries=4)
    if ok_en and vtt_en:
        vtt = open(vtt_en, "r", encoding="utf-8", errors="ignore").read()
        return jsonify({"ok": True, "videoId": video_id, "lang": "en", "vttPath": vtt_en, "vtt": vtt})

    return jsonify({
        "ok": False,
        "step": "yt-dlp-subs",
        "error": "no vtt generated (rate-limit / subtitles disabled / blocked)",
        "stdout_fr": out_fr, "stderr_fr": err_fr,
        "stdout_en": out_en, "stderr_en": err_en
    }), 500

@app.post("/clip")
def clip():
    data = request.get_json(force=True)
    video_id = data["videoId"]
    start = data.get("start", "00:00:30.000")
    dur = float(data.get("duration", 90))
    vtt_path = data.get("vttPath")
    burn = bool(data.get("burnSubtitles", True))

    raw, yout, yerr = ensure_raw_mp4(video_id)
    if not raw:
        return jsonify({"ok": False, "step": "yt-dlp", "error": "download did not create raw mp4", "stdout": yout or "", "stderr": yerr or ""}), 500

    out_name = f"{video_id}_{uuid.uuid4().hex}_9x16.mp4"
    out = f"{FINAL_DIR}/{out_name}"
    n8n_out = f"{N8N_FINAL_DIR}/{out_name}"

    vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"

    subs_tmp_vtt = None
    subs_tmp_ass = None

    if burn and vtt_path and os.path.exists(vtt_path):
        start_ms = parse_hmsms(start)
        end_ms = start_ms + int(dur * 1000)

        subs_tmp_vtt = os.path.join(SUB_DIR, f"trim_{video_id}_{uuid.uuid4().hex}.vtt")
        ok = trim_and_retime_vtt_keep_inline(vtt_path, start_ms, end_ms, subs_tmp_vtt)

        if ok:
            subs_tmp_ass = os.path.join(SUB_DIR, f"kara_{video_id}_{uuid.uuid4().hex}.ass")
            ok_ass = make_ass_from_trimmed_vtt_inline(subs_tmp_vtt, subs_tmp_ass)
            if ok_ass and os.path.exists(subs_tmp_ass):
                safe_ass = subs_tmp_ass.replace("\\", "\\\\").replace("'", "\\'")
                vf = vf + f",subtitles='{safe_ass}'"

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", raw,
        "-t", str(dur),
        "-vf", vf,
        "-map", "0:v:0?",
        "-map", "0:a:0?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        out
    ]
    code, ffout, fferr = run(cmd)

    for p in [subs_tmp_ass, subs_tmp_vtt]:
        if p:
            try: os.remove(p)
            except: pass

    if code != 0:
        return jsonify({"ok": False, "step": "ffmpeg", "stdout": ffout, "stderr": fferr, "vf": vf}), 500

    shutil.copyfile(out, n8n_out)

    return jsonify({
        "ok": True,
        "videoId": video_id,
        "raw": raw,
        "path": out,
        "n8nPath": f"/home/node/.n8n-files/final/{out_name}",
        "subsBurned": bool(subs_tmp_ass is not None),
        "vttPath": vtt_path if vtt_path else None
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8580)
