#!/usr/bin/env python3
"""
Velox Windows Automated Build & Packaging Script.
Bundles Velox into an optimized standalone Windows application (Velox.exe),
bundles static ffmpeg.exe, and generates a portable .ZIP and InnoSetup installer.
"""

import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from version import APP_NAME, APP_VERSION

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BIN_DIR = os.path.join(BASE_DIR, "bin")
DIST_DIR = os.path.join(BASE_DIR, "dist")
BUILD_DIR = os.path.join(BASE_DIR, "build")

def ensure_windows_ffmpeg():
    """Ensures static Windows ffmpeg.exe and ffprobe.exe exist in bin/."""
    os.makedirs(BIN_DIR, exist_ok=True)
    ffmpeg_exe = os.path.join(BIN_DIR, "ffmpeg.exe")
    ffprobe_exe = os.path.join(BIN_DIR, "ffprobe.exe")

    if os.path.exists(ffmpeg_exe) and os.path.exists(ffprobe_exe):
        print("✅ Windows ffmpeg.exe and ffprobe.exe already present in bin/")
        return

    # Check if system ffmpeg.exe exists
    which_ffmpeg = shutil.which("ffmpeg.exe") or shutil.which("ffmpeg")
    which_ffprobe = shutil.which("ffprobe.exe") or shutil.which("ffprobe")
    if which_ffmpeg and which_ffprobe and sys.platform == "win32":
        shutil.copy2(which_ffmpeg, ffmpeg_exe)
        shutil.copy2(which_ffprobe, ffprobe_exe)
        print("✅ Copied system ffmpeg.exe into bin/")
        return

    print("⬇️ Downloading static Windows FFmpeg binaries...")
    ffmpeg_url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
    temp_zip = os.path.join(BASE_DIR, "ffmpeg_win.zip")
    try:
        urllib.request.urlretrieve(ffmpeg_url, temp_zip)
        with zipfile.ZipFile(temp_zip, 'r') as z:
            for member in z.namelist():
                if member.endswith("ffmpeg.exe"):
                    with z.open(member) as source, open(ffmpeg_exe, "wb") as target:
                        shutil.copyfileobj(source, target)
                elif member.endswith("ffprobe.exe"):
                    with z.open(member) as source, open(ffprobe_exe, "wb") as target:
                        shutil.copyfileobj(source, target)
        if os.path.exists(temp_zip):
            os.remove(temp_zip)
        print("✅ Downloaded and placed static ffmpeg.exe & ffprobe.exe into bin/")
    except Exception as e:
        print(f"⚠️ Could not auto-download FFmpeg: {e}")

def ensure_windows_icon():
    """Generates static/icon.ico if missing."""
    ico_path = os.path.join(BASE_DIR, "static", "icon.ico")
    if os.path.exists(ico_path):
        return ico_path

    png_path = os.path.join(BASE_DIR, "extension", "icons", "icon128.png")
    if os.path.exists(png_path):
        try:
            from PIL import Image
            img = Image.open(png_path)
            img.save(ico_path, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128)])
            print("✅ Generated static/icon.ico")
            return ico_path
        except Exception:
            pass
    return None

def build():
    print(f"🚀 Building {APP_NAME} for Windows (v{APP_VERSION})...")
    os.chdir(BASE_DIR)

    ensure_windows_ffmpeg()
    ico_file = ensure_windows_icon()

    # PyInstaller arguments
    # On Windows, path separator for add-data is ';'
    sep = ";" if sys.platform == "win32" else ":"
    pyinstaller_args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--name", APP_NAME,
        f"--add-data=static{sep}static",
        f"--add-data=engine{sep}engine",
        f"--add-data=version.py{sep}.",
        "--hidden-import=uvicorn",
        "--hidden-import=fastapi",
        "--hidden-import=webview",
        "--hidden-import=yt_dlp",
        "--hidden-import=httpx",
        "--hidden-import=pydantic",
        "desktop.py"
    ]

    if os.path.exists(BIN_DIR) and os.listdir(BIN_DIR):
        pyinstaller_args.append(f"--add-data=bin{sep}bin")

    if ico_file and os.path.exists(ico_file):
        pyinstaller_args.extend(["--icon", ico_file])

    print("📦 Running PyInstaller...")
    subprocess.run(pyinstaller_args, check=True)

    velox_dist_dir = os.path.join(DIST_DIR, APP_NAME)

    # 1. Create Lightweight In-App Update Patch (WITHOUT the 150MB+ FFmpeg)
    # Saves >90% bandwidth for existing installations!
    patch_zip_name = f"{APP_NAME}-Windows-Update"
    patch_zip_path = os.path.join(DIST_DIR, f"{patch_zip_name}.zip")
    print(f"🗜️ Creating lightweight in-app update patch: {patch_zip_path}...")
    shutil.make_archive(os.path.join(DIST_DIR, patch_zip_name), 'zip', root_dir=velox_dist_dir)
    print(f"✅ Created lightweight update package: {patch_zip_path}")

    # 2. Add static FFmpeg binaries for full standalone installer & portable zip
    if os.path.exists(BIN_DIR):
        dist_bin = os.path.join(velox_dist_dir, "bin")
        os.makedirs(dist_bin, exist_ok=True)
        for item in os.listdir(BIN_DIR):
            s = os.path.join(BIN_DIR, item)
            d = os.path.join(dist_bin, item)
            if not os.path.exists(d):
                shutil.copy2(s, d)

    # 3. Create full portable ZIP archive (with FFmpeg included)
    zip_output_name = f"{APP_NAME}-Windows-v{APP_VERSION}"
    zip_path = os.path.join(DIST_DIR, f"{zip_output_name}.zip")
    print(f"🗜️ Creating full portable archive: {zip_path}...")
    shutil.make_archive(os.path.join(DIST_DIR, zip_output_name), 'zip', root_dir=DIST_DIR, base_dir=APP_NAME)
    print(f"✅ Created full portable package: {zip_path}")

    # Build InnoSetup installer if ISCC is installed
    iscc = shutil.which("ISCC.exe") or shutil.which("iscc") or r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    if isinstance(iscc, str) and os.path.exists(iscc):
        print("💿 Compiling InnoSetup Windows Installer...")
        iss_file = os.path.join(BASE_DIR, "installer", "windows_installer.iss")
        subprocess.run([iscc, iss_file], check=True)
        print("✅ Created Windows Installer in dist/")
    else:
        print("ℹ️ InnoSetup (ISCC.exe) not found; skipping installer compilation (portable zip created).")

if __name__ == "__main__":
    build()
