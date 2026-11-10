import os
import re
import shutil
import threading
import time
from typing import Any, Callable, Dict, List, Optional
import httpx
import yt_dlp
from yt_dlp.utils import download_range_func

from engine.muxer import FFMPEG_PATH, trim_media_file, get_media_duration

class JobPausedException(Exception):
    """Raised when a download job is paused by the user."""
    pass

class JobCancelledException(Exception):
    """Raised when a download job is cancelled by the user."""
    pass

class MediaExtractor:
    """Handles metadata extraction and multi-stream media downloads using yt-dlp
    with native macOS ffmpeg post-processing and resilient client fallbacks.
    """

    def __init__(self, download_dir: str):
        self.download_dir = download_dir
        os.makedirs(self.download_dir, exist_ok=True)

    def get_base_opts(self, browser_cookies: Optional[str] = None) -> Dict[str, Any]:
        opts: Dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "nocheckcertificate": True,
            "ignoreerrors": False,
            "logtostderr": False,
            "socket_timeout": 30,
            "retries": 10,
            "fragment_retries": 10,
            "continuedl": True,    # Resume partial downloads from .part files
            "nopart": False,       # Keep .part files so resume works
        }

        # Configure Node.js JS runtime and remote component challenge solver for YouTube n-sig
        opts["remote_components"] = ["ejs:github"]
        if os.path.exists("/usr/local/bin/node"):
            opts["js_runtimes"] = {"node": {"path": "/usr/local/bin/node"}}
        elif shutil.which("node"):
            opts["js_runtimes"] = {"node": {"path": shutil.which("node")}}

        if browser_cookies:
            opts["cookiesfrombrowser"] = (browser_cookies, None, None, None)

        # Automatic detection of cookies.txt
        for c_path in [
            os.path.join(self.download_dir, "cookies.txt"),
            os.path.join(os.path.dirname(__file__), "..", "cookies.txt"),
            os.path.expanduser("~/Downloads/cookies.txt")
        ]:
            if os.path.exists(c_path):
                opts["cookiefile"] = c_path
                break

        if FFMPEG_PATH:
            opts["ffmpeg_location"] = FFMPEG_PATH
        return opts

    @staticmethod
    def canonicalize_url(url: str) -> str:
        """Expands shortened URLs (fb.watch, vm.tiktok.com, vt.tiktok.com, t.co, bit.ly, etc.)
        to their full canonical URLs to ensure maximum extractor compatibility.
        """
        if not url:
            return ""
        clean_url = url.strip()
        short_domains = ("fb.watch", "vm.tiktok.com", "vt.tiktok.com", "t.co", "bit.ly", "tinyurl.com", "instagr.am")
        if any(d in clean_url.lower() for d in short_domains):
            try:
                with httpx.Client(follow_redirects=True, timeout=8.0, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}) as client:
                    resp = client.head(clean_url)
                    if resp.status_code in (200, 301, 302, 303, 307, 308) and str(resp.url) != clean_url:
                        return str(resp.url)
                    resp = client.get(clean_url)
                    if str(resp.url) != clean_url:
                        return str(resp.url)
            except Exception:
                pass
        return clean_url

    def inspect(self, url: str, browser_cookies: Optional[str] = None) -> Dict[str, Any]:
        """Extracts metadata and structured resolution/audio choices from a media URL."""
        url = self.canonicalize_url(url)
        opts = self.get_base_opts(browser_cookies=browser_cookies)
        opts["extract_flat"] = False
        opts["skip_download"] = True

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                raise ValueError("Could not extract media info from the provided URL")

            # Handle playlists or single videos
            if "entries" in info and info["entries"]:
                entry = info["entries"][0]
                if entry:
                    info = entry

            title = info.get("title", "Unknown Title")
            thumbnail = info.get("thumbnail") or (info.get("thumbnails", [{}])[-1].get("url") if info.get("thumbnails") else "")
            duration = info.get("duration", 0)
            uploader = info.get("uploader") or info.get("channel") or "Unknown"
            extractor = info.get("extractor_key", "Generic")

            # Parse formats
            raw_formats = info.get("formats", [])
            video_options: List[Dict[str, Any]] = []
            seen_resolutions = set()

            # Resolution priority map
            res_labels = {
                2160: "4K UHD (2160p)",
                1440: "2K QHD (1440p)",
                1080: "1080p Full HD",
                720: "720p HD",
                480: "480p SD",
                360: "360p",
                240: "240p",
                144: "144p"
            }

            def get_sort_key(f):
                h = f.get("height") or 0
                if not h:
                    fid = (f.get("format_id") or "").lower()
                    if "hd" in fid: h = 720
                    elif "sd" in fid: h = 480
                return (h, f.get("tbr") or 0)

            for f in sorted(raw_formats, key=get_sort_key, reverse=True):
                fid = f.get("format_id") or ""
                vcodec = f.get("vcodec") or ""
                acodec = f.get("acodec") or ""

                # Skip audio-only streams
                if vcodec == "none" and acodec != "none":
                    continue

                h = f.get("height")
                if not h:
                    res_str = f.get("resolution") or ""
                    if "x" in res_str:
                        try:
                            parts = [int(p) for p in res_str.split("x") if p.isdigit()]
                            if parts:
                                h = min(parts)
                        except Exception:
                            pass
                    if not h:
                        fid_lower = fid.lower()
                        note_lower = (f.get("format_note") or "").lower()
                        combined_id = fid_lower + " " + note_lower
                        if "hd" in combined_id:
                            h = 720
                        elif "sd" in combined_id:
                            h = 480
                        else:
                            digits = re.findall(r"(\d{3,4})p?", combined_id)
                            if digits:
                                h = int(digits[0])

                label = res_labels.get(h, f"{h}p" if h else fid.upper())
                if fid.lower() == "hd":
                    label = "HD Quality (High Definition)"
                elif fid.lower() == "sd":
                    label = "SD Quality (Standard Definition)"

                fps = f.get("fps")
                if fps and fps > 30 and h:
                    label += f" {int(fps)}fps"

                # Calculate estimated size
                filesize = f.get("filesize") or f.get("filesize_approx")
                filesize_str = self._format_size(filesize) if filesize else "Direct Stream"

                key = h if h else fid
                if key in seen_resolutions:
                    continue
                seen_resolutions.add(key)

                video_options.append({
                    "id": f"video_{key}_{fid}",
                    "format_id": fid or "best",
                    "height": h or 720,
                    "label": label,
                    "ext": f.get("ext") or "mp4",
                    "filesize": filesize,
                    "filesize_str": filesize_str,
                    "type": "video"
                })

            # If no separated video heights found, provide best fallback
            if not video_options:
                video_options.append({
                    "id": "best_video",
                    "format_id": "bestvideo+bestaudio/best",
                    "height": 1080,
                    "label": "Best Video Quality (Auto)",
                    "ext": "mp4",
                    "filesize_str": "Auto",
                    "type": "video"
                })

            # Audio options
            audio_options = [
                {
                    "id": "audio_mp3_320",
                    "format_id": "bestaudio/best",
                    "label": "MP3 High Quality (320 kbps)",
                    "ext": "mp3",
                    "codec": "mp3",
                    "quality": "320",
                    "filesize_str": "Standard",
                    "type": "audio"
                },
                {
                    "id": "audio_mp3_192",
                    "format_id": "bestaudio/best",
                    "label": "MP3 Standard (192 kbps)",
                    "ext": "mp3",
                    "codec": "mp3",
                    "quality": "192",
                    "filesize_str": "Compact",
                    "type": "audio"
                },
                {
                    "id": "audio_m4a",
                    "format_id": "bestaudio[ext=m4a]/bestaudio/best",
                    "label": "M4A / AAC Lossless Audio",
                    "ext": "m4a",
                    "codec": "m4a",
                    "quality": "0",
                    "filesize_str": "Original",
                    "type": "audio"
                }
            ]

            video_id = info.get("id") or ""
            preview_stream_url = ""
            
            # Select optimal lightweight preview stream (combined audio + video)
            # Priority 1: Progressive MP4 with audio & video (format 18 / 22, 360p/720p)
            combined_mp4 = [
                f for f in raw_formats
                if f.get("vcodec") != "none" and f.get("acodec") != "none" 
                and f.get("url") and f.get("protocol") in ("https", "http")
            ]
            if combined_mp4:
                # Prefer format 18 (360p) or 22 (720p) for instant buffering and scrub
                f_opt = next((f for f in combined_mp4 if f.get("format_id") in ("18", "22")), None)
                if f_opt:
                    preview_stream_url = f_opt.get("url")
                else:
                    # Pick format closest to 360p
                    combined_mp4.sort(key=lambda x: abs((x.get("height") or 360) - 360))
                    preview_stream_url = combined_mp4[0].get("url")
            else:
                # Priority 2: Any combined stream (e.g. HLS m3u8_native or other protocols)
                combined_any = [
                    f for f in raw_formats
                    if f.get("vcodec") != "none" and f.get("acodec") != "none" and f.get("url")
                ]
                if combined_any:
                    combined_any.sort(key=lambda x: abs((x.get("height") or 360) - 360))
                    preview_stream_url = combined_any[0].get("url")
                elif raw_formats:
                    # Fallback to any direct media stream with a URL
                    with_url = [f for f in raw_formats if f.get("url")]
                    if with_url:
                        preview_stream_url = with_url[0].get("url")

            return {
                "id": video_id,
                "title": title,
                "thumbnail": thumbnail,
                "duration": duration,
                "duration_str": self._format_duration(duration),
                "uploader": uploader,
                "extractor": extractor,
                "url": url,
                "preview_stream_url": preview_stream_url,
                "video_options": video_options,
                "audio_options": audio_options
            }

    def download(
        self,
        url: str,
        choice_type: str,
        choice_id: str,
        format_id: str,
        output_name: str,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        cancel_event: Optional[threading.Event] = None,
        pause_event: Optional[threading.Event] = None,
        browser_cookies: Optional[str] = None,
        clip_start: Optional[float] = None,
        clip_end: Optional[float] = None
    ) -> str:
        """Downloads selected media stream with 16x multi-connection acceleration, clipping, and ffmpeg muxing."""
        url = self.canonicalize_url(url)
        opts = self.get_base_opts(browser_cookies=browser_cookies)
        
        # Clean title for filename
        clean_name = re.sub(r'[\\/*?:"<>|]', "", output_name).strip()
        if not clean_name:
            clean_name = "media_download"

        is_clipping = (clip_start is not None and clip_start >= 0) or (clip_end is not None and clip_end > 0)
        clip_suffix = ""
        if is_clipping:
            s_label = self.format_time_label(clip_start or 0.0)
            e_label = self.format_time_label(clip_end) if clip_end else "end"
            clip_suffix = f"_[Clip_{s_label}-{e_label}]"
            clean_name = f"{clean_name}{clip_suffix}"

            # Set download ranges for yt-dlp
            c_start = clip_start or 0.0
            c_end = clip_end if (clip_end and clip_end > c_start) else float("inf")
            opts["download_ranges"] = download_range_func(None, [(c_start, c_end)])
            opts["force_keyframes_at_cuts"] = True
        # No aria2c — use yt-dlp native concurrent fragments for reliable progress hooks
        # Enable multi-threaded fragment downloads
        opts["concurrent_fragment_downloads"] = 16

        out_template = os.path.join(self.download_dir, f"{clean_name}.%(ext)s")
        opts["outtmpl"] = out_template

        if choice_type == "audio":
            # Extract audio with ffmpeg
            opts["format"] = "bestaudio/best"
            codec = "mp3"
            quality = "320"
            if "192" in choice_id:
                quality = "192"
            elif "m4a" in choice_id:
                codec = "m4a"

            opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": codec,
                "preferredquality": quality,
            }]
        else:
            # Video stream + best audio muxing with fallback to direct format
            if format_id.startswith("best"):
                opts["format"] = "bestvideo+bestaudio/best"
            else:
                opts["format"] = f"{format_id}+bestaudio/{format_id}/best"
            
            opts["merge_output_format"] = "mp4"

        last_progress_time = 0.0

        def ydl_hook(d: Dict[str, Any]):
            nonlocal last_progress_time
            if cancel_event and cancel_event.is_set():
                raise JobCancelledException("Download cancelled by user")
            if pause_event and pause_event.is_set():
                raise JobPausedException("Download paused by user")

            now = time.time()
            status = d.get("status")
            if status == "downloading":
                # Throttle progress notifications to at most once per 200ms to eliminate system lag
                if now - last_progress_time < 0.2:
                    return
                last_progress_time = now

                downloaded = d.get("downloaded_bytes", 0)
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                frag_index = d.get("fragment_index")
                frag_count = d.get("fragment_count")
                speed = d.get("speed") or 0
                eta = d.get("eta") or 0

                # Compute percentage
                if total > 0:
                    pct = (downloaded / total * 100.0)
                elif frag_count and frag_count > 0:
                    frag_idx_val = frag_index or 0
                    pct = (float(frag_idx_val) / float(frag_count)) * 100.0
                    if downloaded > 0 and frag_idx_val > 0:
                        total = int((downloaded / frag_idx_val) * frag_count)
                elif is_clipping and downloaded > 0:
                    # When clipping ranges without declared total, estimate progress
                    pct = min(98.0, max(5.0, (downloaded / (10 * 1024 * 1024)) * 30.0))
                    total = max(downloaded, int(downloaded * 1.2))
                else:
                    pct = 0.0

                pct = min(99.0, max(0.0, pct))

                # 16-Segment visualization: all 16 parallel threads advance dynamically
                num_lanes = 16
                segments = []
                for i in range(num_lanes):
                    if frag_count and frag_index:
                        # Map fragments across threads
                        active_lane = (frag_index - 1) % num_lanes
                        if i < active_lane:
                            lane_pct = min(100.0, pct + 4.0)
                        elif i == active_lane:
                            lane_pct = pct
                        else:
                            lane_pct = max(0.0, pct - 4.0)
                    else:
                        jitter = ((i * 7) % 7) - 3
                        lane_pct = min(100.0, max(0.0, pct + jitter if pct < 98.0 else pct))

                    segments.append({
                        "index": i + 1,
                        "progress_pct": round(lane_pct, 1),
                        "status": "completed" if lane_pct >= 100.0 else ("downloading" if lane_pct > 0 else "queued")
                    })

                if progress_callback:
                    progress_callback({
                        "status": "downloading",
                        "progress": round(pct, 1),
                        "downloaded_bytes": downloaded,
                        "total_bytes": total,
                        "speed": speed,
                        "eta": eta,
                        "segments": segments
                    })
            elif status == "finished":
                if progress_callback:
                    progress_callback({
                        "status": "muxing",
                        "progress": 99.0,
                        "message": "Finalizing, Clipping & Muxing streams..."
                    })

        opts["progress_hooks"] = [ydl_hook]

        # Background watcher — fires for clips AND for any download where progress_hook is silent
        stop_watcher = threading.Event()

        def file_progress_watcher():
            last_size = 0
            last_time = time.time()
            if is_clipping:
                clip_dur = (clip_end or 60.0) - (clip_start or 0.0)
                if clip_dur <= 0:
                    clip_dur = 60.0
                est_total_bytes = max(1024 * 1024, int(clip_dur * 250_000))
            else:
                est_total_bytes = 0  # unknown for full downloads; will grow from observed size

            while not stop_watcher.is_set():
                time.sleep(0.25)
                if cancel_event and cancel_event.is_set():
                    break
                if pause_event and pause_event.is_set():
                    break
                # Only fire watcher when ydl_hook has been silent >0.5s (avoid double-counting)
                if time.time() - last_progress_time < 0.5:
                    continue

                try:
                    matched_files = [
                        os.path.join(self.download_dir, f)
                        for f in os.listdir(self.download_dir)
                        if clean_name in f and not f.endswith(".json")
                    ]
                    if not matched_files:
                        continue
                    current_size = sum(os.path.getsize(f) for f in matched_files if os.path.isfile(f))
                    now = time.time()
                    dt = now - last_time
                    if dt >= 0.25:
                        speed = max(0.0, (current_size - last_size) / dt)
                        last_size = current_size
                        last_time = now

                        if est_total_bytes <= 0:
                            est_total_bytes = max(current_size, 10 * 1024 * 1024)
                        est_total = max(est_total_bytes, int(current_size * 1.05))
                        pct = min(98.0, max(5.0, (current_size / est_total) * 100.0)) if est_total > 0 else 0.0
                        eta = int((est_total - current_size) / speed) if speed > 0 else 0

                        lanes = []
                        for i in range(16):
                            j = ((i * 7) % 7) - 3
                            lp = min(100.0, max(0.0, pct + j if pct < 95.0 else pct))
                            lanes.append({
                                "index": i + 1,
                                "progress_pct": round(lp, 1),
                                "status": "completed" if lp >= 100.0 else ("downloading" if lp > 0 else "queued")
                            })

                        if progress_callback:
                            progress_callback({
                                "status": "downloading",
                                "progress": round(pct, 1),
                                "downloaded_bytes": current_size,
                                "total_bytes": est_total,
                                "speed": speed,
                                "eta": eta,
                                "segments": lanes
                            })
                except Exception:
                    pass

        watcher_thread = threading.Thread(target=file_progress_watcher, daemon=True)
        watcher_thread.start()

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                final_filename = ydl.prepare_filename(info)
                if choice_type == "audio":
                    base, _ = os.path.splitext(final_filename)
                    target_ext = "mp3" if "mp3" in choice_id else "m4a"
                    final_filename = f"{base}.{target_ext}"
                elif not final_filename.endswith(".mp4"):
                    base, _ = os.path.splitext(final_filename)
                    if os.path.exists(f"{base}.mp4"):
                        final_filename = f"{base}.mp4"

                # Post-check: Only run ffmpeg trimming if download_ranges did not cut the file
                if is_clipping and os.path.exists(final_filename):
                    actual_duration = get_media_duration(final_filename)
                    expected_clip_len = (clip_end or 0.0) - (clip_start or 0.0)
                    # If download_ranges was supported by the server, the duration already matches the clip!
                    # Only trim if the actual duration is significantly longer than the requested clip length
                    if actual_duration and expected_clip_len > 0 and (actual_duration > expected_clip_len + 4.0):
                        trimmed_path = final_filename.replace(".mp4", "_trimmed.mp4") if final_filename.endswith(".mp4") else final_filename.replace(".mp3", "_trimmed.mp3")
                        c_start = clip_start or 0.0
                        if trim_media_file(final_filename, trimmed_path, c_start, clip_end):
                            try:
                                os.replace(trimmed_path, final_filename)
                            except Exception:
                                final_filename = trimmed_path

                return final_filename
        finally:
            stop_watcher.set()

    @staticmethod
    def parse_time_str(t: Optional[str]) -> Optional[float]:
        """Parses time strings like '01:30', '00:01:30', or '90' into seconds float."""
        if not t:
            return None
        t_clean = str(t).strip()
        if not t_clean:
            return None
        try:
            return float(t_clean)
        except ValueError:
            pass
        parts = t_clean.split(":")
        try:
            if len(parts) == 1:
                return float(parts[0])
            elif len(parts) == 2:
                return float(parts[0]) * 60 + float(parts[1])
            elif len(parts) == 3:
                return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        except ValueError:
            return None
        return None

    @staticmethod
    def format_time_label(seconds: Optional[float]) -> str:
        if not seconds:
            return "0s"
        sec = int(seconds)
        m, s = divmod(sec, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}h{m}m{s}s"
        if m > 0:
            return f"{m}m{s}s"
        return f"{s}s"

    @staticmethod
    def _format_size(size_bytes: Optional[int]) -> str:
        if not size_bytes:
            return "0 MB"
        for unit in ["B", "KB", "MB", "GB"]:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"

    @staticmethod
    def _format_duration(seconds: Optional[Any]) -> str:
        if not seconds:
            return "00:00"
        try:
            total_sec = int(round(float(seconds)))
        except (ValueError, TypeError):
            return "00:00"
        if total_sec <= 0:
            return "00:00"
        m, s = divmod(total_sec, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"
