/**
 * icons.js — AISTATE Digital Brush SVG Icon Library
 *
 * Centralised icon definitions using AISTATE brand palette:
 *   navy #0d1350 · blue #2946b7 · sky #1096f4
 *   cyan #70c9f6 · purple #8426a4 · ice #d2d6fa
 *
 * Usage:
 *   aiIcon("play")                 → returns SVG string (18×18)
 *   aiIcon("play", 24)             → custom size
 *   aiIcon("play", 16, "#fff")     → custom colour override
 */
(function () {
  "use strict";

  /* ---- gradient defs (injected once) ---- */
  var _defsInjected = false;
  var DEFS_ID = "ai-icon-defs";
  var DEFS_SVG =
    '<svg xmlns="http://www.w3.org/2000/svg" style="position:absolute;width:0;height:0;overflow:hidden" aria-hidden="true">' +
    "<defs>" +
    '<linearGradient id="ig-sky-purple" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#1096f4"/><stop offset="100%" stop-color="#8426a4"/></linearGradient>' +
    '<linearGradient id="ig-blue-cyan" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#2946b7"/><stop offset="100%" stop-color="#70c9f6"/></linearGradient>' +
    '<linearGradient id="ig-navy-sky" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#0d1350"/><stop offset="100%" stop-color="#1096f4"/></linearGradient>' +
    '<linearGradient id="ig-purple-ice" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#8426a4"/><stop offset="100%" stop-color="#d2d6fa"/></linearGradient>' +
    '<linearGradient id="ig-cyan-ice" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#70c9f6"/><stop offset="100%" stop-color="#d2d6fa"/></linearGradient>' +
    '<linearGradient id="ig-sky-cyan" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#1096f4"/><stop offset="100%" stop-color="#70c9f6"/></linearGradient>' +
    '<linearGradient id="ig-blue-purple" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#2946b7"/><stop offset="100%" stop-color="#8426a4"/></linearGradient>' +
    "</defs></svg>";

  function _ensureDefs() {
    if (_defsInjected) return;
    if (document.getElementById(DEFS_ID)) { _defsInjected = true; return; }
    var d = document.createElement("div");
    d.id = DEFS_ID;
    d.innerHTML = DEFS_SVG;
    document.body.insertBefore(d, document.body.firstChild);
    _defsInjected = true;
  }

  /* ---- helpers ---- */
  var S = 'stroke-linecap="round" stroke-linejoin="round"';
  // w=stroke-width
  function _w(n) { return 'stroke-width="' + (n||1.5) + '"'; }
  function _s(id) { return 'stroke="url(#ig-' + id + ')"'; }
  function _f(id) { return 'fill="url(#ig-' + id + ')"'; }
  function _sc(c) { return 'stroke="' + c + '"'; }
  function _fc(c) { return 'fill="' + c + '"'; }

  /* ---- icon paths ---- */
  var icons = {};

  /* ===== PLAYBACK ===== */
  icons.play = function () {
    return '<circle cx="12" cy="12" r="10" ' + _s("blue-cyan") + " " + _w(1.4) + ' fill="none"/>' +
           '<polygon points="9.5,7 18,12 9.5,17" ' + _f("blue-cyan") + "/>";
  };
  icons.pause = function () {
    return '<circle cx="12" cy="12" r="10" ' + _s("blue-cyan") + " " + _w(1.4) + ' fill="none"/>' +
           '<rect x="8.5" y="7" width="2.5" height="10" rx="1" ' + _f("blue-cyan") + "/>" +
           '<rect x="13" y="7" width="2.5" height="10" rx="1" ' + _f("blue-cyan") + "/>";
  };
  icons.stop = function () {
    return '<circle cx="12" cy="12" r="10" ' + _s("blue-cyan") + " " + _w(1.4) + ' fill="none"/>' +
           '<rect x="8" y="8" width="8" height="8" rx="1.5" ' + _f("blue-cyan") + "/>";
  };
  icons.skip_back_3 = function () {
    return '<path d="M12 5a7 7 0 1 1-7 7" ' + _s("blue-cyan") + " " + _w(1.5) + ' ' + S + ' fill="none"/>' +
           '<path d="M5 8V5h3" ' + _s("blue-cyan") + " " + _w(1.5) + " " + S + ' fill="none"/>' +
           '<text x="12" y="13.5" text-anchor="middle" font-size="6" font-weight="700" ' + _f("sky-purple") + ' font-family="system-ui">3</text>';
  };
  icons.skip_fwd_3 = function () {
    return '<path d="M12 5a7 7 0 1 0 7 7" ' + _s("blue-cyan") + " " + _w(1.5) + ' ' + S + ' fill="none"/>' +
           '<path d="M19 8V5h-3" ' + _s("blue-cyan") + " " + _w(1.5) + " " + S + ' fill="none"/>' +
           '<text x="12" y="13.5" text-anchor="middle" font-size="6" font-weight="700" ' + _f("sky-purple") + ' font-family="system-ui">3</text>';
  };
  icons.skip_back_5 = function () {
    return '<path d="M12 5a7 7 0 1 1-7 7" ' + _s("blue-cyan") + " " + _w(1.5) + ' ' + S + ' fill="none"/>' +
           '<path d="M5 8V5h3" ' + _s("blue-cyan") + " " + _w(1.5) + " " + S + ' fill="none"/>' +
           '<text x="12" y="13.5" text-anchor="middle" font-size="6" font-weight="700" ' + _f("sky-purple") + ' font-family="system-ui">5</text>';
  };
  icons.skip_fwd_5 = function () {
    return '<path d="M12 5a7 7 0 1 0 7 7" ' + _s("blue-cyan") + " " + _w(1.5) + ' ' + S + ' fill="none"/>' +
           '<path d="M19 8V5h-3" ' + _s("blue-cyan") + " " + _w(1.5) + " " + S + ' fill="none"/>' +
           '<text x="12" y="13.5" text-anchor="middle" font-size="6" font-weight="700" ' + _f("sky-purple") + ' font-family="system-ui">5</text>';
  };
  icons.speed = function () {
    return '<path d="M4 16a8 8 0 0 1 16 0" ' + _s("blue-cyan") + " " + _w(1.5) + ' ' + S + ' fill="none"/>' +
           '<path d="M12 16l-2-6" ' + _s("sky-purple") + " " + _w(1.8) + ' ' + S + ' fill="none"/>' +
           '<circle cx="12" cy="16" r="1.5" ' + _f("sky-purple") + "/>" +
           '<path d="M6.5 14.5l-.8.3M8 10.5l-.6-.3M11 8.5v-.8M14 8.8l.3-.7M17.5 14.5l.8.3" ' + _s("blue-cyan") + ' ' + _w(1) + ' ' + S + ' fill="none" opacity=".5"/>';
  };

  /* ===== ACTIONS ===== */
  icons.save = function () {
    return '<path d="M5 3h11l4 4v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z" ' + _s("blue-cyan") + " " + _w(1.4) + ' fill="none"/>' +
           '<rect x="7" y="3" width="8" height="6" rx="1" ' + _s("blue-cyan") + ' ' + _w(1) + ' fill="none" opacity=".5"/>' +
           '<rect x="7" y="14" width="10" height="5" rx="1.5" ' + _f("blue-cyan") + ' opacity=".15"/>' +
           '<path d="M12 14v3M10.5 15.5l1.5 1.5 1.5-1.5" ' + _s("sky-purple") + " " + _w(1.2) + " " + S + ' fill="none"/>';
  };
  icons.delete = function () {
    return '<path d="M4 7h16" stroke="#b91c1c" ' + _w(1.4) + " " + S + ' fill="none"/>' +
           '<path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" stroke="#b91c1c" ' + _w(1.3) + ' fill="none"/>' +
           '<path d="M6 7l1 13a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-13" stroke="#b91c1c" ' + _w(1.4) + ' fill="none"/>' +
           '<path d="M10 11v5M14 11v5" stroke="#b91c1c" ' + _w(1.2) + " " + S + ' fill="none" opacity=".6"/>';
  };
  icons.edit = function () {
    return '<path d="M15.5 4.5l4 4L8 20H4v-4L15.5 4.5z" ' + _s("sky-purple") + " " + _w(1.4) + ' ' + S + ' fill="none"/>' +
           '<path d="M13 7l4 4" ' + _s("sky-purple") + " " + _w(1) + ' fill="none" opacity=".4"/>' +
           '<path d="M4 20h16" ' + _s("sky-purple") + " " + _w(1.2) + " " + S + ' fill="none" opacity=".3"/>';
  };
  icons.close = function () {
    return '<circle cx="12" cy="12" r="9" ' + _s("blue-cyan") + " " + _w(1.3) + ' fill="none" opacity=".3"/>' +
           '<path d="M8.5 8.5l7 7M15.5 8.5l-7 7" ' + _s("blue-cyan") + " " + _w(1.6) + " " + S + ' fill="none"/>';
  };
  icons.copy = function () {
    return '<rect x="8" y="8" width="12" height="13" rx="2" ' + _s("blue-cyan") + " " + _w(1.4) + ' fill="none"/>' +
           '<path d="M16 8V5a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h2" ' + _s("blue-cyan") + " " + _w(1.3) + ' fill="none" opacity=".5"/>' +
           '<path d="M11 13h6M11 16h4" ' + _s("sky-cyan") + " " + _w(1) + " " + S + ' fill="none" opacity=".5"/>';
  };
  icons.generate = function () {
    return '<path d="M5 17L12 4l7 13H5z" ' + _s("sky-purple") + " " + _w(1.4) + ' ' + S + ' ' + _f("sky-purple") + ' fill-opacity=".1"/>' +
           '<path d="M12 10v4" ' + _s("sky-purple") + " " + _w(1.5) + " " + S + ' fill="none"/>' +
           '<circle cx="12" cy="8" r="1" ' + _f("sky-purple") + ' opacity=".8"/>' +
           '<path d="M9 20h6" ' + _s("sky-purple") + " " + _w(1.3) + " " + S + ' fill="none" opacity=".4"/>';
  };
  icons.refresh = function () {
    return '<path d="M4 12a8 8 0 0 1 14-5.3" ' + _s("sky-cyan") + " " + _w(1.5) + " " + S + ' fill="none"/>' +
           '<path d="M20 12a8 8 0 0 1-14 5.3" ' + _s("sky-purple") + " " + _w(1.5) + " " + S + ' fill="none"/>' +
           '<path d="M18 3v4h-4" ' + _s("sky-cyan") + " " + _w(1.5) + " " + S + ' fill="none"/>' +
           '<path d="M6 21v-4h4" ' + _s("sky-purple") + " " + _w(1.5) + " " + S + ' fill="none"/>';
  };
  icons.install = function () {
    return '<path d="M12 3v12" ' + _s("blue-cyan") + " " + _w(1.5) + " " + S + ' fill="none"/>' +
           '<path d="M8 11l4 4 4-4" ' + _s("blue-cyan") + " " + _w(1.5) + " " + S + ' fill="none"/>' +
           '<path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" ' + _s("sky-purple") + " " + _w(1.4) + " " + S + ' fill="none"/>';
  };
  icons.add = function () {
    return '<circle cx="12" cy="12" r="9" ' + _s("blue-cyan") + " " + _w(1.3) + ' fill="none"/>' +
           '<path d="M12 8v8M8 12h8" ' + _s("sky-purple") + " " + _w(1.5) + " " + S + ' fill="none"/>';
  };
  icons.stop_cancel = function () {
    return '<circle cx="12" cy="12" r="9" stroke="#b91c1c" ' + _w(1.4) + ' fill="#b91c1c" fill-opacity=".08"/>' +
           '<rect x="8" y="8" width="8" height="8" rx="1.5" fill="#b91c1c"/>';
  };
  icons.search = function () {
    return '<circle cx="10.5" cy="10.5" r="6.5" ' + _s("sky-purple") + " " + _w(1.5) + ' fill="none"/>' +
           '<path d="M15.5 15.5l5 5" ' + _s("sky-purple") + " " + _w(2) + " " + S + ' fill="none"/>';
  };

  /* ===== STATUS ===== */
  icons.success = function () {
    return '<circle cx="12" cy="12" r="9" stroke="#15803d" ' + _w(1.4) + ' fill="#15803d" fill-opacity=".08"/>' +
           '<path d="M7.5 12.5l3 3 6-6.5" stroke="#15803d" ' + _w(2) + " " + S + ' fill="none"/>';
  };
  icons.error = function () {
    return '<circle cx="12" cy="12" r="9" stroke="#b91c1c" ' + _w(1.4) + ' fill="#b91c1c" fill-opacity=".08"/>' +
           '<path d="M8.5 8.5l7 7M15.5 8.5l-7 7" stroke="#b91c1c" ' + _w(2) + " " + S + ' fill="none"/>';
  };
  icons.warning = function () {
    return '<path d="M12 3L2 20h20L12 3z" stroke="#d97706" ' + _w(1.4) + ' fill="#d97706" fill-opacity=".08" ' + S + '/>' +
           '<path d="M12 10v4" stroke="#d97706" ' + _w(2) + " " + S + ' fill="none"/>' +
           '<circle cx="12" cy="17" r="1" fill="#d97706"/>';
  };
  icons.loading = function () {
    return '<circle cx="12" cy="12" r="9" ' + _s("blue-cyan") + " " + _w(1.4) + ' fill="none" stroke-dasharray="4 3" opacity=".3">' +
           '<animateTransform attributeName="transform" type="rotate" from="0 12 12" to="360 12 12" dur="3s" repeatCount="indefinite"/></circle>' +
           '<path d="M12 3a9 9 0 0 1 9 9" ' + _s("sky-purple") + " " + _w(2) + " " + S + ' fill="none">' +
           '<animateTransform attributeName="transform" type="rotate" from="0 12 12" to="360 12 12" dur="1s" repeatCount="indefinite"/></path>';
  };
  icons.info_circle = function () {
    return '<circle cx="12" cy="12" r="9" ' + _s("blue-cyan") + " " + _w(1.4) + ' fill="none"/>' +
           '<circle cx="12" cy="8" r="1" ' + _f("blue-cyan") + "/>" +
           '<path d="M12 11v6" ' + _s("blue-cyan") + " " + _w(1.5) + " " + S + ' fill="none"/>';
  };

  /* ===== THEMATIC / SECTIONS ===== */
  icons.lightning = function () {
    return '<path d="M13 2L4 14h8l-1 8 9-12h-8l1-8z" ' + _s("sky-cyan") + " " + _w(1.5) + ' ' + S + ' ' + _f("sky-cyan") + ' fill-opacity=".12"/>';
  };
  icons.deep_search = function () {
    return '<circle cx="10.5" cy="10.5" r="6.5" ' + _s("sky-purple") + " " + _w(1.5) + ' fill="none"/>' +
           '<path d="M15.5 15.5l5 5" ' + _s("sky-purple") + " " + _w(2) + " " + S + ' fill="none"/>' +
           '<path d="M8 10h5M10.5 7.5v5" ' + _s("sky-purple") + " " + _w(1.2) + " " + S + ' fill="none" opacity=".5"/>';
  };
  icons.notes = function () {
    return '<path d="M6 3h9l5 5v11a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z" ' + _s("sky-purple") + " " + _w(1.4) + ' fill="none"/>' +
           '<path d="M15 3v5h5" ' + _s("sky-purple") + " " + _w(1.2) + ' fill="none" opacity=".5"/>' +
           '<path d="M8 12h8M8 15h5" ' + _s("sky-cyan") + " " + _w(1.2) + " " + S + ' fill="none" opacity=".5"/>' +
           '<path d="M7 9l2 1.5L11 8" ' + _s("sky-purple") + " " + _w(1.2) + " " + S + ' fill="none"/>';
  };
  icons.pin = function () {
    return '<path d="M9 3h6l1 7h-1l1 3H8l1-3H8L9 3z" ' + _s("sky-purple") + " " + _w(1.3) + ' ' + S + ' fill="none"/>' +
           '<path d="M12 13v6" ' + _s("sky-purple") + " " + _w(1.5) + " " + S + ' fill="none"/>';
  };
  icons.document = function () {
    return '<path d="M6 3h8l6 6v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z" ' + _s("blue-cyan") + " " + _w(1.4) + ' fill="none"/>' +
           '<path d="M14 3v6h6" ' + _s("blue-cyan") + " " + _w(1.2) + ' fill="none" opacity=".5"/>' +
           '<path d="M8 13h8M8 16h5" ' + _s("blue-cyan") + " " + _w(1.1) + " " + S + ' fill="none" opacity=".4"/>';
  };
  icons.folder = function () {
    return '<path d="M4 6a2 2 0 0 1 2-2h4l2 2h6a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6z" ' + _s("sky-cyan") + " " + _w(1.4) + ' fill="none"/>' +
           '<path d="M4 10h16" ' + _s("sky-cyan") + " " + _w(1) + ' fill="none" opacity=".3"/>';
  };
  icons.speaker = function () {
    return '<circle cx="12" cy="9" r="4" ' + _s("blue-cyan") + " " + _w(1.4) + ' fill="none"/>' +
           '<path d="M5 20c0-3 3-5.5 7-5.5s7 2.5 7 5.5" ' + _s("blue-cyan") + " " + _w(1.4) + " " + S + ' fill="none"/>' +
           '<path d="M16 6c.8.3 1.5 1 1.5 2M17.8 4.5c1 .4 2 1.4 2 2.8" ' + _s("sky-cyan") + " " + _w(1.2) + " " + S + ' fill="none" opacity=".5"/>';
  };
  icons.target = function () {
    return '<circle cx="12" cy="12" r="9" ' + _s("sky-purple") + " " + _w(1.3) + ' fill="none" opacity=".3"/>' +
           '<circle cx="12" cy="12" r="6" ' + _s("sky-purple") + " " + _w(1.3) + ' fill="none" opacity=".5"/>' +
           '<circle cx="12" cy="12" r="3" ' + _s("sky-purple") + " " + _w(1.3) + ' fill="none"/>' +
           '<circle cx="12" cy="12" r="1" ' + _f("sky-purple") + "/>";
  };
  icons.brain = function () {
    return '<path d="M12 3C8 3 5 5.5 5 9c0 2 .8 3.5 2 4.5L8 19h8l1-5.5c1.2-1 2-2.5 2-4.5 0-3.5-3-6-7-6z" ' + _s("sky-purple") + " " + _w(1.5) + ' ' + S + ' fill="none"/>' +
           '<path d="M9 19h6v1.5a1.5 1.5 0 0 1-1.5 1.5h-3a1.5 1.5 0 0 1-1.5-1.5V19z" ' + _s("sky-purple") + " " + _w(1.3) + ' fill="none"/>' +
           '<path d="M12 7v4M10 9h4" ' + _s("blue-cyan") + " " + _w(1.2) + " " + S + ' fill="none" opacity=".7"/>';
  };
  icons.vision = function () {
    return '<rect x="3" y="5" width="18" height="14" rx="2.5" ' + _s("blue-cyan") + " " + _w(1.4) + ' fill="none"/>' +
           '<circle cx="12" cy="12" r="3.5" ' + _s("sky-purple") + " " + _w(1.3) + ' fill="none"/>' +
           '<circle cx="12" cy="12" r="1.2" ' + _f("sky-purple") + "/>";
  };
  icons.finance = function () {
    return '<path d="M4 19h16" ' + _s("blue-cyan") + " " + _w(1.3) + " " + S + ' fill="none"/>' +
           '<path d="M4 19V9l4-3 4 5 4-6 4 4v10" ' + _s("sky-purple") + " " + _w(1.4) + " " + S + ' fill="none"/>' +
           '<path d="M4 19V9l4-3 4 5 4-6 4 4v10" ' + _f("sky-purple") + ' fill-opacity=".08"/>';
  };
  icons.wrench = function () {
    return '<path d="M14.7 6.3a7 7 0 0 0-1.3-.3c-1 0-1.9.3-2.6.8L6.5 11.1a2 2 0 0 0 0 2.8l3.6 3.6a2 2 0 0 0 2.8 0l4.3-4.3c.5-.7.8-1.6.8-2.6 0-.4-.1-.9-.3-1.3" ' + _s("sky-purple") + " " + _w(1.4) + ' ' + S + ' fill="none"/>' +
           '<path d="M16 2l2 2-4 4 2 2 4-4 2 2" ' + _s("blue-cyan") + " " + _w(1.3) + " " + S + ' fill="none"/>';
  };
  icons.user = function () {
    return '<circle cx="12" cy="12" r="10" ' + _s("blue-cyan") + " " + _w(1.3) + ' fill="none"/>' +
           '<circle cx="12" cy="9" r="3" ' + _s("blue-cyan") + " " + _w(1.4) + ' fill="none"/>' +
           '<path d="M6 19c0-3 2.7-5 6-5s6 2 6 5" ' + _s("blue-cyan") + " " + _w(1.4) + ' fill="none"/>';
  };
  icons.robot = function () {
    return '<rect x="5" y="5" width="14" height="12" rx="3" ' + _s("purple-ice") + " " + _w(1.4) + ' fill="none"/>' +
           '<circle cx="9" cy="10.5" r="1.5" ' + _f("sky-purple") + "/>" +
           '<circle cx="15" cy="10.5" r="1.5" ' + _f("sky-purple") + "/>" +
           '<path d="M9.5 14c1 1 4 1 5 0" ' + _s("purple-ice") + " " + _w(1.2) + " " + S + ' fill="none"/>' +
           '<path d="M8 5V3M16 5V3M12 17v3M10 20h4" ' + _s("purple-ice") + " " + _w(1.2) + " " + S + ' fill="none"/>';
  };
  icons.globe = function () {
    return '<circle cx="12" cy="12" r="9" ' + _s("sky-cyan") + " " + _w(1.4) + ' fill="none"/>' +
           '<ellipse cx="12" cy="12" rx="4" ry="9" ' + _s("sky-cyan") + " " + _w(1) + ' fill="none" opacity=".5"/>' +
           '<path d="M3 12h18M4 8h16M4 16h16" ' + _s("sky-cyan") + " " + _w(.8) + ' fill="none" opacity=".3"/>';
  };
  icons.check = function () {
    return '<path d="M5 12l5 5L19 7" stroke="#15803d" ' + _w(2.2) + " " + S + ' fill="none"/>';
  };
  icons.headphones = function () {
    return '<path d="M4 15v-3a8 8 0 0 1 16 0v3" ' + _s("blue-cyan") + " " + _w(1.4) + " " + S + ' fill="none"/>' +
           '<rect x="2" y="14" width="4" height="6" rx="1.5" ' + _s("blue-cyan") + " " + _w(1.3) + ' fill="none"/>' +
           '<rect x="18" y="14" width="4" height="6" rx="1.5" ' + _s("sky-purple") + " " + _w(1.3) + ' fill="none"/>';
  };
  icons.mic = function () {
    return '<rect x="9" y="2" width="6" height="10" rx="3" ' + _s("blue-cyan") + " " + _w(1.4) + ' fill="none"/>' +
           '<path d="M5 11a7 7 0 0 0 14 0" ' + _s("sky-purple") + " " + _w(1.4) + ' fill="none"/>' +
           '<path d="M12 18v3M9 21h6" ' + _s("sky-purple") + " " + _w(1.3) + " " + S + ' fill="none"/>';
  };
  icons.receipt = function () {
    return '<path d="M5 2h14v20l-2.5-2-2.5 2-2.5-2L9 22l-2.5-2L5 22V2z" ' + _s("blue-cyan") + " " + _w(1.4) + ' fill="none"/>' +
           '<path d="M8 7h8M8 11h6M8 15h4" ' + _s("sky-cyan") + " " + _w(1.2) + " " + S + ' fill="none" opacity=".5"/>';
  };
  icons.package = function () {
    return '<path d="M3 8l9-5 9 5v8l-9 5-9-5V8z" ' + _s("blue-cyan") + " " + _w(1.4) + ' ' + S + ' fill="none"/>' +
           '<path d="M3 8l9 5 9-5M12 13v9" ' + _s("sky-purple") + " " + _w(1) + ' fill="none" opacity=".4"/>';
  };
  icons.paperclip = function () {
    return '<path d="M16 6l-8.4 8.4a2.5 2.5 0 0 0 3.5 3.5L19.5 9.5a4 4 0 0 0-5.7-5.7L5.5 12.2a5.5 5.5 0 0 0 7.8 7.8L18 15.3" ' + _s("blue-cyan") + " " + _w(1.4) + " " + S + ' fill="none"/>';
  };
  icons.import = function () {
    return '<path d="M12 3v12" ' + _s("blue-cyan") + " " + _w(1.5) + " " + S + ' fill="none"/>' +
           '<path d="M8 11l4 4 4-4" ' + _s("blue-cyan") + " " + _w(1.5) + " " + S + ' fill="none"/>' +
           '<rect x="4" y="17" width="16" height="4" rx="1.5" ' + _s("sky-purple") + " " + _w(1.3) + ' fill="none" opacity=".5"/>';
  };
  icons.export = function () {
    return '<path d="M12 15V3" ' + _s("blue-cyan") + " " + _w(1.5) + " " + S + ' fill="none"/>' +
           '<path d="M8 7l4-4 4 4" ' + _s("blue-cyan") + " " + _w(1.5) + " " + S + ' fill="none"/>' +
           '<path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" ' + _s("sky-purple") + " " + _w(1.4) + " " + S + ' fill="none"/>';
  };
  /* Star rating — pass filled count (0-5) */
  icons.stars = function (filled) {
    filled = filled || 0;
    var out = "";
    for (var i = 0; i < 5; i++) {
      var x = 2.5 + i * 4;
      var clr = i < filled ? "#d97706" : "#cbd5e1";
      out += '<path d="M' + (x + 2) + ' 8l.6 1.9h2l-1.6 1.2.6 1.9-1.6-1.2-1.6 1.2.6-1.9L' + (x + .4) + ' 9.9h2z" fill="' + clr + '" stroke="none"/>';
    }
    return out;
  };

  /* ---- main API ---- */
  function aiIcon(name, size, colour) {
    _ensureDefs();
    size = size || 18;
    var fn = icons[name];
    if (!fn) return "<!-- unknown icon: " + name + " -->";
    var inner = fn();
    if (colour) {
      // override all gradient strokes/fills with solid colour
      inner = inner.replace(/url\(#ig-[^)]+\)/g, colour);
    }
    return '<svg viewBox="0 0 24 24" width="' + size + '" height="' + size + '" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" style="display:inline-block;vertical-align:middle">' + inner + "</svg>";
  }

  /* ---- auto-replace emojis on DOMContentLoaded ---- */
  var EMOJI_MAP = {
    "\uD83E\uDDE0": "brain",       // 🧠
    "\uD83D\uDE80": "generate",    // 🚀
    "\u26A1":       "lightning",    // ⚡
    "\uD83D\uDD0D": "deep_search", // 🔍
    "\uD83D\uDCBE": "save",        // 💾
    "\uD83D\uDCC1": "folder",      // 📁
    "\uD83D\uDCCE": "paperclip",   // 📎
    "\uD83C\uDFAF": "target",      // 🎯
    "\uD83D\uDCE5": "import",      // 📥
    "\u270D\uFE0F": "edit",        // ✍️
    "\uD83D\uDCCB": "copy",        // 📋
    "\u26D4":       "stop_cancel",  // ⛔
    "\uD83D\uDDD1": "delete",      // 🗑
    "\uD83D\uDDD1\uFE0F": "delete",// 🗑️
    "\u2715":       "close",        // ✕
    "\u2705":       "success",      // ✅
    "\u274C":       "error",        // ❌
    "\u26A0\uFE0F": "warning",     // ⚠️
    "\u231B":       "loading",      // ⏳
    "\uD83D\uDCDD": "notes",       // 📝
    "\uD83D\uDCCC": "pin",         // 📌
    "\uD83D\uDCE4": "export",      // 📤
    "\uD83D\uDC64": "user",        // 👤
    "\uD83E\uDD16": "robot",       // 🤖
    "\uD83C\uDF10": "globe",       // 🌐
    "\uD83C\uDF0D": "globe",       // 🌍
    "\uD83C\uDF99\uFE0F": "mic",   // 🎙️
    "\uD83C\uDF99": "mic",         // 🎙
    "\uD83D\uDCB0": "finance",     // 💰
    "\uD83D\uDD27": "wrench",      // 🔧
    "\u2795":       "add",          // ➕
    "\u2B07\uFE0F": "install",     // ⬇️
    "\u2139\uFE0F": "info_circle",  // ℹ️
    "\uD83D\uDCE6": "package",     // 📦
    "\uD83D\uDCF0": "receipt",     // 🧾 (close match)
    "\uD83E\uDDFE": "receipt",     // 🧾
    "\uD83C\uDFA7": "headphones",  // 🎧
    "\uD83C\uDFA4": "speaker",     // 🎤
    "\uD83D\uDD2C": "deep_search", // 🔬
    "\uD83D\uDCC4": "document",    // 📄
    "\uD83D\uDDBC\uFE0F": "vision",// 🖼️
    "\u2712\uFE0F": "edit",        // ✏️
    "\u270F\uFE0F": "edit",        // ✏️
    "\uD83D\uDCAC": "robot",       // 💬 (chat welcome)
    "\u25B6\uFE0F": "play",        // ▶️ (also used as icon in some places)
    "\u23F8\uFE0F": "pause",       // ⏸️
    "\u23F9\uFE0F": "stop",        // ⏹️
    "\u23EA":       "skip_back_3", // ⏪
    "\u23E9":       "skip_fwd_3",  // ⏩
    "\u25C0\uFE0F": "skip_back_3"  // ◀️
  };

  function _replaceEmojis() {
    _ensureDefs();
    // Walk text nodes in buttons, labels, headings, spans with data-i18n
    var selectors = "button, .btn, .h1, .h2, .h3, label, [data-i18n], .seg-editor-title, .chat-welcome-icon";
    var els = document.querySelectorAll(selectors);
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      // Skip if already processed
      if (el.getAttribute("data-icons-done")) continue;

      var html = el.innerHTML;
      var changed = false;
      for (var emoji in EMOJI_MAP) {
        if (html.indexOf(emoji) !== -1) {
          var iconName = EMOJI_MAP[emoji];
          var size = 16;
          // Bigger icons for headers
          if (el.classList.contains("h1") || el.classList.contains("h2") || el.classList.contains("h3")) size = 18;
          if (el.classList.contains("chat-welcome-icon")) size = 40;
          html = html.split(emoji).join(aiIcon(iconName, size));
          changed = true;
        }
      }
      if (changed) {
        el.innerHTML = html;
        el.setAttribute("data-icons-done", "1");
      }
    }
  }

  // Run on DOM ready and expose for dynamic content
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", _replaceEmojis);
  } else {
    // defer slightly so all scripts load
    setTimeout(_replaceEmojis, 0);
  }

  // expose
  window.aiIcon = aiIcon;
  window.AI_ICONS = icons;
  window.aiReplaceEmojis = _replaceEmojis;
})();
