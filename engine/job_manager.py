import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
import subprocess
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from engine.media_extractor import MediaExtractor, JobPausedException
from engine.segmented_downloader import SegmentedDownloader

class Job:
    def __init__(
        self,
        job_id: str,
        url: str,
        title: str,
        job_type: str, # "media" or "direct"
        output_dir: str,
        format_info: Optional[Dict[str, Any]] = None,
        thumbnail: str = "",
        connections: int = 8,
        browser_cookies: Optional[str] = None,
        clip_start: Optional[str] = None,
        clip_end: Optional[str] = None
    ):
        self.id = job_id
        self.url = url
        self.title = title
        self.type = job_type
        self.output_dir = output_dir
        self.format_info = format_info or {}
        self.thumbnail = thumbnail
        self.connections = connections
        self.browser_cookies = browser_cookies
        self.clip_start = clip_start
        self.clip_end = clip_end

        self.status = "queued" # queued, downloading, assembling, paused, completed, error
        self.progress = 0.0
        self.downloaded_bytes = 0
        self.total_bytes = 0
        self.speed = 0.0
        self.eta = 0
        self.error_message = ""
        self.output_path = ""
        self.created_at = time.time()
        self.completed_at = 0.0
        self.segments: List[Dict[str, Any]] = []

        # Cancellation & Pause primitives
        self.cancel_event = threading.Event()
        self.pause_event = threading.Event()
        self.downloader_instance: Optional[SegmentedDownloader] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "url": self.url,
            "title": self.title,
            "type": self.type,
            "status": self.status,
            "progress": self.progress,
            "downloaded_bytes": self.downloaded_bytes,
            "total_bytes": self.total_bytes,
            "downloaded_str": self._format_size(self.downloaded_bytes),
            "total_str": self._format_size(self.total_bytes),
            "speed": self.speed,
            "speed_str": f"{self._format_size(int(self.speed))}/s" if self.speed > 0 else "0 KB/s",
            "eta": self.eta,
            "eta_str": self._format_eta(self.eta),
            "thumbnail": self.thumbnail,
            "output_path": self.output_path,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "error_message": self.error_message,
            "segments": self.segments,
            "clip_start": self.clip_start,
            "clip_end": self.clip_end
        }

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        if not size_bytes:
            return "0 MB"
        s = float(size_bytes)
        for unit in ["B", "KB", "MB", "GB"]:
            if s < 1024:
                return f"{s:.1f} {unit}"
            s /= 1024
        return f"{s:.1f} TB"

    @staticmethod
    def _format_eta(seconds: Any) -> str:
        if not seconds:
            return "--"
        try:
            sec = int(round(float(seconds)))
        except (ValueError, TypeError):
            return "--"
        if sec <= 0:
            return "--"
        m, s = divmod(sec, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}h {m}m"
        if m > 0:
            return f"{m}m {s}s"
        return f"{s}s"


