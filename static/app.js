// ==========================================================================
// VeloxMac Frontend Controller
// ==========================================================================

const state = {
  jobs: {},
  currentInspection: null,
  activeFormatType: 'video',
  selectedFormat: null,
  connections: 8,
  activeTab: 'active',
  ws: null
};

// DOM References
const inspectForm = document.getElementById('inspectForm');
const urlInput = document.getElementById('urlInput');
const inspectBtn = document.getElementById('inspectBtn');
const pasteBtn = document.getElementById('pasteBtn');
const inspectResults = document.getElementById('inspectResults');
const activeJobsContainer = document.getElementById('activeJobsContainer');
const completedJobsContainer = document.getElementById('completedJobsContainer');
const activeBadge = document.getElementById('activeBadge');
const completedBadge = document.getElementById('completedBadge');
const wsStatus = document.getElementById('wsStatus');
const ffmpegStatus = document.getElementById('ffmpegStatus');
const toastContainer = document.getElementById('toastContainer');

// Initialize
document.addEventListener('DOMContentLoaded', () => {
  initWebSocket();
  checkSystemStatus();
  checkCookieStatus();
  setupEventListeners();
  setupTrimmerStudioListeners();
  setupJobActionDelegation();
});

function setupEventListeners() {
  // Paste button
  pasteBtn.addEventListener('click', async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (text) {
        urlInput.value = text.trim();
        urlInput.focus();
        showToast('Pasted link from clipboard');
      }
    } catch (e) {
      showToast('Clipboard access denied, please paste manually');
    }
  });

  // URL Inspect Form
  inspectForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const url = urlInput.value.trim();
    if (!url) return;

    setLoading(true);
    inspectResults.style.display = 'none';

    try {
      const resp = await fetch('/api/inspect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url })
      });
      const data = await resp.json();

      if (!resp.ok) {
        throw new Error(data.detail || 'Failed to analyze URL');
      }

      state.currentInspection = data;
      renderInspectionResults(data);
    } catch (err) {
      const errMsg = String(err.message || '');
      if (errMsg.toLowerCase().includes('bot') || errMsg.includes('Sign in to confirm')) {
        renderBotGuardError(errMsg, url);
      } else {
        showToast(`Error: ${errMsg}`, 'error');
      }
    } finally {
      setLoading(false);
    }
  });

  // Tab buttons
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.activeTab = btn.dataset.tab;

      if (state.activeTab === 'active') {
        activeJobsContainer.style.display = 'flex';
        completedJobsContainer.style.display = 'none';
      } else {
        activeJobsContainer.style.display = 'none';
        completedJobsContainer.style.display = 'flex';
      }
    });
  });

  // Open Downloads Folder
  document.getElementById('openDownloadsFolder').addEventListener('click', () => {
    showToast('Downloads folder: ~/Downloads/VeloxDownloads');
  });

  const openExtFolderBtn = document.getElementById('openExtFolderBtn');
  if (openExtFolderBtn) {
    openExtFolderBtn.addEventListener('click', async () => {
      try {
        await fetch('/api/extension/reveal', { method: 'POST' });
        showToast('📂 Extension folder opened in Finder! Drag into chrome://extensions');
      } catch (e) {
        showToast('Failed to open Finder', 'error');
      }
    });
  }

  // Cookie Modal Handlers
  const cookieModal = document.getElementById('cookieModal');
  const cookieStatusBtn = document.getElementById('cookieStatusBtn');
  const closeCookieModal = document.getElementById('closeCookieModal');
  const selectCookieFileBtn = document.getElementById('selectCookieFileBtn');
  const cookieFileInput = document.getElementById('cookieFileInput');
  const saveCookieTextBtn = document.getElementById('saveCookieTextBtn');
  const cookieTextInput = document.getElementById('cookieTextInput');
  const clearCookieBtn = document.getElementById('clearCookieBtn');

  cookieStatusBtn.addEventListener('click', () => {
    cookieModal.style.display = 'flex';
    checkCookieStatus();
  });

  closeCookieModal.addEventListener('click', () => {
    cookieModal.style.display = 'none';
  });

  selectCookieFileBtn.addEventListener('click', () => {
    cookieFileInput.click();
  });

  cookieFileInput.addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = async (evt) => {
      await uploadCookieText(evt.target.result);
      cookieFileInput.value = '';
    };
    reader.readAsText(file);
  });

  saveCookieTextBtn.addEventListener('click', async () => {
    const text = cookieTextInput.value.trim();
    if (!text) {
      showToast('Please paste cookie text first', 'error');
      return;
    }
    await uploadCookieText(text);
    cookieTextInput.value = '';
  });

  clearCookieBtn.addEventListener('click', async () => {
    try {
      await fetch('/api/cookies', { method: 'DELETE' });
      showToast('Cookies cleared');
      checkCookieStatus();
    } catch (e) {
      showToast('Failed to clear cookies', 'error');
    }
  });
}

// ==========================================================================
// Time Helpers & Trimmer Studio Controller
// ==========================================================================
function parseTimeSeconds(str) {
  if (!str) return 0;
  const parts = str.trim().split(':').map(Number);
  if (parts.some(isNaN)) return 0;
  if (parts.length === 1) return parts[0];
  if (parts.length === 2) return parts[0] * 60 + parts[1];
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
  return 0;
}

function formatSeconds(sec) {
  if (sec <= 0) return '00:00:00';
  const s = Math.floor(sec % 60);
  const m = Math.floor((sec / 60) % 60);
  const h = Math.floor(sec / 3600);
  const pad = n => String(n).padStart(2, '0');
  return `${pad(h)}:${pad(m)}:${pad(s)}`;
}

let currentStudioInfo = null;
let studioIsPlayingClip = false;

