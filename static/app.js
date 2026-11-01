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

  // 1-Click Sync Handlers
  const quickSyncBtn = document.getElementById('quickSyncBtn');
  const modalOneClickSyncBtn = document.getElementById('modalOneClickSyncBtn');
  if (quickSyncBtn) {
    quickSyncBtn.addEventListener('click', () => launch1ClickSync());
  }
  if (modalOneClickSyncBtn) {
    modalOneClickSyncBtn.addEventListener('click', () => launch1ClickSync());
  }

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

let isCapturingCookies = false;
let pendingRetryUrl = null;

async function launch1ClickSync() {
  if (isCapturingCookies) {
    showToast('YouTube sync window is already open! Please check your open windows.', 'info');
    return;
  }
  
  isCapturingCookies = true;
  const quickBtn = document.getElementById('quickSyncBtn');
  const modalBtn = document.getElementById('modalOneClickSyncBtn');
  const modalText = document.getElementById('modalSyncBtnText');
  const modalSpinner = document.getElementById('modalSyncSpinner');

  if (quickBtn) quickBtn.innerHTML = '<span class="dot sync-dot"></span> ⏳ Sync Window Open...';
  if (modalText) modalText.innerText = '⏳ Window Open: Sign in & Click Save...';
  if (modalSpinner) modalSpinner.style.display = 'inline-block';

  showToast('⚡ Opening native YouTube window... Log in or click "Save Cookies & Close" in the window!');

  try {
    const resp = await fetch('/api/cookies/capture', { method: 'POST' });
    const data = await resp.json();
    if (!resp.ok) {
      throw new Error(data.detail || 'Failed to open window');
    }
  } catch (err) {
    showToast(`Error: ${err.message}`, 'error');
    resetSyncButtonStates();
  }
}

function resetSyncButtonStates() {
  isCapturingCookies = false;
  const quickBtn = document.getElementById('quickSyncBtn');
  const modalBtn = document.getElementById('modalOneClickSyncBtn');
  const modalText = document.getElementById('modalSyncBtnText');
  const modalSpinner = document.getElementById('modalSyncSpinner');

  if (quickBtn) quickBtn.innerHTML = '<span class="dot sync-dot"></span> ⚡ 1-Click Sync';
  if (modalText) modalText.innerText = '⚡ Open YouTube Window & Sync Cookies';
  if (modalSpinner) modalSpinner.style.display = 'none';
}

function renderBotGuardError(errorMsg, failedUrl) {
  pendingRetryUrl = failedUrl;
  inspectResults.style.display = 'block';
  inspectResults.innerHTML = `
    <div class="botguard-alert-box">
      <div class="botguard-alert-title">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
        <span>YouTube BotGuard Verification Required</span>
      </div>
      <p class="botguard-alert-desc">
        YouTube detected this IP as automated (<em>"Sign in to confirm you’re not a bot"</em>). 
        Click the <strong>1-Click YouTube Login & Sync</strong> button below to open a native window, verify/log in, and automatically bypass BotGuard!
      </p>
      <div class="botguard-action-row">
        <button type="button" class="sync-large-btn" id="inlineSyncBtn" style="margin: 0; padding: 10px 20px;">
          ⚡ 1-Click YouTube Login & Sync
        </button>
        <button type="button" class="upload-cookie-btn" id="inlineMoreCookieBtn" style="padding: 10px 16px;">
          Manual Cookie Options
        </button>
      </div>
    </div>
  `;

  document.getElementById('inlineSyncBtn').addEventListener('click', () => {
    launch1ClickSync();
  });
  document.getElementById('inlineMoreCookieBtn').addEventListener('click', () => {
    document.getElementById('cookieModal').style.display = 'flex';
  });
}

