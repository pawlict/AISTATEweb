/**
 * audio_player.js — Main audio playback bar with text synchronization.
 *
 * Provides a sticky audio player that:
 *   - Shows waveform-style progress bar
 *   - Highlights the active text block as audio plays
 *   - Includes play/pause, skip ±5s, speed control, time display
 *   - Shared between Transcription and Diarization pages
 *
 * Usage:
 *   const player = new AudioPlayer({
 *     containerId: "audio_player",      // DOM id to render into
 *     getAudioUrl: () => "...",          // function returning audio URL
 *     getSegments: () => [...],          // function returning [{start, end, ...}]
 *     onSegmentActive: (idx) => {},      // callback when segment becomes active
 *     onSegmentInactive: (idx) => {},    // callback when segment stops being active
 *     blocksContainerId: "di_blocks",    // container with .seg elements
 *   });
 *   player.init();
 */

/* global i18n */

(function () {
  "use strict";

  function AudioPlayer(opts) {
    this.opts = opts || {};
    this.audio = null;
    this.activeIdx = -1;
    this._raf = null;
    this._mounted = false;
  }

  AudioPlayer.prototype.init = function () {
    var container = document.getElementById(this.opts.containerId);
    if (!container) return;

    var url = this.opts.getAudioUrl ? this.opts.getAudioUrl() : "";
    if (!url) {
      container.style.display = "none";
      return;
    }

    this.audio = new Audio(url);
    this.audio.preload = "auto";

    // Restore speed
    try {
      var r = parseFloat(localStorage.getItem("aistateweb:audio_speed") || "1");
      if (!isNaN(r) && r > 0) this.audio.playbackRate = r;
    } catch (e) {}

    this._render(container);
    this._bindEvents();
    this._mounted = true;
  };

  AudioPlayer.prototype._render = function (container) {
    container.innerHTML = "";
    container.className = "audio-player-bar";

    var html = '<div class="ap-controls">';
    // Skip back
    html += '<button class="ap-btn" data-act="skip-back" title="' + _t("player.back5") + '">';
    html += aiIcon("skip_back_5", 18);
    html += '</button>';

    // Play / Pause
    html += '<button class="ap-btn ap-btn-play" data-act="play-pause" title="' + _t("player.play") + '">';
    html += '<span class="ap-icon-play">' + aiIcon("play", 30) + '</span>';
    html += '<span class="ap-icon-pause" style="display:none">' + aiIcon("pause", 30) + '</span>';
    html += '</button>';

    // Skip forward
    html += '<button class="ap-btn" data-act="skip-fwd" title="' + _t("player.fwd5") + '">';
    html += aiIcon("skip_fwd_5", 18);
    html += '</button>';

    html += '</div>';

    // Progress bar
    html += '<div class="ap-progress-wrap">';
    html += '  <div class="ap-progress-bar"><div class="ap-progress-fill"></div></div>';
    html += '</div>';

    // Time
    html += '<div class="ap-time"><span class="ap-time-cur">0:00</span> / <span class="ap-time-dur">0:00</span></div>';

    // Speed
    html += '<div class="ap-speed">';
    html += '  <select class="ap-speed-sel">';
    html += '    <option value="0.5">0.5x</option>';
    html += '    <option value="0.75">0.75x</option>';
    html += '    <option value="1" selected>1x</option>';
    html += '    <option value="1.25">1.25x</option>';
    html += '    <option value="1.5">1.5x</option>';
    html += '    <option value="2">2x</option>';
    html += '  </select>';
    html += '</div>';

    container.innerHTML = html;

    // Restore speed in select
    try {
      var sel = container.querySelector(".ap-speed-sel");
      var r = parseFloat(localStorage.getItem("aistateweb:audio_speed") || "1");
      if (sel && !isNaN(r) && r > 0) sel.value = String(r);
    } catch (e) {}
  };

  AudioPlayer.prototype._bindEvents = function () {
    var self = this;
    var container = document.getElementById(this.opts.containerId);
    if (!container || !this.audio) return;

    // Play / Pause
    var playPauseBtn = container.querySelector('[data-act="play-pause"]');
    if (playPauseBtn) {
      playPauseBtn.addEventListener("click", function () {
        if (self.audio.paused) {
          // Stop any hover-playback endWatch before starting main player
          if (typeof segTools !== "undefined" && segTools._stopHover) segTools._stopHover();
          self.audio.play().catch(function () {});
        } else {
          self.audio.pause();
        }
      });
    }

    // Skip
    container.querySelector('[data-act="skip-back"]').addEventListener("click", function () {
      self.audio.currentTime = Math.max(0, self.audio.currentTime - 5);
    });
    container.querySelector('[data-act="skip-fwd"]').addEventListener("click", function () {
      self.audio.currentTime = Math.min(self.audio.duration || 9999, self.audio.currentTime + 5);
    });

    // Speed
    var speedSel = container.querySelector(".ap-speed-sel");
    if (speedSel) {
      speedSel.addEventListener("change", function () {
        var r = parseFloat(speedSel.value || "1");
        if (!isNaN(r) && r > 0) {
          self.audio.playbackRate = r;
          try { localStorage.setItem("aistateweb:audio_speed", String(r)); } catch (e) {}
        }
      });
    }

    // Progress bar click-to-seek
    var progressWrap = container.querySelector(".ap-progress-wrap");
    if (progressWrap) {
      progressWrap.addEventListener("click", function (e) {
        if (!self.audio.duration) return;
        var rect = progressWrap.getBoundingClientRect();
        var pct = (e.clientX - rect.left) / rect.width;
        self.audio.currentTime = pct * self.audio.duration;
      });
    }

    // Audio events
    this.audio.addEventListener("play", function () {
      self._onPlayState(true);
      self._startAnimLoop();
    });
    this.audio.addEventListener("pause", function () {
      self._onPlayState(false);
      self._stopAnimLoop();
      self._updateProgress(); // final update
    });
    this.audio.addEventListener("ended", function () {
      self._onPlayState(false);
      self._stopAnimLoop();
      self._updateProgress();
    });
    this.audio.addEventListener("loadedmetadata", function () { self._updateDuration(); });
    this.audio.addEventListener("durationchange", function () { self._updateDuration(); });
  };

  AudioPlayer.prototype._onPlayState = function (playing) {
    var container = document.getElementById(this.opts.containerId);
    if (!container) return;
    var iconPlay = container.querySelector(".ap-icon-play");
    var iconPause = container.querySelector(".ap-icon-pause");
    if (iconPlay) iconPlay.style.display = playing ? "none" : "";
    if (iconPause) iconPause.style.display = playing ? "" : "none";
  };

  AudioPlayer.prototype._updateDuration = function () {
    var container = document.getElementById(this.opts.containerId);
    if (!container) return;
    var dur = container.querySelector(".ap-time-dur");
    if (dur && this.audio.duration && !isNaN(this.audio.duration)) {
      dur.textContent = _fmtTime(this.audio.duration);
    }
  };

  AudioPlayer.prototype._startAnimLoop = function () {
    if (this._raf) return; // already running
    var self = this;
    var lastProgress = 0;
    var lastSync = 0;
    function tick(ts) {
      // Throttle progress bar updates to ~15fps (every 66ms)
      if (ts - lastProgress >= 66) {
        self._updateProgress();
        lastProgress = ts;
      }
      // Throttle segment highlight sync to ~5fps (every 200ms)
      if (ts - lastSync >= 200) {
        self._syncHighlight();
        lastSync = ts;
      }
      self._raf = requestAnimationFrame(tick);
    }
    this._raf = requestAnimationFrame(tick);
  };

  AudioPlayer.prototype._stopAnimLoop = function () {
    if (this._raf) {
      cancelAnimationFrame(this._raf);
      this._raf = null;
    }
  };

  AudioPlayer.prototype._updateProgress = function () {
    if (!this.audio) return;
    // Cache DOM elements to avoid querySelector every frame
    if (!this._elCur || !this._elFill) {
      var container = document.getElementById(this.opts.containerId);
      if (!container) return;
      this._elCur = container.querySelector(".ap-time-cur");
      this._elFill = container.querySelector(".ap-progress-fill");
    }
    var cur = this.audio.currentTime || 0;
    var dur = this.audio.duration || 0;

    if (this._elCur) this._elCur.textContent = _fmtTime(cur);
    if (this._elFill && dur > 0) {
      this._elFill.style.width = ((cur / dur) * 100) + "%";
    }
  };

  AudioPlayer.prototype._syncHighlight = function () {
    if (!this.audio || this.audio.paused) return;

    var segments = this.opts.getSegments ? this.opts.getSegments() : [];
    if (!segments.length) return;

    var t = this.audio.currentTime;
    var newIdx = -1;

    // Optimize: check current active segment first (common case — same segment)
    if (this.activeIdx >= 0 && this.activeIdx < segments.length) {
      var cur = segments[this.activeIdx];
      if (t >= cur.start && t < cur.end) return; // still in same segment
    }

    for (var i = 0; i < segments.length; i++) {
      if (t >= segments[i].start && t < segments[i].end) {
        newIdx = i;
        break;
      }
    }

    if (newIdx !== this.activeIdx) {
      // Deactivate old
      if (this.activeIdx >= 0) {
        _toggleSegClass(this.opts.blocksContainerId, this.activeIdx, false);
        if (this.opts.onSegmentInactive) this.opts.onSegmentInactive(this.activeIdx);
      }
      // Activate new
      if (newIdx >= 0) {
        _toggleSegClass(this.opts.blocksContainerId, newIdx, true);
        _scrollSegIntoView(this.opts.blocksContainerId, newIdx);
        if (this.opts.onSegmentActive) this.opts.onSegmentActive(newIdx);
      }
      this.activeIdx = newIdx;
    }
  };

  AudioPlayer.prototype.isPlaying = function () {
    return this.audio && !this.audio.paused;
  };

  AudioPlayer.prototype.seekTo = function (sec) {
    if (this.audio) this.audio.currentTime = Math.max(0, sec);
  };

  AudioPlayer.prototype.play = function () {
    if (this.audio) this.audio.play().catch(function () {});
  };

  AudioPlayer.prototype.pause = function () {
    if (this.audio) this.audio.pause();
  };

  AudioPlayer.prototype.getAudio = function () {
    return this.audio;
  };

  AudioPlayer.prototype.destroy = function () {
    if (this._raf) cancelAnimationFrame(this._raf);
    if (this.audio) {
      this.audio.pause();
      this.audio.src = "";
    }
  };

  // ---------- helpers ----------

  function _toggleSegClass(containerId, idx, active) {
    var blocksEl = document.getElementById(containerId);
    if (!blocksEl) return;
    var seg = blocksEl.querySelector('.seg[data-idx="' + idx + '"]');
    if (seg) {
      if (active) {
        seg.classList.add("seg-playing");
      } else {
        seg.classList.remove("seg-playing");
      }
    }
  }

  function _scrollSegIntoView(containerId, idx) {
    var blocksEl = document.getElementById(containerId);
    if (!blocksEl) return;
    var seg = blocksEl.querySelector('.seg[data-idx="' + idx + '"]');
    if (seg) {
      seg.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }

  function _fmtTime(sec) {
    if (!sec || isNaN(sec)) return "0:00";
    var m = Math.floor(sec / 60);
    var s = Math.floor(sec % 60);
    return m + ":" + (s < 10 ? "0" : "") + s;
  }

  function _t(key) {
    if (typeof i18n === "function") return i18n(key);
    if (typeof window._i18n_data === "object" && window._i18n_data[key]) return window._i18n_data[key];
    var defaults = {
      "player.play": "Odtwarzaj / Pauza",
      "player.back5": "Cofnij 5s",
      "player.fwd5": "Do przodu 5s",
    };
    return defaults[key] || key;
  }

  // Expose
  window.AudioPlayer = AudioPlayer;
})();