function setupTrimmerStudioListeners() {
  const modal = document.getElementById('trimmerStudioModal');
  const closeBtn = document.getElementById('closeTrimmerStudioBtn');
  const cancelBtn = document.getElementById('cancelTrimmerStudioBtn');
  const player = document.getElementById('studioVideoPlayer');
  const loading = document.getElementById('studioVideoLoading');

  const startSlider = document.getElementById('studioStartSlider');
  const endSlider = document.getElementById('studioEndSlider');
  const selectionStrip = document.getElementById('studioSelectionStrip');
  const playheadCursor = document.getElementById('studioPlayheadCursor');
  const playheadTime = document.getElementById('studioPlayheadTime');
  const totalDuration = document.getElementById('studioTotalDuration');

  const startChipTime = document.getElementById('startChipTime');
  const playheadChipTime = document.getElementById('playheadChipTime');
  const endChipTime = document.getElementById('endChipTime');

  const startInput = document.getElementById('studioStartInput');
  const endInput = document.getElementById('studioEndInput');
  const clipDurationDisplay = document.getElementById('studioClipDurationDisplay');

  const setStartBtn = document.getElementById('studioSetStartBtn');
  const setEndBtn = document.getElementById('studioSetEndBtn');
  const back5Btn = document.getElementById('studioBack5Btn');
  const fwd5Btn = document.getElementById('studioFwd5Btn');
  const playClipBtn = document.getElementById('studioPlayClipBtn');
  const resetBtn = document.getElementById('studioResetBtn');

  const zeroStartBtn = document.getElementById('studioZeroStartBtn');
  const maxEndBtn = document.getElementById('studioMaxEndBtn');

  const saveTrimToCardBtn = document.getElementById('saveTrimToCardBtn');
  const applyAndDownloadNowBtn = document.getElementById('applyAndDownloadNowBtn');

  if (!modal) return;

  function getDuration() {
    return (currentStudioInfo && currentStudioInfo.duration) ? Math.max(1, currentStudioInfo.duration) : (player && player.duration ? player.duration : 100);
  }

  function updateVisualTrack() {
    const dur = getDuration();
    const s = parseFloat(startSlider.value) || 0;
    const e = parseFloat(endSlider.value) || dur;
    const leftPct = (s / dur) * 100;
    const widthPct = Math.max(0, ((e - s) / dur) * 100);

    if (selectionStrip) {
      selectionStrip.style.left = `${leftPct}%`;
      selectionStrip.style.width = `${widthPct}%`;
    }

    if (startChipTime) startChipTime.textContent = formatSeconds(s);
    if (endChipTime) endChipTime.textContent = formatSeconds(e);
    if (startInput) startInput.value = formatSeconds(s);
    if (endInput) endInput.value = formatSeconds(e);
    if (clipDurationDisplay) clipDurationDisplay.textContent = formatSeconds(Math.max(0, e - s));
  }

  function closeModal() {
    if (player) {
      player.pause();
      player.removeAttribute('src');
      player.load();
    }
    studioIsPlayingClip = false;
    modal.style.display = 'none';
  }

  if (closeBtn) closeBtn.addEventListener('click', closeModal);
  if (cancelBtn) cancelBtn.addEventListener('click', closeModal);

  // Sliders
  if (startSlider && endSlider) {
    startSlider.addEventListener('input', () => {
      const dur = getDuration();
      let s = parseFloat(startSlider.value);
      let e = parseFloat(endSlider.value);
      if (s >= e) {
        s = Math.max(0, e - 0.5);
        startSlider.value = String(s);
      }
      updateVisualTrack();
      if (player && !isNaN(player.duration) && player.duration > 0) {
        player.currentTime = s;
      }
    });

    endSlider.addEventListener('input', () => {
      const dur = getDuration();
      let s = parseFloat(startSlider.value);
      let e = parseFloat(endSlider.value);
      if (e <= s) {
        e = Math.min(dur, s + 0.5);
        endSlider.value = String(e);
      }
      updateVisualTrack();
      if (player && !isNaN(player.duration) && player.duration > 0) {
        player.currentTime = e;
      }
    });
  }

  // Timecode Inputs
  if (startInput) {
    startInput.addEventListener('change', () => {
      const dur = getDuration();
      let s = parseTimeSeconds(startInput.value);
      let e = parseFloat(endSlider.value);
      s = Math.max(0, Math.min(s, e - 0.5));
      startSlider.value = String(s);
      updateVisualTrack();
    });
  }

  if (endInput) {
    endInput.addEventListener('change', () => {
      const dur = getDuration();
      let s = parseFloat(startSlider.value);
      let e = parseTimeSeconds(endInput.value);
      e = Math.max(s + 0.5, Math.min(e, dur));
      endSlider.value = String(e);
      updateVisualTrack();
    });
  }

  if (zeroStartBtn) {
    zeroStartBtn.addEventListener('click', () => {
      startSlider.value = '0';
      updateVisualTrack();
    });
  }

  if (maxEndBtn) {
    maxEndBtn.addEventListener('click', () => {
      endSlider.value = String(getDuration());
      updateVisualTrack();
    });
  }

  // Quick Action Buttons
  if (setStartBtn) {
    setStartBtn.addEventListener('click', () => {
      const cur = player ? player.currentTime : 0;
      let e = parseFloat(endSlider.value);
      if (cur < e) {
        startSlider.value = String(cur);
        updateVisualTrack();
        showToast(`✂️ Set Start [IN] to ${formatSeconds(cur)}`);
      } else {
        showToast('Start point must be before End point', 'error');
      }
    });
  }

  if (setEndBtn) {
    setEndBtn.addEventListener('click', () => {
      const cur = player ? player.currentTime : 0;
      let s = parseFloat(startSlider.value);
      if (cur > s) {
        endSlider.value = String(cur);
        updateVisualTrack();
        showToast(`✂️ Set End [OUT] to ${formatSeconds(cur)}`);
      } else {
        showToast('End point must be after Start point', 'error');
      }
    });
  }

  if (back5Btn) {
    back5Btn.addEventListener('click', () => {
      if (player) player.currentTime = Math.max(0, player.currentTime - 5);
    });
  }

  if (fwd5Btn) {
    fwd5Btn.addEventListener('click', () => {
      const dur = getDuration();
      if (player) player.currentTime = Math.min(dur, player.currentTime + 5);
    });
  }

  if (playClipBtn) {
    playClipBtn.addEventListener('click', () => {
      if (!player) return;
      const s = parseFloat(startSlider.value);
      studioIsPlayingClip = true;
      player.currentTime = s;
      player.play().catch(() => {});
      showToast('▶️ Playing selected clip range...');
    });
  }

  if (resetBtn) {
    resetBtn.addEventListener('click', () => {
      const dur = getDuration();
      startSlider.value = '0';
      endSlider.value = String(dur);
      updateVisualTrack();
      if (player) player.currentTime = 0;
      showToast('🔄 Reset to full video');
    });
  }

  // Video Events
  if (player) {
    player.addEventListener('loadstart', () => {
      if (loading) loading.style.display = 'flex';
    });
    player.addEventListener('canplay', () => {
      if (loading) loading.style.display = 'none';
    });
    player.addEventListener('waiting', () => {
      if (loading) loading.style.display = 'flex';
    });
    player.addEventListener('playing', () => {
      if (loading) loading.style.display = 'none';
    });
    player.addEventListener('timeupdate', () => {
      const cur = player.currentTime;
      const dur = getDuration();
      if (playheadTime) playheadTime.textContent = formatSeconds(cur);
      if (playheadChipTime) playheadChipTime.textContent = formatSeconds(cur);
      if (playheadCursor) {
        const curPct = Math.min(100, Math.max(0, (cur / dur) * 100));
        playheadCursor.style.left = `${curPct}%`;
      }

      if (studioIsPlayingClip) {
        const e = parseFloat(endSlider.value);
        if (cur >= e) {
          player.pause();
          studioIsPlayingClip = false;
        }
      }
    });
  }

  // Save to Downloader Card
  if (saveTrimToCardBtn) {
    saveTrimToCardBtn.addEventListener('click', () => {
      const sStr = startInput.value;
      const eStr = endInput.value;
      const cardToggle = document.getElementById('enableClipToggle');
      const cardStart = document.getElementById('clipStartInput');
      const cardEnd = document.getElementById('clipEndInput');
      const cardControls = document.getElementById('trimmerControls');
      const cardDuration = document.getElementById('clipDurationText');

      if (cardToggle) cardToggle.checked = true;
      if (cardControls) cardControls.style.display = 'grid';
      if (cardStart) cardStart.value = sStr;
      if (cardEnd) cardEnd.value = eStr;
      if (cardDuration) {
        const diff = Math.max(0, parseTimeSeconds(eStr) - parseTimeSeconds(sStr));
        cardDuration.textContent = formatSeconds(diff);
      }

      showToast(`✂️ Clip applied: ${sStr} - ${eStr}`);
      closeModal();
    });
  }

  // Apply & Download Now
  if (applyAndDownloadNowBtn) {
    applyAndDownloadNowBtn.addEventListener('click', () => {
      const sStr = startInput.value;
      const eStr = endInput.value;
      const cardToggle = document.getElementById('enableClipToggle');
      const cardStart = document.getElementById('clipStartInput');
      const cardEnd = document.getElementById('clipEndInput');
      const cardControls = document.getElementById('trimmerControls');

      if (cardToggle) cardToggle.checked = true;
      if (cardControls) cardControls.style.display = 'grid';
      if (cardStart) cardStart.value = sStr;
      if (cardEnd) cardEnd.value = eStr;

      closeModal();

      const startDownloadBtn = document.getElementById('startDownloadBtn');
      if (startDownloadBtn) {
        startDownloadBtn.click();
      }
    });
  }
}

