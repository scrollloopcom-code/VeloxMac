import os
import re
import shutil
import threading
from typing import Any, Callable, Dict, List, Optional
import yt_dlp
from yt_dlp.utils import download_range_func

from engine.muxer import FFMPEG_PATH, trim_media_file

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

    def inspect(self, url: str, browser_cookies: Optional[str] = None) -> Dict[str, Any]:
        """Extracts metadata and structured resolution/audio choices from a media URL."""
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

            for f in sorted(raw_formats, key=lambda x: (x.get("height") or 0, x.get("tbr") or 0), reverse=True):
                h = f.get("height")
                vcodec = f.get("vcodec", "none")
                if not h or vcodec == "none":
                    continue

                if h in seen_resolutions:
                    continue
                seen_resolutions.add(h)

                label = res_labels.get(h, f"{h}p")
                fps = f.get("fps")
                if fps and fps > 30:
                    label += f" {int(fps)}fps"

                # Calculate estimated size
                filesize = f.get("filesize") or f.get("filesize_approx")
                filesize_str = self._format_size(filesize) if filesize else "Adaptive"

                format_id = f.get("format_id")
                video_options.append({
                    "id": f"video_{h}_{format_id}",
                    "format_id": format_id,
                    "height": h,
                    "label": label,
                    "ext": "mp4",
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
            for f in raw_formats:
                if f.get("vcodec") != "none" and f.get("acodec") != "none" and f.get("url"):
                    preview_stream_url = f.get("url")
                    break

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
        browser_cookies: Optional[str] = None,
        clip_start: Optional[float] = None,
        clip_end: Optional[float] = None
    ) -> str:
        """Downloads selected media stream with live progress, clipping, and ffmpeg muxing."""
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

        # Enable 16x multi-threaded parallel fragment downloading (IDM Turbo mode)
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
            # Video stream + best audio muxing
            if format_id.startswith("best"):
                opts["format"] = "bestvideo+bestaudio/best"
            else:
                opts["format"] = f"{format_id}+bestaudio/best"
            
            opts["merge_output_format"] = "mp4"

        last_progress_time = 0

        def ydl_hook(d: Dict[str, Any]):
            if cancel_event and cancel_event.is_set():
                raise KeyboardInterrupt("Download cancelled by user")

            status = d.get("status")
            if status == "downloading":
                downloaded = d.get("downloaded_bytes", 0)
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                speed = d.get("speed") or 0
                eta = d.get("eta") or 0

                pct = (downloaded / total * 100.0) if total > 0 else 0.0

                # 16-Segment visualization for multi-connection fragment threads
                num_lanes = 16
                segments = []
                for i in range(num_lanes):
                    lane_start = i * (100.0 / num_lanes)
                    lane_end = (i + 1) * (100.0 / num_lanes)
                    if pct >= lane_end:
                        lane_pct = 100.0
                    elif pct > lane_start:
                        lane_pct = ((pct - lane_start) / (100.0 / num_lanes)) * 100.0
                    else:
                        lane_pct = 0.0
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

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            # Find the actual written filename
            final_filename = ydl.prepare_filename(info)
            if choice_type == "audio":
                base, _ = os.path.splitext(final_filename)
                target_ext = "mp3" if "mp3" in choice_id else "m4a"
                final_filename = f"{base}.{target_ext}"
            elif not final_filename.endswith(".mp4"):
                base, _ = os.path.splitext(final_filename)
                if os.path.exists(f"{base}.mp4"):
                    final_filename = f"{base}.mp4"

            # Post-check: ensure trimming is applied if download_ranges was ignored by certain extractors
            if is_clipping and os.path.exists(final_filename):
                trimmed_path = final_filename.replace(".mp4", "_trimmed.mp4") if final_filename.endswith(".mp4") else final_filename.replace(".mp3", "_trimmed.mp3")
                c_start = clip_start or 0.0
                if trim_media_file(final_filename, trimmed_path, c_start, clip_end):
                    try:
                        os.replace(trimmed_path, final_filename)
                    except Exception:
                        final_filename = trimmed_path

            return final_filename

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
    def _format_duration(seconds: Optional[int]) -> str:
        if not seconds:
            return "00:00"
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"
