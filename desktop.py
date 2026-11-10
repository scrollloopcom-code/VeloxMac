#!/usr/bin/env python3
"""
LoopCatch Desktop Application Launcher.
Starts the local LoopCatch engine server (if not already running)
and opens a native dark glassmorphism desktop window.
"""

import sys
import os
import time
import socket
import threading
import webview
from version import APP_NAME, APP_FULL_NAME, APP_VERSION, COMPANY_NAME, AUTHOR

def is_port_in_use(port: int = 8899) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def start_server():
    import uvicorn
    from app import app
    uvicorn.run(app, host="127.0.0.1", port=8899, log_level="warning")

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base_dir)

    # Start FastAPI server in background thread if not already running
    if not is_port_in_use(8899):
        server_thread = threading.Thread(target=start_server, daemon=True)
        server_thread.start()
        # Wait up to 3 seconds for server to bind
        for _ in range(30):
            if is_port_in_use(8899):
                break
            time.sleep(0.1)

    # Open native desktop window (WebKit on macOS, Edge Chromium on Windows)
    win = webview.create_window(
        title=f"{APP_FULL_NAME} — {AUTHOR} (v{APP_VERSION})",
        url="http://127.0.0.1:8899",
        width=1180,
        height=820,
        min_size=(840, 580),
        text_select=True
    )

    # Use native platform GUI
    if sys.platform == "win32":
        webview.start(gui="edgechromium")
    else:
        webview.start()

if __name__ == "__main__":
    main()
