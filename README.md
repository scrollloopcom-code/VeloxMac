# LoopCatch — Next-Gen Media & IDM Downloader
**A Product of Scroll Loop • Developed by Lahiru_nk**

High-performance cross-platform (macOS & Windows) media extractor and multi-threaded segmented downloader with Multi-Device Cookie Vault and automatic in-app GitHub updates.

---

## ⚡️ Key Architecture & Capabilities

1. **Exact Media Extraction Pipeline (`yt-dlp` + Native FFmpeg)**:
   - Supports 4K UHD, 1440p, 1080p Full HD, 720p, 480p, 360p video streams.
   - Separate audio stream extraction: MP3 320 kbps (High Quality), MP3 192 kbps, and M4A/AAC lossless.
   - **Video Clip & Trim (Start - End Timestamp Cutting)**: Cut and download specific segments directly without downloading the entire file.
   - Native Apple Clang FFmpeg muxer at `/opt/homebrew/bin/ffmpeg` with lightning-fast stream copy and zero quality loss.
   - Anti-throttling fallback clients (`android`, `ios`, `web`, `mweb`) for YouTube, Instagram, TikTok, Facebook, Twitter/X, and Bilibili.

2. **Multi-Threaded HTTP Segmented Downloader (IDM Engine)**:
   - Parallel HTTP `Range: bytes=X-Y` requests (4x, 8x Turbo, 16x Max connections).
   - Multiplies download speeds on servers with single-thread speed limits.
   - Dynamic 8-segment visualizer in the UI showing individual connection chunk progress.
   - Pause, resume, and atomic file assembly.

3. **macOS Glassmorphism Web UI**:
   - Modern Apple Dark aesthetic (SF Pro font, frosted translucent cards, glowing neon accents).
   - Real-time 60fps bidirectional WebSocket telemetry (speed, percentage, ETA, chunks).
   - One-click "Reveal in macOS Finder" (`open -R`) and "Play Media" (`open`).

---

## 🚀 How to Run

In Terminal:
```bash
cd /Users/lahirunk/.gemini/antigravity/scratch/VeloxMac
./run.sh
```

Or run directly via python:
```bash
source .venv/bin/activate
python3 app:app
```

Then open `http://127.0.0.1:8899` in Safari or Chrome.
Downloads are automatically saved to `~/Downloads/LoopCatchDownloads`.
