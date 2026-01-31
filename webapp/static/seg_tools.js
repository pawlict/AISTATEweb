/**
 * seg_tools.js — Shared UX enhancements for Transcription & Diarization pages
 *
 * Features:
 *   1. Text search with highlighting & prev/next navigation
 *   2. Click-on-segment → jump audio to that position (master player logic)
 *   3. Real audio waveform navigation map (Web Audio API amplitude)
 *   4. Merge / split segments
 *
 * Usage:
 *   segTools.init({ page, blocksId, getSegments, setSegments, getPlayer, onChanged });
 */
(function () {
  "use strict";

  /* =========================================================
   *  CONFIG — set by init()
   * ========================================================= */
  var CFG = null;
  var _waveformPeaks = null;   // Float32Array of peak amplitudes
  var _waveformDuration = 0;   // duration in seconds from decoded audio

  function _seg() { return CFG && CFG.getSegments ? CFG.getSegments() : []; }
  function _player() { return CFG && CFG.getPlayer ? CFG.getPlayer() : null; }
  function _blocksEl() { return CFG ? document.getElementById(CFG.blocksId) : null; }
  function _changed() { if (CFG && CFG.onChanged) CFG.onChanged(); }

  /** Is the main player currently playing? */
  function _isMainPlaying() {
    var p = _player();
    return p && typeof p.isPlaying === "function" && p.isPlaying();
  }

  /* =========================================================
   *  1. TEXT SEARCH
   * ========================================================= */
  var _searchState = { query: "", hits: [], current: -1 };

  function _buildSearchBar() {
    var bar = document.createElement("div");
    bar.className = "seg-search-bar";
    bar.innerHTML =
      '<div class="seg-search-inner">' +
      (typeof aiIcon === "function" ? aiIcon("search", 16) : "") +
      '<input class="seg-search-input" type="text" placeholder="' + _t("search.placeholder") + '" />' +
      '<span class="seg-search-count"></span>' +
      '<button class="seg-search-prev" title="' + _t("search.prev") + '">&lsaquo;</button>' +
      '<button class="seg-search-next" title="' + _t("search.next") + '">&rsaquo;</button>' +
      '<button class="seg-search-close" title="' + _t("search.close") + '">&times;</button>' +
      "</div>";
    return bar;
  }

  function _insertSearchBar() {
    var blocksEl = _blocksEl();
    if (!blocksEl) return null;
    var existing = blocksEl.parentNode.querySelector(".seg-search-bar");
    if (existing) return existing;

    var bar = _buildSearchBar();
    blocksEl.parentNode.insertBefore(bar, blocksEl);

    var input = bar.querySelector(".seg-search-input");
    var countEl = bar.querySelector(".seg-search-count");

    input.addEventListener("input", function () {
      _doSearch(input.value, countEl);
    });
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { e.preventDefault(); e.shiftKey ? _searchPrev(countEl) : _searchNext(countEl); }
      if (e.key === "Escape") { _closeSearch(); }
    });
    bar.querySelector(".seg-search-prev").addEventListener("click", function () { _searchPrev(countEl); });
    bar.querySelector(".seg-search-next").addEventListener("click", function () { _searchNext(countEl); });
    bar.querySelector(".seg-search-close").addEventListener("click", function () { _closeSearch(); });

    return bar;
  }

  function _doSearch(query, countEl) {
    _clearHighlights();
    _searchState.query = (query || "").toLowerCase().trim();
    _searchState.hits = [];
    _searchState.current = -1;

    if (!_searchState.query) {
      if (countEl) countEl.textContent = "";
      return;
    }

    var segs = _seg();
    var blocksEl = _blocksEl();
    if (!blocksEl) return;

    for (var i = 0; i < segs.length; i++) {
      var text = (segs[i].text || "").toLowerCase();
      if (text.indexOf(_searchState.query) !== -1) {
        _searchState.hits.push(i);
        var segEl = blocksEl.querySelector('.seg[data-idx="' + i + '"]');
        if (segEl) {
          segEl.classList.add("seg-search-hit");
          var textDiv = segEl.querySelector(".seg-text");
          if (textDiv) _highlightInElement(textDiv, _searchState.query);
        }
      }
    }

    if (countEl) {
      countEl.textContent = _searchState.hits.length > 0
        ? "0 / " + _searchState.hits.length
        : _t("search.no_results");
    }

    if (_searchState.hits.length > 0) {
      _searchState.current = 0;
      _goToHit(countEl);
    }
  }

  function _highlightInElement(el, q) {
    var html = el.textContent;
    var lower = html.toLowerCase();
    var result = "";
    var pos = 0;
    var idx;
    while ((idx = lower.indexOf(q, pos)) !== -1) {
      result += _escHtml(html.slice(pos, idx));
      result += '<mark class="seg-search-mark">' + _escHtml(html.slice(idx, idx + q.length)) + "</mark>";
      pos = idx + q.length;
    }
    result += _escHtml(html.slice(pos));
    el.innerHTML = result;
  }

  function _escHtml(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function _clearHighlights() {
    var blocksEl = _blocksEl();
    if (!blocksEl) return;
    var hits = blocksEl.querySelectorAll(".seg-search-hit");
    for (var i = 0; i < hits.length; i++) hits[i].classList.remove("seg-search-hit");
    var active = blocksEl.querySelectorAll(".seg-search-active");
    for (var j = 0; j < active.length; j++) active[j].classList.remove("seg-search-active");
    var marks = blocksEl.querySelectorAll(".seg-text");
    for (var k = 0; k < marks.length; k++) {
      if (marks[k].querySelector("mark")) {
        marks[k].textContent = marks[k].textContent;
      }
    }
  }

  function _goToHit(countEl) {
    var blocksEl = _blocksEl();
    if (!blocksEl || !_searchState.hits.length) return;

    var prev = blocksEl.querySelector(".seg-search-active");
    if (prev) prev.classList.remove("seg-search-active");

    var idx = _searchState.hits[_searchState.current];
    var segEl = blocksEl.querySelector('.seg[data-idx="' + idx + '"]');
    if (segEl) {
      segEl.classList.add("seg-search-active");
      segEl.scrollIntoView({ behavior: "smooth", block: "center" });
    }

    if (countEl) {
      countEl.textContent = (_searchState.current + 1) + " / " + _searchState.hits.length;
    }
  }

  function _searchNext(countEl) {
    if (!_searchState.hits.length) return;
    _searchState.current = (_searchState.current + 1) % _searchState.hits.length;
    _goToHit(countEl);
  }

  function _searchPrev(countEl) {
    if (!_searchState.hits.length) return;
    _searchState.current = (_searchState.current - 1 + _searchState.hits.length) % _searchState.hits.length;
    _goToHit(countEl);
  }

  function _closeSearch() {
    _clearHighlights();
    _searchState = { query: "", hits: [], current: -1 };
    var bar = document.querySelector(".seg-search-bar");
    if (bar) {
      bar.querySelector(".seg-search-input").value = "";
      bar.querySelector(".seg-search-count").textContent = "";
    }
  }

  function openSearch() {
    var bar = _insertSearchBar();
    if (bar) {
      bar.style.display = "";
      var input = bar.querySelector(".seg-search-input");
      if (input) input.focus();
    }
  }

  /* =========================================================
   *  2. CLICK-ON-SEGMENT → JUMP AUDIO (master player)
   * ========================================================= */
  function _bindClickToSeek() {
    var blocksEl = _blocksEl();
    if (!blocksEl || blocksEl._segToolsClickBound) return;
    blocksEl._segToolsClickBound = true;

    blocksEl.addEventListener("click", function (e) {
      var target = e.target;
      if (!target) return;
      if (target.closest(".seg-editor")) return;
      if (target.closest(".seg-note-icon")) return;
      if (target.closest(".seg-audio-btn")) return;
      if (target.closest(".seg-actions")) return;
      if (target.tagName === "BUTTON" || target.tagName === "INPUT" || target.tagName === "TEXTAREA") return;

      var segEl = target.closest(".seg");
      if (!segEl) return;

      var idx = parseInt(segEl.getAttribute("data-idx") || "-1", 10);
      if (idx < 0) return;

      var segs = _seg();
      if (idx >= segs.length) return;

      var player = _player();
      if (player && player.audio) {
        // LPM click always seeks to segment start and starts main player
        player.seekTo(segs[idx].start);
        player.play();
      }
    });
  }

  /* =========================================================
   *  3. REAL AUDIO WAVEFORM MAP (Web Audio API)
   * ========================================================= */

  /** Fetch and decode audio, extract peak amplitudes */
  function _loadWaveformData(callback) {
    if (_waveformPeaks) { callback(_waveformPeaks, _waveformDuration); return; }

    var player = _player();
    if (!player || !player.audio || !player.audio.src) return;

    var url = player.audio.src;
    var xhr = new XMLHttpRequest();
    xhr.open("GET", url, true);
    xhr.responseType = "arraybuffer";
    xhr.onload = function () {
      if (xhr.status !== 200) return;
      try {
        var audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        audioCtx.decodeAudioData(xhr.response, function (buffer) {
          var rawData = buffer.getChannelData(0); // mono or left channel
          var numPeaks = 800; // match canvas width
          var blockSize = Math.floor(rawData.length / numPeaks);
          var peaks = new Float32Array(numPeaks);

          for (var i = 0; i < numPeaks; i++) {
            var start = i * blockSize;
            var max = 0;
            for (var j = 0; j < blockSize; j++) {
              var abs = Math.abs(rawData[start + j] || 0);
              if (abs > max) max = abs;
            }
            peaks[i] = max;
          }

          _waveformPeaks = peaks;
          _waveformDuration = buffer.duration;
          audioCtx.close().catch(function(){});
          callback(peaks, buffer.duration);
        }, function () {
          console.warn("seg_tools: failed to decode audio for waveform");
        });
      } catch (e) {
        console.warn("seg_tools: Web Audio API error:", e);
      }
    };
    xhr.onerror = function () {
      console.warn("seg_tools: failed to fetch audio for waveform");
    };
    xhr.send();
  }

  function _buildSegmentMap() {
    var segs = _seg();
    if (!segs.length) return;

    var container = document.getElementById(CFG.blocksId);
    if (!container) return;

    var parent = container.parentNode;
    var existing = parent.querySelector(".seg-map");
    if (existing) existing.remove();

    var map = document.createElement("div");
    map.className = "seg-map";

    var canvas = document.createElement("canvas");
    canvas.className = "seg-map-canvas";
    canvas.width = 800;
    canvas.height = 64;
    map.appendChild(canvas);

    var playhead = document.createElement("div");
    playhead.className = "seg-map-playhead";
    map.appendChild(playhead);

    parent.insertBefore(map, container);

    // Try real waveform first, fallback to pseudo-waveform
    _loadWaveformData(function (peaks, duration) {
      _drawRealWaveform(canvas, peaks, duration, segs);
      _bindMapEvents(map, canvas, segs, duration, playhead);
    });

    // Draw pseudo-waveform immediately as placeholder
    var totalDur = 0;
    for (var i = 0; i < segs.length; i++) {
      if (segs[i].end > totalDur) totalDur = segs[i].end;
    }
    if (totalDur > 0 && !_waveformPeaks) {
      _drawPseudoWaveform(canvas, segs, totalDur);
      _bindMapEvents(map, canvas, segs, totalDur, playhead);
    } else if (_waveformPeaks) {
      // Already have peaks cached — draw immediately
      _drawRealWaveform(canvas, _waveformPeaks, _waveformDuration, segs);
      _bindMapEvents(map, canvas, segs, _waveformDuration, playhead);
    }
  }

  /** Draw real waveform from decoded audio peaks, colored by speaker segments */
  function _drawRealWaveform(canvas, peaks, duration, segs) {
    var ctx = canvas.getContext("2d");
    var W = canvas.width;
    var H = canvas.height;
    ctx.clearRect(0, 0, W, H);

    // Background
    ctx.fillStyle = "rgba(15,23,42,0.03)";
    ctx.fillRect(0, 0, W, H);

    if (!peaks || !peaks.length || duration <= 0) return;

    // Build speaker color map
    var colors = [
      [16, 150, 244],  // sky
      [41, 70, 183],   // blue
      [132, 38, 164],  // purple
      [112, 201, 246], // cyan
      [13, 19, 80],    // navy
      [210, 214, 250]  // ice
    ];
    var speakerMap = {};
    var colorIdx = 0;
    for (var s = 0; s < segs.length; s++) {
      var spk = segs[s].speaker || "__default__";
      if (!speakerMap[spk]) {
        speakerMap[spk] = colors[colorIdx % colors.length];
        colorIdx++;
      }
    }

    // For each peak column, determine which segment it belongs to
    var midY = H / 2;
    var barW = 1; // 1px per peak column

    for (var i = 0; i < peaks.length; i++) {
      var t = (i / peaks.length) * duration; // time for this column
      var amp = peaks[i];

      // Find segment at this time
      var segSpeaker = null;
      for (var si = 0; si < segs.length; si++) {
        if (t >= segs[si].start && t < segs[si].end) {
          segSpeaker = segs[si].speaker || "__default__";
          break;
        }
      }

      // Height proportional to amplitude (centered vertically)
      var barH = Math.max(1, amp * (H - 4));
      var y = midY - barH / 2;

      // Color: segment speaker color, or dim gray if between segments
      var rgb;
      if (segSpeaker && speakerMap[segSpeaker]) {
        rgb = speakerMap[segSpeaker];
        ctx.fillStyle = "rgba(" + rgb[0] + "," + rgb[1] + "," + rgb[2] + ",0.75)";
      } else {
        ctx.fillStyle = "rgba(150,150,150,0.25)";
      }

      ctx.fillRect(i * barW, y, barW, barH);
    }

    // Segment boundary lines
    for (var b = 0; b < segs.length; b++) {
      var x = Math.round((segs[b].start / duration) * W);
      if (x > 0 && x < W) {
        ctx.fillStyle = "rgba(255,255,255,0.5)";
        ctx.fillRect(x, 0, 1, H);
      }
    }
  }

  /** Fallback pseudo-waveform (text-length based) while real one loads */
  function _drawPseudoWaveform(canvas, segs, totalDur) {
    var ctx = canvas.getContext("2d");
    var W = canvas.width;
    var H = canvas.height;
    ctx.clearRect(0, 0, W, H);

    ctx.fillStyle = "rgba(15,23,42,0.03)";
    ctx.fillRect(0, 0, W, H);

    var colors = [
      "rgba(16,150,244,0.35)",
      "rgba(41,70,183,0.35)",
      "rgba(132,38,164,0.3)",
      "rgba(112,201,246,0.35)"
    ];
    var speakerMap = {};
    var ci = 0;

    for (var i = 0; i < segs.length; i++) {
      var seg = segs[i];
      var x0 = (seg.start / totalDur) * W;
      var x1 = (seg.end / totalDur) * W;
      var w = Math.max(2, x1 - x0);
      var spk = seg.speaker || "";
      if (spk && !speakerMap[spk]) { speakerMap[spk] = colors[ci++ % colors.length]; }
      ctx.fillStyle = spk ? speakerMap[spk] : colors[0];

      var textLen = (seg.text || "").length;
      var h = Math.max(8, Math.min(H - 4, 10 + (textLen / 3)));
      ctx.fillRect(x0, (H - h) / 2, w, h);
    }
  }

  function _bindMapEvents(mapEl, canvas, segs, totalDur, playhead) {
    if (mapEl._segToolsMapBound) return;
    mapEl._segToolsMapBound = true;

    mapEl.addEventListener("click", function (e) {
      var rect = canvas.getBoundingClientRect();
      var pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
      var time = pct * totalDur;

      var player = _player();
      if (player && player.audio) {
        player.seekTo(time);
        player.play();
      }
    });

    mapEl.addEventListener("mousemove", function (e) {
      var rect = canvas.getBoundingClientRect();
      var pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
      mapEl.title = _fmtTime(pct * totalDur);
    });

    // Playhead animation
    function updatePlayhead() {
      var player = _player();
      if (player && player.audio && totalDur > 0) {
        var pct = (player.audio.currentTime || 0) / totalDur;
        playhead.style.left = (pct * 100) + "%";
        playhead.style.display = player.audio.paused ? "none" : "";
      }
      requestAnimationFrame(updatePlayhead);
    }
    requestAnimationFrame(updatePlayhead);
  }

  /* =========================================================
   *  4. MERGE / SPLIT SEGMENTS
   * ========================================================= */
  function _addSegmentActions() {
    var blocksEl = _blocksEl();
    if (!blocksEl || blocksEl._segToolsActionsBound) return;
    blocksEl._segToolsActionsBound = true;

    blocksEl.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-seg-action]");
      if (!btn) return;
      e.preventDefault();
      e.stopPropagation();

      var action = btn.getAttribute("data-seg-action");
      var idx = parseInt(btn.getAttribute("data-seg-idx") || "-1", 10);
      if (idx < 0) return;

      if (action === "merge-next") _mergeWithNext(idx);
      else if (action === "split") _splitSegment(idx);
    });
  }

  function _injectSegmentButtons() {
    var blocksEl = _blocksEl();
    if (!blocksEl) return;
    var segs = _seg();

    for (var i = 0; i < segs.length; i++) {
      var segEl = blocksEl.querySelector('.seg[data-idx="' + i + '"]');
      if (!segEl || segEl.querySelector(".seg-actions")) continue;

      var actions = document.createElement("div");
      actions.className = "seg-actions";

      if (i < segs.length - 1) {
        actions.innerHTML +=
          '<button class="seg-action-btn" data-seg-action="merge-next" data-seg-idx="' + i + '" title="' + _t("seg.merge") + '">' +
          '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M5 12h14M12 5l7 7-7 7"/></svg>' +
          " " + _t("seg.merge") +
          "</button>";
      }

      actions.innerHTML +=
        '<button class="seg-action-btn" data-seg-action="split" data-seg-idx="' + i + '" title="' + _t("seg.split") + '">' +
        '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M12 3v18M5 12h14"/></svg>' +
        " " + _t("seg.split") +
        "</button>";

      segEl.appendChild(actions);
    }
  }

  function _mergeWithNext(idx) {
    var segs = _seg();
    if (idx < 0 || idx >= segs.length - 1) return;

    var a = segs[idx];
    var b = segs[idx + 1];
    a.end = b.end;
    a.text = (a.text || "") + " " + (b.text || "");
    segs.splice(idx + 1, 1);

    if (CFG.setSegments) CFG.setSegments(segs);
    _changed();
    _afterRender();
  }

  function _splitSegment(idx) {
    var segs = _seg();
    if (idx < 0 || idx >= segs.length) return;

    var seg = segs[idx];
    var text = seg.text || "";
    var words = text.split(/\s+/);
    if (words.length < 2) return;

    var midWord = Math.ceil(words.length / 2);
    var textA = words.slice(0, midWord).join(" ");
    var textB = words.slice(midWord).join(" ");

    var dur = seg.end - seg.start;
    var ratio = textA.length / Math.max(1, text.length);
    var midTime = Math.round((seg.start + dur * ratio) * 1000) / 1000;

    segs.splice(idx, 1,
      { start: seg.start, end: midTime, text: textA, speaker: seg.speaker || null },
      { start: midTime, end: seg.end, text: textB, speaker: seg.speaker || null }
    );

    if (CFG.setSegments) CFG.setSegments(segs);
    _changed();
    _afterRender();
  }

  /* =========================================================
   *  HELPERS
   * ========================================================= */
  function _fmtTime(sec) {
    if (!sec || isNaN(sec)) return "0:00";
    var m = Math.floor(sec / 60);
    var s = Math.floor(sec % 60);
    return m + ":" + (s < 10 ? "0" : "") + s;
  }

  function _t(key) {
    var map = {
      "search.placeholder": "Szukaj w tekście…",
      "search.prev": "Poprzedni",
      "search.next": "Następny",
      "search.close": "Zamknij",
      "search.no_results": "Brak wyników",
      "seg.merge": "Połącz",
      "seg.split": "Podziel"
    };
    if (typeof window.t === "function") {
      var v = window.t("segtools." + key);
      if (v !== "segtools." + key) return v;
    }
    return map[key] || key;
  }

  /* =========================================================
   *  POST-RENDER HOOK
   * ========================================================= */
  function _afterRender() {
    _bindClickToSeek();
    _addSegmentActions();
    _injectSegmentButtons();
    _buildSegmentMap();
    if (_searchState.query) {
      var bar = document.querySelector(".seg-search-bar");
      var countEl = bar ? bar.querySelector(".seg-search-count") : null;
      _doSearch(_searchState.query, countEl);
    }
  }

  /* =========================================================
   *  PUBLIC API
   * ========================================================= */
  window.segTools = {
    init: function (config) {
      CFG = config;
      // Reset waveform cache when re-initialized (different page/project)
      _waveformPeaks = null;
      _waveformDuration = 0;
    },
    afterRender: _afterRender,
    openSearch: openSearch,
    mergeWithNext: _mergeWithNext,
    splitSegment: _splitSegment,
    /** Check if main player is currently playing (used by pages for hover logic) */
    isMainPlaying: _isMainPlaying
  };
})();