function openTrimmerStudio(info) {
  currentStudioInfo = info;
  const modal = document.getElementById('trimmerStudioModal');
  const title = document.getElementById('studioModalTitle');
  const totalDuration = document.getElementById('studioTotalDuration');
  const player = document.getElementById('studioVideoPlayer');
  const loading = document.getElementById('studioVideoLoading');
  const startSlider = document.getElementById('studioStartSlider');
  const endSlider = document.getElementById('studioEndSlider');

  const dur = (info && info.duration) ? Math.max(1, info.duration) : 100;
  if (title) title.textContent = `Velox Trimmer Studio — ${info.title || 'Video'}`;
  if (totalDuration) totalDuration.textContent = info.duration_str || formatSeconds(dur);

  const cardStart = document.getElementById('clipStartInput');
  const cardEnd = document.getElementById('clipEndInput');
  let s = (cardStart && cardStart.value) ? parseTimeSeconds(cardStart.value) : 0;
  let e = (cardEnd && cardEnd.value) ? parseTimeSeconds(cardEnd.value) : dur;
  if (e <= 0 || e > dur) e = dur;
  if (s >= e) s = 0;

  if (startSlider && endSlider) {
    startSlider.min = '0';
    startSlider.max = String(dur);
    startSlider.step = '0.5';
    startSlider.value = String(s);

    endSlider.min = '0';
    endSlider.max = String(dur);
    endSlider.step = '0.5';
    endSlider.value = String(e);

    // Sync track visual
    startSlider.dispatchEvent(new Event('input'));
  }

  // Load authenticated preview stream
  if (player) {
    if (info.preview_stream_url) {
      if (loading) loading.style.display = 'flex';
      player.src = `/api/stream/proxy?url=${encodeURIComponent(info.preview_stream_url)}`;
      player.load();
      player.currentTime = s;
    } else {
      if (loading) loading.style.display = 'none';
      player.removeAttribute('src');
    }
  }

  if (modal) modal.style.display = 'flex';
}

async function uploadCookieText(text) {
  try {
    const resp = await fetch('/api/cookies', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cookie_text: text })
    });
    if (resp.ok) {
      showToast('✅ Cookies applied successfully! YouTube BotGuard bypassed.');
      checkCookieStatus();
    } else {
      const err = await resp.json();
      showToast(`Error: ${err.detail || 'Failed to save cookies'}`, 'error');
    }
  } catch (e) {
    showToast(`Error: ${e.message}`, 'error');
  }
}

let pendingRetryUrl = null;

function renderBotGuardError(errorMsg, failedUrl) {
  pendingRetryUrl = failedUrl;
  inspectResults.style.display = 'block';
  inspectResults.innerHTML = `
    <div class="botguard-alert-box">
      <div class="botguard-alert-title">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
        <span>YouTube Sign-In Required (BotGuard)</span>
      </div>
      <p class="botguard-alert-desc">
        YouTube requires authentication for this link. Use the <strong>VeloxMac Browser Extension</strong> to sync cookies directly from your browser, or import a cookies.txt file!
      </p>
      <div class="botguard-action-row">
        <button type="button" class="sync-large-btn" id="inlineSyncBtn" style="margin: 0; padding: 10px 20px;">
          🍪 Open Cookies & Extension Manager
        </button>
      </div>
    </div>
  `;

  document.getElementById('inlineSyncBtn').addEventListener('click', () => {
    document.getElementById('cookieModal').style.display = 'flex';
  });
}