async function checkCookieStatus() {
  try {
    const resp = await fetch('/api/cookies/status');
    const data = await resp.json();
    const dot = document.getElementById('cookieDot');
    const label = document.getElementById('cookieLabel');
    const statusText = document.getElementById('currentStatusText');
    const clearBtn = document.getElementById('clearCookieBtn');

    if (data.has_cookies) {
      dot.style.background = 'var(--accent-green)';
      dot.style.boxShadow = '0 0 8px var(--accent-green)';
      label.textContent = 'Cookies: Active';
      statusText.innerHTML = `✅ <strong>Cookies Active</strong> &bull; Size: ${Math.round(data.size / 1024)} KB`;
      clearBtn.style.display = 'inline-block';
    } else {
      dot.style.background = '#f39c12';
      dot.style.boxShadow = 'none';
      label.textContent = 'Cookies: None';
      statusText.innerHTML = '⚠️ <strong>No cookies configured</strong> (YouTube may block requests)';
      clearBtn.style.display = 'none';
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
      </div>

      <div class="trimmer-inputs-wrapper" id="trimmerControls" style="display: none;">
        <!-- Embedded Interactive Preview Player (Video + Audio) -->
        <div class="clip-preview-container">
          <div class="preview-media-box">
            ${(info.extractor === 'Youtube' || (info.url && (info.url.includes('youtube.com') || info.url.includes('youtu.be')))) && info.id ? `
              <iframe 
                id="clipIframePlayer" 
                src="https://www.youtube-nocookie.com/embed/${info.id}?enablejsapi=1&playsinline=1" 
                title="Preview" 
                frameborder="0" 
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" 
                allowfullscreen>
              </iframe>
            ` : (info.preview_stream_url ? `
              <video id="clipHtmlVideo" controls playsinline src="${info.preview_stream_url}" poster="${info.thumbnail}"></video>
            ` : `
              <div class="preview-placeholder">
                <img src="${info.thumbnail}" alt="Thumbnail">
                <span class="preview-note">Use timeline scrubber & quick buttons below to select clip</span>
              </div>
            `)}
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
  const enableClipToggle = document.getElementById('enableClipToggle');
  const trimmerControls = document.getElementById('trimmerControls');
  const clipStartInput = document.getElementById('clipStartInput');
  const clipEndInput = document.getElementById('clipEndInput');
  const clipDurationText = document.getElementById('clipDurationText');
  const setStartZeroBtn = document.getElementById('setStartZeroBtn');
  const setEndMaxBtn = document.getElementById('setEndMaxBtn');

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
    if (sec <= 0) return '00:00';
    const s = Math.floor(sec % 60);
    const m = Math.floor((sec / 60) % 60);
    const h = Math.floor(sec / 3600);
    const pad = n => String(n).padStart(2, '0');
    if (h > 0) return `${pad(h)}:${pad(m)}:${pad(s)}`;
    return `${pad(m)}:${pad(s)}`;
  }

  function updateClipDurationDisplay() {
    if (!enableClipToggle.checked) return;
    const s = parseTimeSeconds(clipStartInput.value);
    const e = parseTimeSeconds(clipEndInput.value);
    const diff = Math.max(0, e - s);
    clipDurationText.textContent = diff > 0 ? formatSeconds(diff) : '00:00 (Invalid range)';
  }

  enableClipToggle.addEventListener('change', () => {
    trimmerControls.style.display = enableClipToggle.checked ? 'grid' : 'none';
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
        state.jobs[data.job.id] = data.job;
        renderJobs();
      } else if (data.type === 'active_batch') {
        data.jobs.forEach(j => { state.jobs[j.id] = j; });
        renderJobs();
      } else if (data.type === 'job_deleted') {
        delete state.jobs[data.job_id];
        renderJobs();
      } else if (data.type === 'cookies_updated') {
        resetSyncButtonStates();
        checkCookieStatus();
        if (data.count > 0) {
          showToast(`✅ Successfully synced ${data.count} YouTube cookies! BotGuard bypassed.`, 'success');
          // If user was trying to analyze a link that failed with BotGuard, auto-retry now!
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

// Render Job Cards
function renderJobs() {
  const jobList = Object.values(state.jobs).sort((a, b) => b.created_at - a.created_at);
  const activeJobs = jobList.filter(j => ['queued', 'downloading', 'assembling', 'paused'].includes(j.status));
  const completedJobs = jobList.filter(j => ['completed', 'error', 'cancelled'].includes(j.status));

  activeBadge.textContent = activeJobs.length;
  completedBadge.textContent = completedJobs.length;

  // Render Active
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

  // Render Completed
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

  attachJobActionListeners();
}

function renderJobCard(job) {
  const isDownloading = job.status === 'downloading';
  const isPaused = job.status === 'paused';
  const isCompleted = job.status === 'completed';

  let statusBadge = '';
  if (job.status === 'downloading') statusBadge = '<span style="color:var(--accent-cyan)">Downloading</span>';
  else if (job.status === 'assembling') statusBadge = '<span style="color:var(--accent-amber)">Muxing & Merging...</span>';
  else if (job.status === 'paused') statusBadge = '<span style="color:var(--accent-amber)">Paused</span>';
  else if (job.status === 'completed') statusBadge = '<span style="color:var(--accent-green)">Completed</span>';
  else if (job.status === 'error') statusBadge = `<span style="color:var(--accent-red)">Error: ${escapeHtml(job.error_message || 'Failed')}</span>`;

  // Segment visualizer (for multi-threaded IDM direct downloads)
  let segmentsHtml = '';
  if (job.segments && job.segments.length > 0 && (isDownloading || isPaused)) {
    segmentsHtml = `
      <div class="segment-visualizer">
        ${job.segments.map(s => `
          <div class="segment-block" title="Chunk ${s.index}: ${s.progress_pct}%">
            <div class="segment-fill" style="width: ${s.progress_pct}%"></div>
          </div>
        `).join('')}
      </div>
    `;
  }

  return `
    <div class="job-card" data-jobid="${job.id}">
      <div class="job-main-row">
        <div class="job-info-col">
          <div class="job-icon">
            ${job.thumbnail ? `<img src="${job.thumbnail}" alt="Thumbnail">` : `
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
              ${statusBadge} &bull; ${job.downloaded_str} of ${job.total_str} (${job.progress}%)
              ${job.clip_start || job.clip_end ? ` &bull; <span class="clip-badge">✂️ Clip: ${job.clip_start || '00:00'} - ${job.clip_end || 'end'}</span>` : ''}
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
            <button class="action-btn primary-action open-btn" data-jobid="${job.id}" title="Play / Open">
              <svg viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
            </button>
            <button class="action-btn reveal-btn" data-jobid="${job.id}" title="Reveal in macOS Finder">
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

      <div class="progress-bar-container">
        <div class="progress-bar-fill" style="width: ${job.progress}%"></div>
      </div>

      ${segmentsHtml}

      ${isDownloading ? `
        <div class="job-telemetry-row">
          <span class="speed-badge">⚡️ ${job.speed_str}</span>
          <span>ETA: ${job.eta_str}</span>
        </div>
      ` : ''}
    </div>
  `;
}

function attachJobActionListeners() {
  document.querySelectorAll('.pause-btn').forEach(btn => {
    btn.onclick = () => fetch(`/api/jobs/${btn.dataset.jobid}/pause`, { method: 'POST' });
  });

  document.querySelectorAll('.resume-btn').forEach(btn => {
    btn.onclick = () => fetch(`/api/jobs/${btn.dataset.jobid}/resume`, { method: 'POST' });
  });

  document.querySelectorAll('.reveal-btn').forEach(btn => {
    btn.onclick = () => fetch(`/api/jobs/${btn.dataset.jobid}/reveal`, { method: 'POST' });
  });

  document.querySelectorAll('.open-btn').forEach(btn => {
    btn.onclick = () => fetch(`/api/jobs/${btn.dataset.jobid}/open`, { method: 'POST' });
  });

  document.querySelectorAll('.delete-btn').forEach(btn => {
    btn.onclick = () => fetch(`/api/jobs/${btn.dataset.jobid}`, { method: 'DELETE' });
  });
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
