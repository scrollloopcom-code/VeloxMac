"""
Velox Multi-Device Cookie Vault & Profile Manager.
Created by Lahiru_nk for Scroll Loop.
Allows storing and organizing browser cookies from different machines (e.g., MacBook, Mac Mini, Windows PCs)
with device details, platform breakdowns, and seamless 1-click active profile switching.
"""

import json
import os
import platform
import re
import shutil
import socket
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

class CookieVaultManager:
    def __init__(self, base_download_dir: str):
        self.base_download_dir = base_download_dir
        self.vault_dir = os.path.join(self.base_download_dir, "cookie_vault")
        os.makedirs(self.vault_dir, exist_ok=True)
        self.metadata_file = os.path.join(self.vault_dir, "devices.json")
        self.config_file = os.path.join(self.vault_dir, "vault_config.json")
        
        self.current_device_id = self._init_device_id()
        self._ensure_metadata_file()

    @property
    def current_device_name(self) -> str:
        data = self.get_vault_data()
        for dev in data.get("devices", []):
            if dev.get("id") == self.current_device_id:
                return dev.get("name", self.get_default_device_name())
        return self.get_default_device_name()

    def _init_device_id(self) -> str:
        """Generates or retrieves a persistent friendly ID for this physical PC."""
        dev_id_file = os.path.join(self.vault_dir, ".local_device_id")
        if os.path.exists(dev_id_file):
            try:
                with open(dev_id_file, "r") as f:
                    dev_id = f.read().strip()
                if dev_id:
                    return dev_id
            except Exception:
                pass

        # Generate friendly device identifier
        host = socket.gethostname().split(".")[0].replace(" ", "_")
        host_clean = re.sub(r'[^a-zA-Z0-9_\-]', '', host)
        os_prefix = "win" if sys.platform == "win32" else ("mac" if sys.platform == "darwin" else "linux")
        dev_id = f"{os_prefix}_{host_clean}".lower()
        
        try:
            with open(dev_id_file, "w") as f:
                f.write(dev_id)
        except Exception:
            pass
        return dev_id

    def get_default_device_name(self) -> str:
        """Returns a user-friendly default name for the current PC."""
        host = socket.gethostname().split(".")[0]
        if sys.platform == "darwin":
            return f"Lahiru's Mac ({host})"
        elif sys.platform == "win32":
            return f"Lahiru's Windows PC ({host})"
        return f"Lahiru's Linux ({host})"

    def _scan_cookie_file(self, filepath: str):
        valid_cnt = 0
        plats = set()
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("\t")
                    if len(parts) >= 7:
                        valid_cnt += 1
                        domain = parts[0].lower()
                        if "youtube" in domain or "google" in domain:
                            plats.add("YouTube")
                        elif "instagram" in domain:
                            plats.add("Instagram")
                        elif "facebook" in domain:
                            plats.add("Facebook")
                        elif "tiktok" in domain:
                            plats.add("TikTok")
                        elif "twitter" in domain or "x.com" in domain:
                            plats.add("Twitter/X")
                        elif "reddit" in domain:
                            plats.add("Reddit")
        except Exception:
            pass
        return valid_cnt, sorted(list(plats))

    def _ensure_metadata_file(self):
        if not os.path.exists(self.metadata_file):
            try:
                with open(self.metadata_file, "w", encoding="utf-8") as f:
                    json.dump({"devices": {}, "active_profile_id": self.current_device_id}, f, indent=2)
            except Exception:
                pass

    def get_vault_data(self) -> Dict[str, Any]:
        """Loads devices metadata and active profile setting."""
        try:
            if os.path.exists(self.metadata_file):
                with open(self.metadata_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = {"devices": {}, "active_profile_id": self.current_device_id}
        except Exception:
            data = {"devices": {}, "active_profile_id": self.current_device_id}

        devices = data.get("devices", {})
        active_id = data.get("active_profile_id", self.current_device_id)

        # Auto-discover any cookie files placed manually or transferred from another PC
        discovered_new = False
        try:
            for fname in os.listdir(self.vault_dir):
                if fname.endswith("_cookies.txt") and not fname.startswith("."):
                    dev_id = fname[:-12]
                    if dev_id and dev_id not in devices:
                        filepath = os.path.join(self.vault_dir, fname)
                        if os.path.isfile(filepath):
                            cnt, plats = self._scan_cookie_file(filepath)
                            os_guess = "Windows" if dev_id.startswith("win_") else ("macOS" if dev_id.startswith("mac_") else "PC")
                            devices[dev_id] = {
                                "id": dev_id,
                                "name": f"Device ({dev_id})",
                                "os": os_guess,
                                "hostname": dev_id,
                                "cookie_file": fname,
                                "cookie_count": cnt,
                                "platforms": plats,
                                "last_synced": datetime.fromtimestamp(os.path.getmtime(filepath)).strftime("%Y-%m-%d %H:%M:%S")
                            }
                            discovered_new = True
            if discovered_new:
                data["devices"] = devices
                with open(self.metadata_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
        except Exception:
            pass

        # Annotate with real-time status
        dev_list = []
        for dev_id, dev_info in devices.items():
            cookie_path = os.path.join(self.vault_dir, dev_info.get("cookie_file", ""))
            file_exists = os.path.exists(cookie_path) and os.path.getsize(cookie_path) > 10
            dev_list.append({
                "id": dev_id,
                "name": dev_info.get("name", dev_id),
                "os": dev_info.get("os", "Unknown"),
                "hostname": dev_info.get("hostname", ""),
                "cookie_file": dev_info.get("cookie_file", ""),
                "cookie_count": dev_info.get("cookie_count", 0),
                "platforms": dev_info.get("platforms", []),
                "last_synced": dev_info.get("last_synced", ""),
                "is_current_machine": (dev_id == self.current_device_id),
                "is_active_profile": (dev_id == active_id),
                "has_cookies": file_exists
            })

        # Ensure current machine is represented even before first sync
        if not any(d["id"] == self.current_device_id for d in dev_list):
            dev_list.insert(0, {
                "id": self.current_device_id,
                "name": self.get_default_device_name(),
                "os": "macOS" if sys.platform == "darwin" else ("Windows" if sys.platform == "win32" else "Linux"),
                "hostname": socket.gethostname(),
                "cookie_file": f"{self.current_device_id}_cookies.txt",
                "cookie_count": 0,
                "platforms": [],
                "last_synced": "Not yet synced",
                "is_current_machine": True,
                "is_active_profile": (self.current_device_id == active_id),
                "has_cookies": False
            })

        return {
            "vault_dir": self.vault_dir,
            "current_device_id": self.current_device_id,
            "active_profile_id": active_id,
            "devices": dev_list
        }

    def save_device_cookies(self, cookie_text: str, custom_device_name: Optional[str] = None) -> Dict[str, Any]:
        """Saves synced cookies under the current machine profile and activates them."""
        dev_id = self.current_device_id
        cookie_filename = f"{dev_id}_cookies.txt"
        target_path = os.path.join(self.vault_dir, cookie_filename)

        with open(target_path, "w", encoding="utf-8") as f:
            f.write(cookie_text)

        # Detect platforms & count valid cookies
        platforms_found = set()
        valid_count = 0
        for line in cookie_text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                valid_count += 1
                domain = parts[0].lower()
                if "youtube" in domain or "google" in domain:
                    platforms_found.add("YouTube")
                elif "instagram" in domain:
                    platforms_found.add("Instagram")
                elif "facebook" in domain:
                    platforms_found.add("Facebook")
                elif "tiktok" in domain:
                    platforms_found.add("TikTok")
                elif "twitter" in domain or "x.com" in domain:
                    platforms_found.add("Twitter/X")
                elif "reddit" in domain:
                    platforms_found.add("Reddit")

        os_name = "macOS" if sys.platform == "darwin" else ("Windows" if sys.platform == "win32" else "Linux")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Read existing metadata
        vault_data = {}
        if os.path.exists(self.metadata_file):
            try:
                with open(self.metadata_file, "r", encoding="utf-8") as f:
                    vault_data = json.load(f)
            except Exception:
                vault_data = {}

        devices = vault_data.get("devices", {})
        existing_name = devices.get(dev_id, {}).get("name")
        dev_name = custom_device_name or existing_name or self.get_default_device_name()

        devices[dev_id] = {
            "id": dev_id,
            "name": dev_name,
            "os": os_name,
            "hostname": socket.gethostname(),
            "cookie_file": cookie_filename,
            "cookie_count": valid_count,
            "platforms": sorted(list(platforms_found)),
            "last_synced": now_str
        }

        vault_data["devices"] = devices
        vault_data["active_profile_id"] = dev_id

        with open(self.metadata_file, "w", encoding="utf-8") as f:
            json.dump(vault_data, f, indent=2)

        # Update root cookies.txt for immediate extractor use
        active_cookie_file = os.path.join(self.base_download_dir, "cookies.txt")
        shutil.copy2(target_path, active_cookie_file)

        return {
            "device_id": dev_id,
            "device_name": dev_name,
            "cookie_count": valid_count,
            "platforms": sorted(list(platforms_found)),
            "saved_to": target_path
        }

    def set_active_profile(self, target_device_id: str) -> bool:
        """Switches the active downloader cookie set to match a specific device profile."""
        if not os.path.exists(self.metadata_file):
            return False

        with open(self.metadata_file, "r", encoding="utf-8") as f:
            vault_data = json.load(f)

        devices = vault_data.get("devices", {})
        if target_device_id not in devices:
            return False

        dev_info = devices[target_device_id]
        cookie_file = dev_info.get("cookie_file")
        src_path = os.path.join(self.vault_dir, cookie_file)

        if not os.path.exists(src_path):
            return False

        active_cookie_file = os.path.join(self.base_download_dir, "cookies.txt")
        shutil.copy2(src_path, active_cookie_file)

        vault_data["active_profile_id"] = target_device_id
        with open(self.metadata_file, "w", encoding="utf-8") as f:
            json.dump(vault_data, f, indent=2)

        return True

    def rename_device(self, device_id: str, new_name: str) -> bool:
        """Renames a device in the vault metadata."""
        if not os.path.exists(self.metadata_file):
            return False

        with open(self.metadata_file, "r", encoding="utf-8") as f:
            vault_data = json.load(f)

        devices = vault_data.get("devices", {})
        if device_id in devices:
            devices[device_id]["name"] = new_name.strip()
            with open(self.metadata_file, "w", encoding="utf-8") as f:
                json.dump(vault_data, f, indent=2)
            return True
        return False

    def export_vault_zip(self) -> str:
        """Packages the entire cookie vault folder into a portable zip file for other PCs."""
        zip_output = os.path.join(self.base_download_dir, "Velox_Cookie_Vault_Backup")
        out_path = shutil.make_archive(zip_output, 'zip', root_dir=self.base_download_dir, base_dir="cookie_vault")
        return out_path