async function checkCookieStatus() {
  try {
    const resp = await fetch('/api/cookies/status');
    const data = await resp.json();
    const dot = document.getElementById('cookieDot');
    const modalDot = document.getElementById('modalCookieDot');
    const label = document.getElementById('cookieLabel');
    const statusText = document.getElementById('currentStatusText');
    const clearBtn = document.getElementById('clearCookieBtn');

    if (data.has_cookies) {
      if (dot) {
        dot.style.background = 'var(--accent-green)';
        dot.style.boxShadow = '0 0 8px var(--accent-green)';
      }
      if (modalDot) {
        modalDot.style.background = 'var(--accent-green)';
        modalDot.style.boxShadow = '0 0 8px var(--accent-green)';
      }
      if (label) label.textContent = 'Cookies: Active';
      if (statusText) statusText.innerHTML = `✅ <strong>YouTube Session Active</strong> &bull; Size: ${(data.size / 1024).toFixed(1)} KB (BotGuard Bypassed)`;
      if (clearBtn) clearBtn.style.display = 'inline-block';
    } else {
      if (dot) {
        dot.style.background = '#f39c12';
        dot.style.boxShadow = 'none';
      }
      if (modalDot) {
        modalDot.style.background = '#f39c12';
        modalDot.style.boxShadow = 'none';
      }
      if (label) label.textContent = 'Cookies: None';
      if (statusText) statusText.innerHTML = '⚠️ <strong>No session configured</strong> (YouTube BotGuard challenge may block requests)';
      if (clearBtn) clearBtn.style.display = 'none';
    }
  } catch (e) {}
}

function setLoading(isLoading) {
  const btnText = inspectBtn.querySelector('.btn-text');
  const spinner = inspectBtn.querySelector('.spinner');
  if (isLoading) {
    btnText.style.display = 'none';
    spinner.style.display = 'inline-block';
    inspectBtn.disabled = true;
  } else {
    btnText.style.display = 'inline';
    spinner.style.display = 'none';
    inspectBtn.disabled = false;
  }
}

async function checkSystemStatus() {
  try {
    const res = await fetch('/api/system');
    const data = await res.json();
    if (data.ffmpeg_available) {
      ffmpegStatus.innerHTML = '<span class="dot active"></span> FFmpeg Active';
    } else {
      ffmpegStatus.innerHTML = '<span class="dot" style="background:#e74c3c"></span> FFmpeg Missing';
    }
  } catch (e) {
    // ignore
  }
}

// Render Inspection Results Drawer
function renderInspectionResults(data) {
  inspectResults.innerHTML = '';
  inspectResults.style.display = 'flex';

  if (data.type === 'media') {
    renderMediaInspection(data.info);
  } else {
    renderDirectInspection(data.info);
  }
}

