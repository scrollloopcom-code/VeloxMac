#!/usr/bin/env python3
"""
Automated DMG and .app Builder for VeloxMac.
Generates high-res Apple icns icons, sets up VeloxMac.app bundle,
and packages a drag-to-Applications .dmg installer.
"""

import os
import sys
import shutil
import subprocess
import AppKit

def build():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    build_dir = os.path.join(base_dir, "build")
    dist_dir = os.path.join(base_dir, "dist")
    os.makedirs(build_dir, exist_ok=True)
    os.makedirs(dist_dir, exist_ok=True)

    print("🎨 Generating macOS AppIcon.icns...")
    iconset_dir = os.path.join(build_dir, "VeloxMac.iconset")
    os.makedirs(iconset_dir, exist_ok=True)

    icon_sizes = [
        ("icon_16x16.png", 16),
        ("icon_16x16@2x.png", 32),
        ("icon_32x32.png", 32),
        ("icon_32x32@2x.png", 64),
        ("icon_128x128.png", 128),
        ("icon_128x128@2x.png", 256),
        ("icon_256x256.png", 256),
        ("icon_256x256@2x.png", 512),
        ("icon_512x512.png", 512),
        ("icon_512x512@2x.png", 1024),
    ]

    for filename, size in icon_sizes:
        img = AppKit.NSImage.alloc().initWithSize_((size, size))
        img.lockFocus()
        bg_rect = AppKit.NSMakeRect(size*0.05, size*0.05, size*0.9, size*0.9)
        bg_path = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(bg_rect, size*0.2, size*0.2)
        AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.04, 0.06, 0.1, 1.0).setFill()
        bg_path.fill()
        AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.0, 0.95, 1.0, 0.8).setStroke()
        bg_path.setLineWidth_(size * 0.04)
        bg_path.stroke()

        bolt = AppKit.NSBezierPath.bezierPath()
        bolt.moveToPoint_((size * 0.52, size * 0.82))
        bolt.lineToPoint_((size * 0.28, size * 0.45))
        bolt.lineToPoint_((size * 0.48, size * 0.45))
        bolt.lineToPoint_((size * 0.44, size * 0.18))
        bolt.lineToPoint_((size * 0.72, size * 0.55))
        bolt.lineToPoint_((size * 0.52, size * 0.55))
        bolt.closePath()
        AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.0, 0.95, 1.0, 1.0).setFill()
        bolt.fill()
        img.unlockFocus()
        
        rep = AppKit.NSBitmapImageRep.imageRepWithData_(img.TIFFRepresentation())
        png_data = rep.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, None)
        png_data.writeToFile_atomically_(os.path.join(iconset_dir, filename), True)

    icns_path = os.path.join(build_dir, "AppIcon.icns")
    subprocess.run(["iconutil", "-c", "icns", iconset_dir, "-o", icns_path], check=True)

    print("📦 Assembling VeloxMac.app...")
    app_dir = os.path.join(dist_dir, "VeloxMac.app")
    if os.path.exists(app_dir):
        shutil.rmtree(app_dir)

    macos_dir = os.path.join(app_dir, "Contents", "MacOS")
    res_dir = os.path.join(app_dir, "Contents", "Resources")
    os.makedirs(macos_dir, exist_ok=True)
    os.makedirs(res_dir, exist_ok=True)

    shutil.copyfile(icns_path, os.path.join(res_dir, "AppIcon.icns"))

    plist = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>VeloxMac</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundleIdentifier</key>
    <string>com.velox.mac</string>
    <key>CFBundleName</key>
    <string>VeloxMac</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0.0</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
"""
    with open(os.path.join(app_dir, "Contents", "Info.plist"), "w") as f:
        f.write(plist)

    launcher = f"""#!/bin/bash
PROJECT_DIR="{base_dir}"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python3"

cd "$PROJECT_DIR" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

exec "$PYTHON_BIN" desktop.py
"""
    launcher_path = os.path.join(macos_dir, "VeloxMac")
    with open(launcher_path, "w") as f:
        f.write(launcher)
    os.chmod(launcher_path, 0o755)

    print("💿 Building VeloxMac-v1.0.dmg...")
    dmg_stage = os.path.join(dist_dir, "dmg_stage")
    if os.path.exists(dmg_stage):
        shutil.rmtree(dmg_stage)
    os.makedirs(dmg_stage)

    shutil.copytree(app_dir, os.path.join(dmg_stage, "VeloxMac.app"))
    os.symlink("/Applications", os.path.join(dmg_stage, "Applications"))

    dmg_output = os.path.expanduser("~/Downloads/VeloxDownloads/VeloxMac-v1.0.dmg")
    if os.path.exists(dmg_output):
        os.remove(dmg_output)

    subprocess.run([
        "hdiutil", "create",
        "-volname", "VeloxMac",
        "-srcfolder", dmg_stage,
        "-ov",
        "-format", "UDZO",
        dmg_output
    ], check=True)

    print(f"✅ Success! DMG created at: {dmg_output}")

    # Also build VeloxMac.zip for seamless 1-click in-app auto-updating
    zip_output = os.path.join(dist_dir, "VeloxMac.zip")
    print(f"🗜️ Creating {zip_output} for in-app auto-updater...")
    shutil.make_archive(os.path.join(dist_dir, "VeloxMac"), "zip", root_dir=dist_dir, base_dir="VeloxMac.app")
    print(f"✅ Created in-app updater package: {zip_output}")

if __name__ == "__main__":
    build()
