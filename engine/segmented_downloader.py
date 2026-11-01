import asyncio
import json
import os
import re
import time
from typing import Any, Callable, Dict, List, Optional
import httpx

class Segment:
    def __init__(self, index: int, start: int, end: int, downloaded: int = 0):
        self.index = index
        self.start = start
        self.end = end
        self.downloaded = downloaded

    @property
    def total_bytes(self) -> int:
        return self.end - self.start + 1

    @property
    def remaining_bytes(self) -> int:
        return max(0, self.total_bytes - self.downloaded)

    @property
    def progress_pct(self) -> float:
        if self.total_bytes <= 0:
            return 100.0
        return min(100.0, round((self.downloaded / self.total_bytes) * 100.0, 1))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "start": self.start,
            "end": self.end,
            "downloaded": self.downloaded,
            "total": self.total_bytes,
            "progress_pct": self.progress_pct
        }


class SegmentedDownloader:
    """High-performance multi-connection HTTP/HTTPS segmented downloader (IDM-style)

    Supports parallel byte-range connections, pause/resume, and real-time segment telemetry.
    """

    def __init__(
        self,
        url: str,
        output_dir: str,
        custom_filename: Optional[str] = None,
        connections: int = 8,
        headers: Optional[Dict[str, str]] = None
    ):
        self.url = url
        self.output_dir = output_dir
        self.custom_filename = custom_filename
        self.connections = max(1, min(connections, 32))
        self.headers = headers or {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept": "*/*"
        }

        self.filename = ""
        self.final_path = ""
        self.meta_path = ""
        self.total_size = 0
        self.accepts_ranges = False
        self.segments: List[Segment] = []

        self.is_paused = False
        self.is_cancelled = False
        self._pause_event = asyncio.Event()
        self._pause_event.set()

    @staticmethod
    async def inspect_url(url: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Probes remote URL to check content length, range support, and filename."""
        req_headers = headers or {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        }

        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            try:
                # First attempt: HEAD
                resp = await client.head(url, headers=req_headers)
                if resp.status_code >= 400:
                    # Fallback to GET with Range: 0-0
                    range_h = dict(req_headers)
                    range_h["Range"] = "bytes=0-0"
                    resp = await client.get(url, headers=range_h)
            except Exception:
                # Secondary fallback: GET with Range: 0-0
                range_h = dict(req_headers)
                range_h["Range"] = "bytes=0-0"
                resp = await client.get(url, headers=range_h)

            content_len = resp.headers.get("content-length")
            total_size = int(content_len) if content_len and content_len.isdigit() else 0

            # Content range check (e.g. bytes 0-0/1048576)
            cr = resp.headers.get("content-range")
            if cr and "/" in cr:
                total_str = cr.split("/")[-1]
                if total_str.isdigit():
                    total_size = int(total_str)

            accept_ranges = resp.headers.get("accept-ranges") == "bytes" or resp.status_code == 206

            # Determine filename
            filename = ""
            cd = resp.headers.get("content-disposition")
            if cd:
                match = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';\r\n]+)', cd, re.IGNORECASE)
                if match:
                    filename = match.group(1).strip()

            if not filename:
                # Extract from URL path
                path = resp.url.path
                basename = os.path.basename(path.rstrip("/"))
                if basename and "." in basename:
                    filename = basename
                else:
                    filename = "download.bin"

            content_type = resp.headers.get("content-type", "application/octet-stream")

            return {
                "url": str(resp.url),
                "filename": filename,
                "total_size": total_size,
                "total_size_str": SegmentedDownloader._format_size(total_size),
                "accepts_ranges": accept_ranges,
                "content_type": content_type
            }

    async def initialize(self):
        """Prepares filenames, metadata, and segment boundaries."""
        info = await self.inspect_url(self.url, self.headers)
        self.filename = self.custom_filename or info["filename"]
        # Sanitize filename for macOS
        self.filename = re.sub(r'[/\\:*?"<>|]', "_", self.filename).strip()
        if not self.filename:
            self.filename = "downloaded_file.bin"

        self.final_path = os.path.join(self.output_dir, self.filename)
        self.meta_path = f"{self.final_path}.meta.json"
        self.total_size = info["total_size"]
        self.accepts_ranges = info["accepts_ranges"]

        # Check for existing partial download to resume
        if os.path.exists(self.meta_path):
            try:
                with open(self.meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                if meta.get("url") == self.url and meta.get("total_size") == self.total_size:
                    self.segments = [
                        Segment(s["index"], s["start"], s["end"], s.get("downloaded", 0))
                        for s in meta.get("segments", [])
                    ]
                    # Verify on-disk part files
                    for seg in self.segments:
                        part_file = f"{self.final_path}.part{seg.index}"
                        if os.path.exists(part_file):
                            seg.downloaded = os.path.getsize(part_file)
                    return
            except Exception:
                pass

        # Create fresh segments
        self.segments = []
        if self.accepts_ranges and self.total_size > 1024 * 1024 and self.connections > 1:
            chunk_size = self.total_size // self.connections
            for i in range(self.connections):
                start = i * chunk_size
                end = (self.total_size - 1) if i == self.connections - 1 else (start + chunk_size - 1)
                self.segments.append(Segment(i, start, end, 0))
        else:
            # Single connection
            self.segments.append(Segment(0, 0, max(0, self.total_size - 1), 0))

        self._save_meta()

    def _save_meta(self):
        try:
            data = {
                "url": self.url,
                "filename": self.filename,
                "total_size": self.total_size,
                "connections": len(self.segments),
                "segments": [s.to_dict() for s in self.segments]
            }
            with open(self.meta_path, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception:
            pass

    async def download(self, progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None) -> str:
        """Executes concurrent segment download with real-time speed & telemetry."""
        if not self.segments:
            await self.initialize()

        last_tick_time = time.time()
        last_total_downloaded = sum(s.downloaded for s in self.segments)
        speed = 0.0

        async def _download_segment(seg: Segment, client: httpx.AsyncClient):
            part_file = f"{self.final_path}.part{seg.index}"
            
            # Check already finished
            if seg.downloaded >= seg.total_bytes and seg.total_bytes > 0:
                return

            req_headers = dict(self.headers)
            current_start = seg.start + seg.downloaded
            if self.accepts_ranges and self.total_size > 0:
                req_headers["Range"] = f"bytes={current_start}-{seg.end}"

            mode = "ab" if seg.downloaded > 0 and os.path.exists(part_file) else "wb"
            with open(part_file, mode) as f:
                async with client.stream("GET", self.url, headers=req_headers, timeout=60.0) as resp:
                    resp.raise_for_status()
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        while not self._pause_event.is_set():
                            if self.is_cancelled:
                                return
                            await asyncio.sleep(0.1)

                        if self.is_cancelled:
                            return

                        f.write(chunk)
                        seg.downloaded += len(chunk)

        async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
            tasks = [asyncio.create_task(_download_segment(seg, client)) for seg in self.segments]

            # Telemetry monitor loop
            while not all(t.done() for t in tasks):
                if self.is_cancelled:
                    for t in tasks:
                        t.cancel()
                    break

                now = time.time()
                elapsed = now - last_tick_time
                current_total = sum(s.downloaded for s in self.segments)

                if elapsed >= 0.5:
                    speed = max(0.0, (current_total - last_total_downloaded) / elapsed)
                    last_total_downloaded = current_total
                    last_tick_time = now

                    remaining = max(0, self.total_size - current_total)
                    eta = int(remaining / speed) if speed > 0 and self.total_size > 0 else 0
                    pct = round((current_total / self.total_size * 100.0), 1) if self.total_size > 0 else 0.0

                    if progress_callback:
                        progress_callback({
                            "status": "downloading" if not self.is_paused else "paused",
                            "progress": pct,
                            "downloaded_bytes": current_total,
                            "total_bytes": self.total_size,
                            "speed": speed,
                            "eta": eta,
                            "segments": [s.to_dict() for s in self.segments]
                        })

                    self._save_meta()

                await asyncio.sleep(0.2)

            await asyncio.gather(*tasks, return_exceptions=True)

        if self.is_cancelled:
            self._cleanup_parts()
            raise asyncio.CancelledError("Download cancelled")

        if self.is_paused:
            self._save_meta()
            return self.final_path

        # Assemble parts into final destination
        if progress_callback:
            progress_callback({
                "status": "assembling",
                "progress": 99.0,
                "message": "Assembling downloaded chunks..."
            })

        with open(self.final_path, "wb") as outfile:
            for seg in self.segments:
                part_file = f"{self.final_path}.part{seg.index}"
                if os.path.exists(part_file):
                    with open(part_file, "rb") as infile:
                        while chunk := infile.read(1024 * 1024):
                            outfile.write(chunk)
                else:
                    raise FileNotFoundError(f"Missing part file: {part_file}")

        self._cleanup_parts()
        return self.final_path

    def pause(self):
        self.is_paused = True
        self._pause_event.clear()

    def resume(self):
        self.is_paused = False
        self._pause_event.set()

    def cancel(self):
        self.is_cancelled = True
        self._pause_event.set()

    def _cleanup_parts(self):
        for seg in self.segments:
            p = f"{self.final_path}.part{seg.index}"
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass
        if os.path.exists(self.meta_path):
            try:
                os.remove(self.meta_path)
            except Exception:
                pass

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        if not size_bytes:
            return "Unknown"
        s = float(size_bytes)
        for unit in ["B", "KB", "MB", "GB"]:
            if s < 1024:
                return f"{s:.1f} {unit}"
            s /= 1024
        return f"{s:.1f} TB"