function renderMediaInspection(info) {
  state.activeFormatType = 'video';
  state.selectedFormat = info.video_options[0] || null;

  const html = `
    <div class="media-summary-header">
      <div class="media-thumb-box">
        <img src="${info.thumbnail || ''}" alt="Thumbnail" onerror="this.src='data:image/svg+xml,<svg xmlns=\'http://www.w3.org/2000/svg\' viewBox=\'0 0 24 24\' fill=\'%23555\'><rect width=\'24\' height=\'24\'/></svg>'">
        ${info.duration ? `<span class="thumb-duration">${info.duration_str}</span>` : ''}
      </div>
      <div class="media-meta-details">
        <h3 class="media-meta-title">${escapeHtml(info.title)}</h3>
        <p class="media-meta-uploader">${escapeHtml(info.uploader)} &bull; ${info.extractor}</p>
      </div>
    </div>

    <div class="format-selection-container">
      <div class="format-tabs">
        <button class="format-tab-btn active" id="tabVideo">🎬 Video (MP4)</button>
        <button class="format-tab-btn" id="tabAudio">🎵 Audio Only (MP3/M4A)</button>
      </div>

      <div class="format-grid" id="formatGrid"></div>
    </div>

    <!-- Video Trimmer / Clipper Section -->
    <div class="clip-trimmer-section">
      <div class="trimmer-toggle-row">
        <label class="switch-container">
          <input type="checkbox" id="enableClipToggle">
          <span class="switch-slider"></span>
        </label>
        <div class="trimmer-title-group">
          <span class="trimmer-title">✂️ Clip / Trim Video (Download Specific Part)</span>
          <span class="trimmer-sub">Cut exact start & end timestamps without downloading the full video</span>
        </div>
        <button type="button" class="open-trimmer-studio-btn" id="openTrimmerStudioBtn">
          🎬 Open Trimmer Studio
        </button>
      </div>

      <div class="trimmer-inputs-wrapper" id="trimmerControls" style="display: none;">
        <!-- Embedded Interactive Preview Player (Video + Audio) -->
        <div class="clip-preview-container">
          <div class="preview-media-box">
            ${info.preview_stream_url ? `
              <video id="clipHtmlVideo" controls playsinline preload="none" data-src="/api/stream/proxy?url=${encodeURIComponent(info.preview_stream_url)}" poster="${info.thumbnail}"></video>
            ` : `
              <div class="preview-placeholder">
                <img src="${info.thumbnail}" alt="Thumbnail">
                <span class="preview-note">Click "🎬 Open Trimmer Studio" to scrub and set cut points</span>
              </div>
            `}
          </div>

          <!-- Scrubbing Bar & Playhead Position -->
          <div class="scrubber-card">
            <div class="scrubber-top-row">
              <span class="scrub-label">🎯 Interactive Timeline Scrub (Audio & Video):</span>
              <span class="scrub-time" id="scrubberTimeDisplay">00:00:00 / ${info.duration_str || '00:00'}</span>
            </div>
            <input type="range" class="clip-range-slider" id="clipTimelineSlider" min="0" max="${info.duration || 100}" step="1" value="0">
            <div class="scrub-action-buttons">
              <button type="button" class="quick-set-btn" id="setStartFromSliderBtn">
                ⏱️ Set Start (<span id="startSliderLabel">00:00</span>)
              </button>
              <button type="button" class="quick-set-btn secondary" id="seekMiddleBtn">
                ⚡ Jump Midpoint
              </button>
              <button type="button" class="quick-set-btn" id="setEndFromSliderBtn">
                ⏱️ Set End (<span id="endSliderLabel">00:00</span>)
              </button>
            </div>
          </div>
        </div>

        <div class="time-input-box">
          <label>Start Timestamp</label>
          <div class="time-field-row">
            <input type="text" id="clipStartInput" placeholder="00:00:00" value="00:00:00">
            <button type="button" class="quick-time-btn" id="setStartZeroBtn">0:00</button>
          </div>
        </div>

        <div class="time-input-box">
          <label>End Timestamp</label>
          <div class="time-field-row">
            <input type="text" id="clipEndInput" placeholder="${info.duration_str || '00:00:00'}" value="${info.duration_str || '00:00:00'}">
            <button type="button" class="quick-time-btn" id="setEndMaxBtn">End</button>
          </div>
        </div>

        <div class="clip-summary-box">
          <span class="summary-label">Selected Clip Length:</span>
          <span class="summary-duration" id="clipDurationText">${info.duration_str || '00:00:00'}</span>
          <span class="summary-hint">⚡ Fast keyframe stream-cut</span>
        </div>
      </div>
    </div>
          <label>End Timestamp</label>
          <div class="time-field-row">
            <input type="text" id="clipEndInput" placeholder="00:00:00" value="${info.duration_str || '00:00:00'}">
            <button type="button" class="quick-time-btn" id="setEndMaxBtn">Full End</button>
          </div>
        </div>

        <div class="clip-duration-badge" id="clipDurationBadge">
          <span>Selected Clip Duration: <strong id="clipDurationText">${info.duration_str || 'Full Video'}</strong></span>
          <span style="font-size: 11px; opacity: 0.8;">(Fast keyframe stream-cut with audio)</span>
        </div>
      </div>
    </div>

    <div class="download-action-bar">
      <div class="connections-selector">
        <span>Acceleration:</span>
        <div class="conn-pills">
          <button class="conn-pill-btn" data-conn="4">4x</button>
          <button class="conn-pill-btn active" data-conn="8">8x Turbo</button>
          <button class="conn-pill-btn" data-conn="16">16x Max</button>
        </div>
      </div>
      <button class="start-dl-btn" id="startDownloadBtn">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
          <path d="M12 2L2 12h5v8h10v-8h5L12 2z"/>
        </svg>
        <span>Download Now</span>
      </button>
    </div>
  `;

  inspectResults.innerHTML = html;

  // Format Switcher
  const tabVideo = document.getElementById('tabVideo');
  const tabAudio = document.getElementById('tabAudio');
  const formatGrid = document.getElementById('formatGrid');

  function updateFormatCards() {
    const list = state.activeFormatType === 'video' ? info.video_options : info.audio_options;
    formatGrid.innerHTML = list.map(opt => `
      <div class="format-card ${state.selectedFormat?.id === opt.id ? 'selected' : ''}" data-fid="${opt.id}">
        <div>
          <div class="format-card-title">${opt.label}</div>
          <div class="format-card-sub">${opt.ext.toUpperCase()}</div>
        </div>
        <div class="format-card-size">${opt.filesize_str}</div>
      </div>
    `).join('');

    formatGrid.querySelectorAll('.format-card').forEach(card => {
      card.addEventListener('click', () => {
        const fid = card.dataset.fid;
        state.selectedFormat = list.find(x => x.id === fid);
        updateFormatCards();
      });
    });
  }

  tabVideo.addEventListener('click', () => {
    tabVideo.classList.add('active');
    tabAudio.classList.remove('active');
    state.activeFormatType = 'video';
    state.selectedFormat = info.video_options[0] || null;
    updateFormatCards();
  });

  tabAudio.addEventListener('click', () => {
    tabAudio.classList.add('active');
    tabVideo.classList.remove('active');
    state.activeFormatType = 'audio';
    state.selectedFormat = info.audio_options[0] || null;
    updateFormatCards();
  });

  updateFormatCards();

  // Video Trimmer Toggle & Inputs
  const openTrimmerStudioBtn = document.getElementById('openTrimmerStudioBtn');
  const enableClipToggle = document.getElementById('enableClipToggle');
  const trimmerControls = document.getElementById('trimmerControls');
  const clipStartInput = document.getElementById('clipStartInput');
  const clipEndInput = document.getElementById('clipEndInput');
  const clipDurationText = document.getElementById('clipDurationText');
  const setStartZeroBtn = document.getElementById('setStartZeroBtn');
  const setEndMaxBtn = document.getElementById('setEndMaxBtn');

  if (openTrimmerStudioBtn) {
    openTrimmerStudioBtn.addEventListener('click', () => {
      openTrimmerStudio(info);
    });
  }

  function updateClipDurationDisplay() {
    if (!enableClipToggle.checked) return;
    const s = parseTimeSeconds(clipStartInput.value);
    const e = parseTimeSeconds(clipEndInput.value);
    const diff = Math.max(0, e - s);
    clipDurationText.textContent = diff > 0 ? formatSeconds(diff) : '00:00:00 (Invalid range)';
  }

  enableClipToggle.addEventListener('change', () => {
    trimmerControls.style.display = enableClipToggle.checked ? 'grid' : 'none';
    if (enableClipToggle.checked && clipHtmlVideo && !clipHtmlVideo.src && clipHtmlVideo.dataset.src) {
      clipHtmlVideo.src = clipHtmlVideo.dataset.src;
      clipHtmlVideo.load();
    }
    updateClipDurationDisplay();
  });

  clipStartInput.addEventListener('input', updateClipDurationDisplay);
  clipEndInput.addEventListener('input', updateClipDurationDisplay);

  setStartZeroBtn.addEventListener('click', () => {
    clipStartInput.value = '00:00:00';
    updateClipDurationDisplay();
  });

  setEndMaxBtn.addEventListener('click', () => {
    clipEndInput.value = info.duration_str || '00:00:00';
    updateClipDurationDisplay();
  });

  // Interactive Video & Audio Preview Scrubber
  const clipTimelineSlider = document.getElementById('clipTimelineSlider');
  const scrubberTimeDisplay = document.getElementById('scrubberTimeDisplay');
  const startSliderLabel = document.getElementById('startSliderLabel');
  const endSliderLabel = document.getElementById('endSliderLabel');
  const setStartFromSliderBtn = document.getElementById('setStartFromSliderBtn');
  const setEndFromSliderBtn = document.getElementById('setEndFromSliderBtn');
  const seekMiddleBtn = document.getElementById('seekMiddleBtn');
  const clipIframePlayer = document.getElementById('clipIframePlayer');
  const clipHtmlVideo = document.getElementById('clipHtmlVideo');

  function seekPlayer(sec) {
    if (clipHtmlVideo) {
      clipHtmlVideo.currentTime = sec;
    }
    if (clipIframePlayer && clipIframePlayer.contentWindow) {
      clipIframePlayer.contentWindow.postMessage(
        JSON.stringify({ event: 'command', func: 'seekTo', args: [sec, true] }),
        '*'
      );
    }
  }

  if (clipTimelineSlider) {
    clipTimelineSlider.addEventListener('input', () => {
      const sec = parseFloat(clipTimelineSlider.value);
      const timeStr = formatSeconds(sec);
      if (scrubberTimeDisplay) scrubberTimeDisplay.textContent = `${timeStr} / ${info.duration_str || '00:00'}`;
      if (startSliderLabel) startSliderLabel.textContent = timeStr;
      if (endSliderLabel) endSliderLabel.textContent = timeStr;
      seekPlayer(sec);
    });
  }

  if (setStartFromSliderBtn) {
    setStartFromSliderBtn.addEventListener('click', () => {
      const sec = clipTimelineSlider ? parseFloat(clipTimelineSlider.value) : 0;
      clipStartInput.value = formatSeconds(sec);
      updateClipDurationDisplay();
      showToast(`✂️ Clip Start set to ${clipStartInput.value}`);
    });
  }

  if (setEndFromSliderBtn) {
    setEndFromSliderBtn.addEventListener('click', () => {
      const sec = clipTimelineSlider ? parseFloat(clipTimelineSlider.value) : 0;
      clipEndInput.value = formatSeconds(sec);
      updateClipDurationDisplay();
      showToast(`✂️ Clip End set to ${clipEndInput.value}`);
    });
  }

  if (seekMiddleBtn) {
    seekMiddleBtn.addEventListener('click', () => {
      const mid = Math.floor((info.duration || 60) / 2);
      if (clipTimelineSlider) {
        clipTimelineSlider.value = mid;
        clipTimelineSlider.dispatchEvent(new Event('input'));
      }
    });
  }

  if (clipHtmlVideo) {
    clipHtmlVideo.addEventListener('timeupdate', () => {
      if (clipTimelineSlider && !clipTimelineSlider.matches(':active')) {
        clipTimelineSlider.value = clipHtmlVideo.currentTime;
        const timeStr = formatSeconds(clipHtmlVideo.currentTime);
        if (scrubberTimeDisplay) scrubberTimeDisplay.textContent = `${timeStr} / ${info.duration_str || '00:00'}`;
        if (startSliderLabel) startSliderLabel.textContent = timeStr;
        if (endSliderLabel) endSliderLabel.textContent = timeStr;
      }
    });
  }

  // Turbo Connections
  inspectResults.querySelectorAll('.conn-pill-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      inspectResults.querySelectorAll('.conn-pill-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.connections = parseInt(btn.dataset.conn);
    });
  });

  // Start Download
  document.getElementById('startDownloadBtn').addEventListener('click', async () => {
    if (!state.selectedFormat) {
      showToast('Please select a format first', 'error');
      return;
    }

    const isClip = enableClipToggle && enableClipToggle.checked;
    const clipStart = isClip ? clipStartInput.value.trim() : null;
    const clipEnd = isClip ? clipEndInput.value.trim() : null;

    try {
      const resp = await fetch('/api/download/media', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: info.url,
          title: info.title,
          format_info: state.selectedFormat,
          thumbnail: info.thumbnail,
          clip_start: clipStart,
          clip_end: clipEnd
        })
      });
      const res = await resp.json();
      if (resp.ok) {
        inspectResults.style.display = 'none';
        urlInput.value = '';
        const clipMsg = isClip ? ` [Clipped: ${clipStart} - ${clipEnd}]` : '';
        showToast(`Downloading: ${info.title}${clipMsg}`);
        switchToActiveTab();
      }
    } catch (e) {
      showToast(`Error: ${e.message}`, 'error');
    }
  });
}

