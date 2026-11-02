import os
import shutil
import subprocess
from typing import Optional

def find_ffmpeg() -> Optional[str]:
    """Finds the best available ffmpeg binary on macOS."""
    candidates = [
        "/opt/homebrew/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
        shutil.which("ffmpeg")
    ]
    for c in candidates:
        if c and os.path.exists(c) and os.access(c, os.X_OK):
            return c
    return None

def find_ffprobe() -> Optional[str]:
    """Finds the best available ffprobe binary on macOS."""
    candidates = [
        "/opt/homebrew/bin/ffprobe",
        "/usr/local/bin/ffprobe",
        shutil.which("ffprobe")
    ]
    for c in candidates:
        if c and os.path.exists(c) and os.access(c, os.X_OK):
            return c
    return None

FFMPEG_PATH = find_ffmpeg()
FFPROBE_PATH = find_ffprobe()

def is_ffmpeg_available() -> bool:
    return FFMPEG_PATH is not None

def run_ffmpeg(args: list[str], timeout: Optional[int] = 300) -> subprocess.CompletedProcess:
    """Runs ffmpeg with provided arguments, hard memory cap and thread limits."""
    if not FFMPEG_PATH:
        raise RuntimeError("ffmpeg binary not found on macOS system")
    # Prepend thread-limiting flags before user args so user args can override
    # -threads 2 caps CPU threads; -hide_banner reduces noise
    base_args = ["-threads", "2", "-hide_banner"]
    cmd = [FFMPEG_PATH] + base_args + args

    import resource
    def set_limits():
        # Cap virtual memory at 2 GB to prevent runaway ffmpeg RAM usage
        two_gb = 2 * 1024 * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_AS, (two_gb, two_gb))
        except Exception:
            pass

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        preexec_fn=set_limits,
    )

def get_media_duration(file_path: str) -> Optional[float]:
    """Inspects the exact media duration in seconds using ffprobe."""
    if not FFPROBE_PATH or not os.path.exists(file_path):
        return None
    try:
        cmd = [
            FFPROBE_PATH, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if res.returncode == 0 and res.stdout.strip():
            return float(res.stdout.strip())
    except Exception:
        pass
    return None

def trim_media_file(input_file: str, output_file: str, start_sec: float, end_sec: Optional[float] = None) -> bool:
    """Precisely trims a media file using ffmpeg with stream-copy and re-encode fallback."""
    if not FFMPEG_PATH or not os.path.exists(input_file):
        return False

    args = ["-y", "-ss", str(start_sec)]
    if end_sec is not None and end_sec > start_sec:
        args += ["-to", str(end_sec)]
    args += ["-i", input_file, "-c", "copy", output_file]

    res = run_ffmpeg(args, timeout=180)
    if res.returncode == 0 and os.path.exists(output_file) and os.path.getsize(output_file) > 0:
        return True

    # Fallback without -c copy for non-keyframe cuts
    args = ["-y", "-ss", str(start_sec)]
    if end_sec is not None and end_sec > start_sec:
        args += ["-to", str(end_sec)]
    args += ["-i", input_file, output_file]
    res = run_ffmpeg(args, timeout=300)
    return res.returncode == 0 and os.path.exists(output_file) and os.path.getsize(output_file) > 0
