"""
Velox Cross-Platform In-App Auto-Updater Engine.
Checks for releases on GitHub, downloads binary/package updates with live telemetry,
and performs 1-click in-place application upgrade and seamless restart on macOS and Windows.
"""

import asyncio
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Dict, Optional
import httpx

from version import APP_NAME, APP_VERSION, GITHUB_OWNER, GITHUB_REPO

def parse_semver(v: Optional[str]) -> tuple:
    """Parses a version string like '1.2.3' or 'v1.2.3' into a comparable integer tuple."""
    if not v:
        return (0, 0, 0)
    clean = re.sub(r'^[vV]', '', str(v).strip())
    # Extract numeric components
    match = re.match(r'^(\d+)(?:\.(\d+))?(?:\.(\d+))?', clean)
    if match:
        parts = [int(p) if p else 0 for p in match.groups()]
        return tuple(parts)
    return (0, 0, 0)

def is_newer_version(latest: str, current: str) -> bool:
    """Returns True if latest > current using semantic version comparison."""
    return parse_semver(latest) > parse_semver(current)

class AutoUpdater:
    def __init__(self, download_dir: str):
        self.download_dir = download_dir
        self.current_version = APP_VERSION
        self.github_owner = GITHUB_OWNER
        self.github_repo = GITHUB_REPO
        self.is_updating = False
        self.update_progress: Dict[str, Any] = {
            "status": "idle",
            "percent": 0.0,
            "downloaded_bytes": 0,
            "total_bytes": 0,
            "speed": 0.0,
            "message": ""
        }

    def _get_auth_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": f"{APP_NAME}-Desktop-Updater/{APP_VERSION}"
        }
        # Check environment variable or fallback git remote token
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            # Check git config or embedded repo token if present
            try:
                git_remote = subprocess.check_output(
                    ["git", "remote", "get-url", "origin"],
                    stderr=subprocess.DEVNULL,
                    text=True
                ).strip()
                match = re.search(r'x-access-token:([^@]+)@', git_remote)
                if match:
                    token = match.group(1)
            except Exception:
                pass
        if token:
            headers["Authorization"] = f"token {token}"
        return headers

    async def check_for_updates(self) -> Dict[str, Any]:
        """Queries GitHub for the latest release and matches the current OS asset."""
        api_url = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/releases/latest"
        headers = self._get_auth_headers()

        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                resp = await client.get(api_url, headers=headers)
                if resp.status_code == 404:
                    return {
                        "update_available": False,
                        "current_version": self.current_version,
                        "latest_version": self.current_version,
                        "message": "No published releases found."
                    }
                if resp.status_code != 200:
                    return {
                        "update_available": False,
                        "current_version": self.current_version,
                        "latest_version": self.current_version,
                        "message": f"GitHub API returned status {resp.status_code}"
                    }

                release = resp.json()
                tag_name = release.get("tag_name", "").strip()
                latest_clean = tag_name.lstrip("vV")
                changelog = release.get("body", "Bug fixes and performance improvements.")
                release_title = release.get("name") or f"Velox v{latest_clean}"

                if not is_newer_version(latest_clean, self.current_version):
                    return {
                        "update_available": False,
                        "current_version": self.current_version,
                        "latest_version": latest_clean,
                        "release_title": release_title,
                        "changelog": changelog,
                        "message": "You are on the latest version."
                    }

                # Find optimal asset for current OS
                assets = release.get("assets", [])
                chosen_asset = None

                if sys.platform == "win32":
                    # 1. First priority: Lightweight in-app patch zip (~18MB, no 150MB FFmpeg)
                    for a in assets:
                        name = a.get("name", "").lower()
                        if "update" in name and name.endswith(".zip"):
                            chosen_asset = a
                            break
                    # 2. Second priority: Full portable zip
                    if not chosen_asset:
                        for a in assets:
                            name = a.get("name", "").lower()
                            if "windows" in name and name.endswith(".zip"):
                                chosen_asset = a
                                break
                    # 3. Third priority: InnoSetup exe installer
                    if not chosen_asset:
                        for a in assets:
                            name = a.get("name", "").lower()
                            if "setup" in name and name.endswith(".exe"):
                                chosen_asset = a
                                break
                    if not chosen_asset:
                        for a in assets:
                            if a.get("name", "").endswith((".exe", ".zip")):
                                chosen_asset = a
                                break
                else: # macOS / Darwin
                    # Preference: .zip for in-place 1-click upgrade, then .dmg
                    for a in assets:
                        name = a.get("name", "").lower()
                        if "mac" in name and name.endswith(".zip"):
                            chosen_asset = a
                            break
                    if not chosen_asset:
                        for a in assets:
                            name = a.get("name", "").lower()
                            if name.endswith(".dmg"):
                                chosen_asset = a
                                break
                    if not chosen_asset and assets:
                        chosen_asset = assets[0]

                if not chosen_asset:
                    return {
                        "update_available": True,
                        "current_version": self.current_version,
                        "latest_version": latest_clean,
                        "release_title": release_title,
                        "changelog": changelog,
                        "download_url": release.get("html_url", ""),
                        "asset_name": "Web Release",
                        "size_bytes": 0,
                        "message": f"Update v{latest_clean} is available! Please download from GitHub."
                    }

                download_url = chosen_asset.get("browser_download_url") or chosen_asset.get("url")
                return {
                    "update_available": True,
                    "current_version": self.current_version,
                    "latest_version": latest_clean,
                    "release_title": release_title,
                    "changelog": changelog,
                    "download_url": download_url,
                    "asset_name": chosen_asset.get("name"),
                    "size_bytes": chosen_asset.get("size", 0),
                    "message": f"⚡ Update v{latest_clean} is ready to install!"
                }

        except Exception as e:
            return {
                "update_available": False,
                "current_version": self.current_version,
                "latest_version": self.current_version,
                "error": str(e)
            }

    async def download_and_apply_update(
        self,
        download_url: str,
        progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> Dict[str, Any]:
        """Downloads the update binary and executes seamless 1-click in-place restart."""
        if self.is_updating:
            return {"status": "in_progress", "message": "An update is already downloading."}

        self.is_updating = True
        self.update_progress = {
            "status": "downloading",
            "percent": 0.0,
            "downloaded_bytes": 0,
            "total_bytes": 0,
            "speed": 0.0,
            "message": "Starting download..."
        }

        temp_dir = tempfile.mkdtemp(prefix="velox_update_")
        target_name = download_url.split("/")[-1].split("?")[0] or "velox_update.pkg"
        target_file = os.path.join(temp_dir, target_name)

        headers = self._get_auth_headers()
        # GitHub raw asset download requires Accept: application/octet-stream if using asset URL
        if "/assets/" in download_url:
            headers["Accept"] = "application/octet-stream"

        try:
            async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
                async with client.stream("GET", download_url, headers=headers) as resp:
                    if resp.status_code != 200:
                        raise RuntimeError(f"Download failed with HTTP status {resp.status_code}")

                    total_bytes = int(resp.headers.get("Content-Length", 0))
                    downloaded = 0
                    start_time = time.time()
                    last_emit_time = start_time

                    with open(target_file, "wb") as f:
                        async for chunk in resp.aiter_bytes(chunk_size=65536):
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)

                                now = time.time()
                                if now - last_emit_time >= 0.2:
                                    elapsed = max(0.01, now - start_time)
                                    speed = downloaded / elapsed
                                    pct = round((downloaded / total_bytes) * 100, 1) if total_bytes > 0 else 50.0
                                    self.update_progress.update({
                                        "status": "downloading",
                                        "percent": pct,
                                        "downloaded_bytes": downloaded,
                                        "total_bytes": total_bytes,
                                        "speed": speed,
                                        "message": f"Downloading update ({pct}%)..."
                                    })
                                    if progress_cb:
                                        progress_cb(self.update_progress)
                                    last_emit_time = now

            self.update_progress.update({
                "status": "applying",
                "percent": 100.0,
                "message": "Extracting and restarting application..."
            })
            if progress_cb:
                progress_cb(self.update_progress)

            # Apply update depending on OS and asset type
            success = self._execute_restart(target_file, temp_dir)
            return {"status": "restarting", "message": "Update downloaded successfully. Restarting..."}

        except Exception as e:
            self.update_progress.update({
                "status": "error",
                "message": f"Update failed: {str(e)}"
            })
            if progress_cb:
                progress_cb(self.update_progress)
            return {"status": "error", "error": str(e)}
        finally:
            self.is_updating = False

    def _execute_restart(self, package_path: str, temp_dir: str) -> bool:
        """Kicks off the detached OS-native update script and exits current process."""
        if sys.platform == "win32":
            return self._execute_restart_windows(package_path, temp_dir)
        elif sys.platform == "darwin":
            return self._execute_restart_macos(package_path, temp_dir)
        return False

    def _execute_restart_windows(self, package_path: str, temp_dir: str) -> bool:
        """Windows in-place replacement and app restart."""
        # Current exe or app directory
        app_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        current_pid = os.getpid()

        if package_path.endswith(".exe"):
            # If an installer (.exe) was downloaded, run installer detached and terminate self
            cmd = f'timeout /t 1 /nobreak >nul & start "" "{package_path}"'
            subprocess.Popen(
                ["cmd.exe", "/c", cmd],
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
            )
            # Schedule self termination
            threading_timer = asyncio.get_event_loop().call_later(0.5, lambda: sys.exit(0))
            return True

        # If .zip was downloaded, unpack in place
        bat_script = os.path.join(temp_dir, "velox_updater.bat")
        with open(bat_script, "w") as f:
            f.write(f"""@echo off
timeout /t 1 /nobreak >nul
taskkill /F /PID {current_pid} >nul 2>&1
tar -xf "{package_path}" -C "{app_dir}"
start "" "{os.path.join(app_dir, 'Velox.exe')}"
rd /s /q "{temp_dir}" >nul 2>&1
exit
""")
        subprocess.Popen(
            ["cmd.exe", "/c", bat_script],
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
        )
        asyncio.get_event_loop().call_later(0.5, lambda: sys.exit(0))
        return True

    def _execute_restart_macos(self, package_path: str, temp_dir: str) -> bool:
        """macOS in-place bundle replacement and app restart."""
        current_pid = os.getpid()
        sh_script = os.path.join(temp_dir, "velox_restart.sh")

        if package_path.endswith(".zip"):
            # Unpack zip in temp
            extract_dir = os.path.join(temp_dir, "extracted")
            os.makedirs(extract_dir, exist_ok=True)
            subprocess.run(["unzip", "-q", "-o", package_path, "-d", extract_dir], check=True)

            with open(sh_script, "w") as f:
                f.write(f"""#!/bin/bash
sleep 1
kill -9 {current_pid} 2>/dev/null
TARGET_APP="/Applications/VeloxMac.app"
NEW_APP="{extract_dir}/VeloxMac.app"
if [ -d "$NEW_APP" ]; then
    if [ -w "/Applications" ]; then
        rm -rf "$TARGET_APP"
        cp -R "$NEW_APP" "$TARGET_APP"
        open -n "$TARGET_APP"
    else
        open -n "$NEW_APP"
    fi
fi
rm -rf "{temp_dir}"
exit 0
""")
            os.chmod(sh_script, 0o755)
            subprocess.Popen(["/bin/bash", sh_script])
            asyncio.get_event_loop().call_later(0.5, lambda: sys.exit(0))
            return True

        elif package_path.endswith(".dmg"):
            # Mount DMG and copy VeloxMac.app to /Applications
            with open(sh_script, "w") as f:
                f.write(f"""#!/bin/bash
sleep 1
kill -9 {current_pid} 2>/dev/null
MOUNT_POINT="/Volumes/VeloxUpdate_{int(time.time())}"
mkdir -p "$MOUNT_POINT"
hdiutil attach "{package_path}" -mountpoint "$MOUNT_POINT" -nobrowse -quiet
TARGET_APP="/Applications/VeloxMac.app"
if [ -d "$MOUNT_POINT/VeloxMac.app" ]; then
    if [ -w "/Applications" ]; then
        rm -rf "$TARGET_APP"
        cp -R "$MOUNT_POINT/VeloxMac.app" "$TARGET_APP"
        hdiutil detach "$MOUNT_POINT" -quiet
        open -n "$TARGET_APP"
    else
        open "$MOUNT_POINT"
    fi
fi
rm -rf "{temp_dir}"
exit 0
""")
            os.chmod(sh_script, 0o755)
            subprocess.Popen(["/bin/bash", sh_script])
            asyncio.get_event_loop().call_later(0.5, lambda: sys.exit(0))
            return True

        return False