function renderDirectInspection(info) {
  const html = `
    <div class="direct-file-card">
      <div class="direct-file-row">
        <div>
          <div class="direct-file-name">📦 ${escapeHtml(info.filename)}</div>
          <div class="direct-file-meta">${info.content_type} &bull; ${info.accepts_ranges ? '⚡️ Multi-threaded Byte Ranges Supported' : 'Single Connection Stream'}</div>
        </div>
        <div class="format-card-size" style="font-size: 14px;">${info.total_size_str}</div>
      </div>
    </div>

    <div class="download-action-bar">
      <div class="connections-selector">
        <span>Parallel Connections:</span>
        <div class="conn-pills">
          <button class="conn-pill-btn" data-conn="4">4 Conns</button>
          <button class="conn-pill-btn active" data-conn="8">8 Conns (IDM)</button>
          <button class="conn-pill-btn" data-conn="16">16 Conns (Max)</button>
        </div>
      </div>
      <button class="start-dl-btn" id="startDirectDownloadBtn">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
          <path d="M12 2L2 12h5v8h10v-8h5L12 2z"/>
        </svg>
        <span>Start Accelerated Download</span>
      </button>
    </div>
  `;

  inspectResults.innerHTML = html;

  inspectResults.querySelectorAll('.conn-pill-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      inspectResults.querySelectorAll('.conn-pill-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.connections = parseInt(btn.dataset.conn);
    });
  });

  document.getElementById('startDirectDownloadBtn').addEventListener('click', async () => {
    try {
      const resp = await fetch('/api/download/direct', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: info.url,
          filename: info.filename,
          connections: state.connections
        })
      });
      if (resp.ok) {
        inspectResults.style.display = 'none';
        urlInput.value = '';
        showToast(`Started downloading: ${info.filename}`);
        switchToActiveTab();
      }
    } catch (e) {
      showToast(`Error: ${e.message}`, 'error');
    }
  });
}

function switchToActiveTab() {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelector('.tab-btn[data-tab="active"]').classList.add('active');
  state.activeTab = 'active';
  activeJobsContainer.style.display = 'flex';
  completedJobsContainer.style.display = 'none';
}