class JobManager:
    """Central Job Coordinator for VeloxMac

    Manages active queues, background threads, direct download workers,
    JSON state storage, and macOS Finder integration.
    """

    def __init__(self, download_dir: str, state_file: str):
        self.download_dir = download_dir
        self.state_file = state_file
        os.makedirs(self.download_dir, exist_ok=True)

        self.jobs: Dict[str, Job] = {}
        self.media_extractor = MediaExtractor(download_dir=self.download_dir)
        self.thread_pool = ThreadPoolExecutor(max_workers=4)
        self.ws_subscribers: List[asyncio.Queue] = []

        self._load_state()

    def _load_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for item in data:
                    job = Job(
                        job_id=item["id"],
                        url=item["url"],
                        title=item["title"],
                        job_type=item["type"],
                        output_dir=self.download_dir,
                        thumbnail=item.get("thumbnail", "")
                    )
                    job.status = item.get("status", "completed")
                    if job.status == "downloading":
                        job.status = "paused"
                    job.progress = item.get("progress", 100.0)
                    job.downloaded_bytes = item.get("downloaded_bytes", 0)
                    job.total_bytes = item.get("total_bytes", 0)
                    job.output_path = item.get("output_path", "")
                    job.created_at = item.get("created_at", time.time())
                    job.completed_at = item.get("completed_at", 0.0)
                    self.jobs[job.id] = job
            except Exception:
                pass

    def _save_state(self):
        try:
            data = [j.to_dict() for j in self.jobs.values()]
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self.ws_subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        if q in self.ws_subscribers:
            self.ws_subscribers.remove(q)

    def broadcast_update(self, data: Dict[str, Any]):
        for q in list(self.ws_subscribers):
            try:
                q.put_nowait(data)
            except Exception:
                pass

    def add_media_job(
        self,
        url: str,
        title: str,
        format_info: Dict[str, Any],
        thumbnail: str = "",
        browser_cookies: Optional[str] = None,
        clip_start: Optional[str] = None,
        clip_end: Optional[str] = None
    ) -> Job:
        job_id = str(uuid.uuid4())[:8]
        job = Job(
            job_id=job_id,
            url=url,
            title=title,
            job_type="media",
            output_dir=self.download_dir,
            format_info=format_info,
            thumbnail=thumbnail,
            browser_cookies=browser_cookies,
            clip_start=clip_start,
            clip_end=clip_end
        )
        self.jobs[job_id] = job
        self._save_state()

        # Launch in thread pool
        asyncio.create_task(self._run_media_job(job))
        return job

    def add_direct_job(self, url: str, filename: str, connections: int = 8) -> Job:
        job_id = str(uuid.uuid4())[:8]
        job = Job(
            job_id=job_id,
            url=url,
            title=filename or "Direct Download",
            job_type="direct",
            output_dir=self.download_dir,
            connections=connections
        )
        self.jobs[job_id] = job
        self._save_state()

        # Launch async task
        asyncio.create_task(self._run_direct_job(job))
        return job

    async def _run_media_job(self, job: Job):
        job.status = "downloading"
        loop = asyncio.get_running_loop()

        def progress_cb(data: Dict[str, Any]):
            status = data.get("status")
            if status == "downloading":
                job.progress = data.get("progress", 0.0)
                job.downloaded_bytes = data.get("downloaded_bytes", 0)
                job.total_bytes = data.get("total_bytes", 0)
                job.speed = data.get("speed", 0.0)
                job.eta = data.get("eta", 0)
                job.segments = data.get("segments", [])
            elif status == "muxing":
                job.status = "assembling"
                job.progress = 99.0

            self.broadcast_update({"type": "job_update", "job": job.to_dict()})

        choice_type = job.format_info.get("type", "video")
        choice_id = job.format_info.get("id", "")
        format_id = job.format_info.get("format_id", "best")

        c_start = MediaExtractor.parse_time_str(job.clip_start)
        c_end = MediaExtractor.parse_time_str(job.clip_end)

        try:
            final_file = await loop.run_in_executor(
                self.thread_pool,
                lambda: self.media_extractor.download(
                    url=job.url,
                    choice_type=choice_type,
                    choice_id=choice_id,
                    format_id=format_id,
                    output_name=job.title,
                    progress_callback=progress_cb,
                    cancel_event=job.cancel_event,
                    pause_event=job.pause_event,
                    browser_cookies=job.browser_cookies,
                    clip_start=c_start,
                    clip_end=c_end
                )
            )
            job.output_path = final_file
            job.status = "completed"
            job.progress = 100.0
            job.completed_at = time.time()
            job.speed = 0.0
            job.eta = 0
            if os.path.exists(final_file):
                job.total_bytes = os.path.getsize(final_file)
                job.downloaded_bytes = job.total_bytes
        except JobPausedException:
            job.status = "paused"
            job.speed = 0.0
            job.eta = 0
        except Exception as e:
            if job.cancel_event.is_set():
                job.status = "cancelled"
            elif job.pause_event.is_set():
                job.status = "paused"
                job.speed = 0.0
                job.eta = 0
            else:
                job.status = "error"
                job.error_message = str(e)
        finally:
            self._save_state()
            self.broadcast_update({"type": "job_update", "job": job.to_dict()})

    async def _run_direct_job(self, job: Job):
        job.status = "downloading"
        downloader = SegmentedDownloader(
            url=job.url,
            output_dir=self.download_dir,
            custom_filename=job.title if job.title != "Direct Download" else None,
            connections=job.connections
        )
        job.downloader_instance = downloader

        def progress_cb(data: Dict[str, Any]):
            job.status = data.get("status", "downloading")
            job.progress = data.get("progress", 0.0)
            job.downloaded_bytes = data.get("downloaded_bytes", 0)
            job.total_bytes = data.get("total_bytes", 0)
            job.speed = data.get("speed", 0.0)
            job.eta = data.get("eta", 0)
            job.segments = data.get("segments", [])
            self.broadcast_update({"type": "job_update", "job": job.to_dict()})

        try:
            final_file = await downloader.download(progress_callback=progress_cb)
            if not downloader.is_paused and not downloader.is_cancelled:
                job.output_path = final_file
                job.status = "completed"
                job.progress = 100.0
                job.completed_at = time.time()
                job.speed = 0.0
                job.eta = 0
                if os.path.exists(final_file):
                    job.total_bytes = os.path.getsize(final_file)
                    job.downloaded_bytes = job.total_bytes
        except asyncio.CancelledError:
            job.status = "cancelled"
        except Exception as e:
            job.status = "error"
            job.error_message = str(e)
        finally:
            self._save_state()
            self.broadcast_update({"type": "job_update", "job": job.to_dict()})

    def pause_job(self, job_id: str):
        job = self.jobs.get(job_id)
        if job and job.status in ("downloading", "assembling"):
            job.status = "paused"
            job.speed = 0.0
            job.eta = 0
            job.pause_event.set()
            if job.downloader_instance:
                job.downloader_instance.pause()
            self._save_state()
            self.broadcast_update({"type": "job_update", "job": job.to_dict()})

    def resume_job(self, job_id: str):
        job = self.jobs.get(job_id)
        if job and job.status == "paused":
            job.status = "downloading"
            job.pause_event.clear()
            job.cancel_event.clear()
            if job.downloader_instance:
                job.downloader_instance.resume()
                asyncio.create_task(self._run_direct_job(job))
            elif job.type == "media":
                asyncio.create_task(self._run_media_job(job))
            self._save_state()
            self.broadcast_update({"type": "job_update", "job": job.to_dict()})

    def cancel_job(self, job_id: str):
        job = self.jobs.get(job_id)
        if job:
            job.pause_event.set()
            job.cancel_event.set()
            if job.downloader_instance:
                job.downloader_instance.cancel()
            job.status = "cancelled"
            job.speed = 0.0
            job.eta = 0
            self._save_state()
            self.broadcast_update({"type": "job_update", "job": job.to_dict()})

    def delete_job(self, job_id: str):
        if job_id in self.jobs:
            self.cancel_job(job_id)
            del self.jobs[job_id]
            self._save_state()
            self.broadcast_update({"type": "job_deleted", "job_id": job_id})

    def reveal_in_finder(self, job_id: str) -> bool:
        """Reveals the completed file in macOS Finder."""
        job = self.jobs.get(job_id)
        if job and job.output_path and os.path.exists(job.output_path):
            subprocess.run(["open", "-R", job.output_path])
            return True
        return False

    def open_file(self, job_id: str) -> bool:
        """Opens the completed file with default macOS application."""
        job = self.jobs.get(job_id)
        if job and job.output_path and os.path.exists(job.output_path):
            subprocess.run(["open", job.output_path])
            return True
        return False