// WebSocket connection for real-time telemetry
function initWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws`;

  state.ws = new WebSocket(wsUrl);

  state.ws.onopen = () => {
    wsStatus.innerHTML = '<span class="dot active"></span> Live 60fps';
  };

  state.ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.type === 'init') {
        state.jobs = {};
        data.jobs.forEach(j => { state.jobs[j.id] = j; });
        renderJobs();
      } else if (data.type === 'job_update') {
        const oldJob = state.jobs[data.job.id];
        state.jobs[data.job.id] = data.job;
        const oldActive = oldJob && ['queued', 'downloading', 'assembling', 'paused'].includes(oldJob.status);
        const newActive = ['queued', 'downloading', 'assembling', 'paused'].includes(data.job.status);
        if (!oldJob || oldActive !== newActive) {
          renderJobs();
        } else {
          const card = document.querySelector(`.job-card[data-jobid="${data.job.id}"]`);
          if (card) {
            updateJobCardInPlace(card, data.job);
          } else {
            renderJobs();
          }
        }
      } else if (data.type === 'active_batch') {
        let needsRender = false;
        data.jobs.forEach(j => {
          const existed = !!state.jobs[j.id];
          state.jobs[j.id] = j;
          const card = document.querySelector(`.job-card[data-jobid="${j.id}"]`);
          if (card) {
            updateJobCardInPlace(card, j);
          } else {
            needsRender = true;
          }
          if (!existed) needsRender = true;
        });
        if (needsRender) renderJobs();
      } else if (data.type === 'job_deleted') {
        delete state.jobs[data.job_id];
        renderJobs();
      } else if (data.type === 'cookies_updated') {
        checkCookieStatus();
        if (data.count > 0) {
          showToast(`✅ Successfully synced ${data.count} YouTube cookies! BotGuard bypassed.`, 'success');
          if (pendingRetryUrl && urlInput.value.trim() === pendingRetryUrl) {
            showToast('🔄 Auto-analyzing video link with newly synced cookies...');
            inspectForm.dispatchEvent(new Event('submit'));
            pendingRetryUrl = null;
          }
        } else {
          showToast('Cookie sync window closed. No new cookies saved.', 'info');
        }
      }
    } catch (e) {
      // ignore
    }
  };

  state.ws.onclose = () => {
    wsStatus.innerHTML = '<span class="dot" style="background:#f39c12"></span> Reconnecting...';
    setTimeout(initWebSocket, 2000);
  };
}

// Global Event Delegation for Job Actions
function setupJobActionDelegation() {
  function handleActionClick(e) {
    const btn = e.target.closest('button[data-jobid]');
    if (!btn) return;
    e.stopPropagation();
    const jobId = btn.dataset.jobid;
    if (btn.classList.contains('pause-btn')) {
      fetch(`/api/jobs/${jobId}/pause`, { method: 'POST' }).catch(() => {});
      showToast('⏸️ Pausing download...');
    } else if (btn.classList.contains('resume-btn')) {
      fetch(`/api/jobs/${jobId}/resume`, { method: 'POST' }).catch(() => {});
      showToast('▶️ Resuming download...');
    } else if (btn.classList.contains('delete-btn')) {
      fetch(`/api/jobs/${jobId}`, { method: 'DELETE' }).catch(() => {});
      showToast('🗑️ Removing download...');
    } else if (btn.classList.contains('reveal-btn')) {
      fetch(`/api/jobs/${jobId}/reveal`, { method: 'POST' }).catch(() => {});
      showToast('📂 Revealing in macOS Finder...');
    } else if (btn.classList.contains('open-btn')) {
      fetch(`/api/jobs/${jobId}/open`, { method: 'POST' }).catch(() => {});
    }
  }

  if (activeJobsContainer) activeJobsContainer.addEventListener('click', handleActionClick);
  if (completedJobsContainer) completedJobsContainer.addEventListener('click', handleActionClick);
}

// In-place Job Card Updater (eliminates DOM thrashing and CPU lag)
function updateJobCardInPlace(card, job) {
  const isDownloading = job.status === 'downloading';
  const isQueued      = job.status === 'queued';
  const isPaused      = job.status === 'paused';
  const isClip        = !!(job.clip_start || job.clip_end);
  const isActive      = isDownloading || isQueued;

  let statusBadge = '';
  if (isDownloading || isQueued) {
    statusBadge = isClip
      ? '<span style="color:var(--accent-cyan)">Downloading full file for clip…</span>'
      : '<span style="color:var(--accent-cyan)">Downloading</span>';
  }
  else if (job.status === 'assembling') statusBadge = '<span style="color:var(--accent-amber)">Muxing & Merging…</span>';
  else if (isPaused)    statusBadge = '<span style="color:var(--accent-amber)">Paused</span>';
  else if (job.status === 'completed') statusBadge = '<span style="color:var(--accent-green)">Completed</span>';
  else if (job.status === 'error') statusBadge = `<span style="color:var(--accent-red)">Error: ${escapeHtml(job.error_message || 'Failed')}</span>`;

  // Meta line update
  const metaLine = card.querySelector('.job-meta-line');
  if (metaLine) {
    const metaProgress = (isActive || isPaused)
      ? `<span class="meta-progress">${job.downloaded_str} / ${job.total_str} (${job.progress}%)</span>`
      : '';
    const clipBadge = isClip
      ? `<span class="clip-badge">✂️ ${job.clip_start || '00:00'}–${job.clip_end || 'end'}</span>`
      : '';
    metaLine.innerHTML = `${statusBadge}${metaProgress}${clipBadge}`;
  }

  // Progress Bar
  const progressBar = card.querySelector('.progress-bar-fill');
  if (progressBar) progressBar.style.width = `${job.progress}%`;

  // Segment bars in-place update (auto-creates if missing so 2+ downloads show threads reliably)
  if (job.segments && job.segments.length > 0 && isActive) {
    let viz = card.querySelector('.segment-visualizer');
    let segmentBlocks = card.querySelectorAll('.segment-block');
    if (!viz || segmentBlocks.length !== job.segments.length) {
      const progressRow = card.querySelector('.job-progress-row');
      if (progressRow) {
        if (viz) viz.remove();
        viz = document.createElement('div');
        viz.className = 'segment-visualizer';
        viz.innerHTML = job.segments.map((s, i) => `
          <div class="segment-block" title="Thread ${i+1}: ${Math.round(s.progress_pct || 0)}%">
            <div class="segment-fill" style="width: ${s.progress_pct || 0}%"></div>
          </div>
        `).join('');
        progressRow.appendChild(viz);
      }
    } else {
      job.segments.forEach((seg, idx) => {
        const fill = segmentBlocks[idx].querySelector('.segment-fill');
        if (fill) fill.style.width = `${seg.progress_pct}%`;
        segmentBlocks[idx].title = `Thread ${idx+1}: ${Math.round(seg.progress_pct)}%`;
      });
    }
  } else if (!isActive) {
    const viz = card.querySelector('.segment-visualizer');
    if (viz) viz.remove();
  }

  // Telemetry row
  let telemetry = card.querySelector('.job-telemetry-row');
  if (isActive) {
    if (!telemetry) {
      telemetry = document.createElement('div');
      telemetry.className = 'job-telemetry-row';
      card.appendChild(telemetry);
    }
    telemetry.innerHTML = `
      <span class="speed-badge">⚡ ${job.speed_str || '0 KB/s'}</span>
      <span class="eta-label">ETA: ${job.eta_str || '—'}</span>
    `;
  } else if (telemetry) {
    telemetry.remove();
  }

  // Pause / Resume button swap
  const pauseBtn  = card.querySelector('.pause-btn');
  const resumeBtn = card.querySelector('.resume-btn');
  if (isDownloading && resumeBtn) {
    resumeBtn.outerHTML = `
      <button class="action-btn pause-btn" data-jobid="${job.id}" title="Pause">
        <svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>
      </button>`;
  } else if (isPaused && pauseBtn) {
    pauseBtn.outerHTML = `
      <button class="action-btn resume-btn" data-jobid="${job.id}" title="Resume">
        <svg viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
      </button>`;
  }
}

// Render Job Cards
function renderJobs() {
  const jobList = Object.values(state.jobs).sort((a, b) => b.created_at - a.created_at);
  const activeJobs = jobList.filter(j => ['queued', 'downloading', 'assembling', 'paused'].includes(j.status));
  const completedJobs = jobList.filter(j => ['completed', 'error', 'cancelled'].includes(j.status));

  if (activeBadge) activeBadge.textContent = activeJobs.length;
  if (completedBadge) completedBadge.textContent = completedJobs.length;

  // Render Active
  if (activeJobsContainer) {
    if (activeJobs.length === 0) {
      activeJobsContainer.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon">⚡️</div>
          <h3>No Active Downloads</h3>
          <p>Paste a video or direct file URL above to initiate an accelerated download.</p>
        </div>
      `;
    } else {
      activeJobsContainer.innerHTML = activeJobs.map(j => renderJobCard(j)).join('');
    }
  }

  // Render Completed
  if (completedJobsContainer) {
    if (completedJobs.length === 0) {
      completedJobsContainer.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon">📁</div>
          <h3>No Completed Downloads Yet</h3>
          <p>Your finished downloads and muxed media files will be organized here.</p>
        </div>
      `;
    } else {
      completedJobsContainer.innerHTML = completedJobs.map(j => renderJobCard(j)).join('');
    }
  }
}

function renderJobCard(job) {
  const isDownloading = job.status === 'downloading';
  const isQueued     = job.status === 'queued';
  const isPaused     = job.status === 'paused';
  const isCompleted  = job.status === 'completed';
  const isClip       = !!(job.clip_start || job.clip_end);

  let statusBadge = '';
  if (isDownloading || isQueued) {
    if (isClip) {
      statusBadge = '<span style="color:var(--accent-cyan)">Downloading full file for clip…</span>';
    } else {
      statusBadge = '<span style="color:var(--accent-cyan)">Downloading</span>';
    }
  }
  else if (job.status === 'assembling') statusBadge = '<span style="color:var(--accent-amber)">Muxing & Merging…</span>';
  else if (isPaused)    statusBadge = '<span style="color:var(--accent-amber)">Paused</span>';
  else if (isCompleted) statusBadge = '<span style="color:var(--accent-green)">Completed</span>';
  else if (job.status === 'error') statusBadge = `<span style="color:var(--accent-red)">Error: ${escapeHtml(job.error_message || 'Failed')}</span>`;

  // Segment bars — compact single row
  let segmentsHtml = '';
  if (job.segments && job.segments.length > 0 && (isDownloading || isQueued || isPaused)) {
    segmentsHtml = `
      <div class="segment-visualizer">
        ${job.segments.map((s, i) => `
          <div class="segment-block" title="Thread ${i+1}: ${Math.round(s.progress_pct)}%">
            <div class="segment-fill" style="width: ${s.progress_pct}%"></div>
          </div>
        `).join('')}
      </div>
    `;
  }

  const clipBadge = isClip
    ? `<span class="clip-badge">✂️ ${job.clip_start || '00:00'}–${job.clip_end || 'end'}</span>`
    : '';

  const metaProgress = (isDownloading || isQueued || isPaused)
    ? `${job.downloaded_str} / ${job.total_str} (${job.progress}%)`
    : '';

  return `
    <div class="job-card" data-jobid="${job.id}">
      <div class="job-main-row">
        <div class="job-info-col">
          <div class="job-icon">
            ${job.thumbnail ? `<img src="${job.thumbnail}" alt="">` : `
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                <polyline points="7 10 12 15 17 10"/>
                <line x1="12" y1="15" x2="12" y2="3"/>
              </svg>
            `}
          </div>
          <div class="job-text">
            <div class="job-title" title="${escapeHtml(job.title)}">${escapeHtml(job.title)}</div>
            <div class="job-meta-line">
              ${statusBadge}
              ${metaProgress ? `<span class="meta-progress">${metaProgress}</span>` : ''}
              ${clipBadge}
            </div>
          </div>
        </div>

        <div class="job-actions">
          ${isDownloading ? `
            <button class="action-btn pause-btn" data-jobid="${job.id}" title="Pause">
              <svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>
            </button>
          ` : ''}
          ${isPaused ? `
            <button class="action-btn resume-btn" data-jobid="${job.id}" title="Resume">
              <svg viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
            </button>
          ` : ''}
          ${isCompleted ? `
            <button class="action-btn primary-action open-btn" data-jobid="${job.id}" title="Open">
              <svg viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
            </button>
            <button class="action-btn reveal-btn" data-jobid="${job.id}" title="Reveal in Finder">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
              </svg>
            </button>
          ` : ''}
          <button class="action-btn delete-btn" data-jobid="${job.id}" title="Remove">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
      </div>

      <div class="job-progress-row">
        <div class="progress-bar-container">
          <div class="progress-bar-fill" style="width: ${job.progress}%"></div>
        </div>
        ${segmentsHtml}
      </div>

      ${(isDownloading || isQueued) ? `
        <div class="job-telemetry-row">
          <span class="speed-badge">⚡ ${job.speed_str || '0 KB/s'}</span>
          <span class="eta-label">ETA: ${job.eta_str || '—'}</span>
        </div>
      ` : ''}
    </div>
  `;
}

function showToast(message, type = 'info') {
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.textContent = message;
  toastContainer.appendChild(toast);
  setTimeout(() => {
    toast.remove();
  }, 3500);
}

function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/[&<>"']/g, m => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  })[m]);
}
