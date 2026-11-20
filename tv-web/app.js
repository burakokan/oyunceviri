/* Oyun Çeviri TV app for Samsung (Tizen) and LG (webOS). The same page also runs in a normal browser for
 * testing (index.html?pc=127.0.0.1). ES5 only: 2017 Samsung TVs have an old browser engine.
 * The PC sends: line (subtitle), clear, style, screen (menu / quest translation boxes), regions (hint box / phone
 * messages: one box per area, "⟦1⟧" in the text is a button icon sent as a PNG). */
(function () {
  "use strict";
  var VERSION = "1.6-web";
  var PORT = 8765;
  var PLATFORM = window.tizen ? "tizen"
    : (window.PalmSystem || window.webOSSystem || /Web0S|webOS/i.test(navigator.userAgent)) ? "webos" : "browser";

  var DEFAULT_STYLE = {
    textSize: 30, bold: true, textColor: "#FFFFFF", speakerShow: true, speakerColor: "#FFD54F",
    outline: 3, outlineColor: "#000000", shadow: 6, bgColor: "#000000", bgOpacity: 55, bgRadius: 12,
    bgPadding: 14, position: "bottom", offset: 6, align: "center", xOffset: 0, maxWidth: 80, showEnglish: false,
    englishSize: 60, englishColor: "#B0BEC5", lingerMs: 400, prevHoldMs: 2500, readBaseMs: 1500,
    readPerCharMs: 50, readMaxMs: 5000, lineSpacing: 115, uppercase: false, speakerColors: true, maxLines: 4,
    provisional: true, prevSmaller: false, speakerOwnLine: false, stackPrevious: false
  };

  function $(id) { return document.getElementById(id); }
  function load(key, fallback) {
    try { var v = localStorage.getItem("oc." + key); return v === null ? fallback : JSON.parse(v); }
    catch (e) { return fallback; }
  }
  function save(key, value) { try { localStorage.setItem("oc." + key, JSON.stringify(value)); } catch (e) { /* full */ } }
  function merge(a, b) { var o = {}, k; for (k in a) { o[k] = a[k]; } for (k in b || {}) { o[k] = b[k]; } return o; }
  function query(name) {
    var m = new RegExp("[?&]" + name + "=([^&]*)").exec(location.search);
    return m ? decodeURIComponent(m[1]) : null;
  }

  var style = merge(DEFAULT_STYLE, load("style", {}));
  var hdmi = load("hdmi", 1);
  var scale = 1920 / 960;            // Android sizes are in dp on a 960 dp wide TV screen

  // ---------------------------------------------------------------- PS5 picture (HDMI input)

  function showHdmi(n) {
    hdmi = n;
    save("hdmi", n);
    $("hdmiNow").textContent = "HDMI " + n;
    if (PLATFORM === "tizen") {
      if (!window.tizen || !tizen.tvwindow) { diag("HDMI HATA: bu TV tizen.tvwindow desteklemiyor"); return; }
      /* The source object comes from the TV itself (VIDEOSOURCE) and the window is shown BEHIND the page over the
       * whole surface ("100%"), the way CouchSubs (AGPL-3.0) does it. A hand-made {type, number} source and a px
       * rectangle without BEHIND gave a black page on some Samsung TVs (found and fixed on a user's TV). */
      var open = function (source) {
        try {
          diag("HDMI " + n + ": kaynak seçiliyor…");
          tizen.tvwindow.setSource(source, function () {
            diag("HDMI " + n + ": kaynak seçildi, pencere açılıyor…");
            try {
              tizen.tvwindow.show(function () { diag("HDMI " + n + ": pencere açık (görüntü gelmeli)"); },
                function (e) { diag("HDMI HATA show(): " + (e && (e.name + " " + e.message))); },
                ["0", "0", "100%", "100%"], "MAIN", "BEHIND");
            } catch (e) { diag("HDMI HATA show() çağrısı: " + e.name + " " + e.message); }
          }, function (e) { diag("HDMI HATA setSource(" + n + "): " + (e && (e.name + " " + e.message))); });
        } catch (e) { diag("HDMI HATA: " + (e && (e.name + " " + e.message))); }
      };
      try {
        tizen.systeminfo.getPropertyValue("VIDEOSOURCE", function (info) {
          var all = ((info && info.connected) || []).concat((info && info.disconnected) || []), found = null, i;
          for (i = 0; i < all.length; i++) { if (all[i].type === "HDMI" && all[i].number === n) { found = all[i]; } }
          if (!found) {
            var names = [];
            for (i = 0; i < all.length; i++) { names.push(all[i].type + all[i].number); }
            diag("HDMI HATA: TV'de HDMI " + n + " yok. TV'nin kaynakları: " + (names.join(" ") || "boş"));
            return;
          }
          open(found);
        }, function (e) { diag("VIDEOSOURCE okunamadı, elle deneniyor: " + (e && e.message)); open({ type: "HDMI", number: n }); });
      } catch (e) { open({ type: "HDMI", number: n }); }
    } else if (PLATFORM === "webos") {
      var v = $("hdmi");
      v.innerHTML = "";
      var s = document.createElement("source");
      s.setAttribute("src", "ext://hdmi:" + n);
      s.setAttribute("type", "service/webos-external");
      v.appendChild(s);
      v.style.display = "block";
      try { v.load(); v.play(); } catch (e) { /* plays by itself */ }
    } else {
      $("placeholder").style.display = "block";
    }
  }

  // ---------------------------------------------------------------- finding the PC

  var ws = null, host = null, searching = false;

  function ownAddress(done) {
    if (PLATFORM === "tizen") {
      var tried = 0;
      ["ETHERNET_NETWORK", "WIFI_NETWORK"].forEach(function (kind) {
        try {
          tizen.systeminfo.getPropertyValue(kind, function (net) {
            tried++;
            if (net && net.ipAddress && net.ipAddress !== "0.0.0.0") { done(net.ipAddress); done = function () {}; }
            else if (tried === 2) { done(null); }
          }, function () { tried++; if (tried === 2) { done(null); } });
        } catch (e) { tried++; if (tried === 2) { done(null); } }
      });
    } else if (PLATFORM === "webos" && window.PalmServiceBridge) {
      var bridge = new PalmServiceBridge();
      bridge.onservicecallback = function (raw) {
        var s = {}; try { s = JSON.parse(raw); } catch (e) { /* bad answer */ }
        var net = (s.wired && s.wired.ipAddress) ? s.wired : s.wifi;
        done(net && net.ipAddress ? net.ipAddress : null);
      };
      bridge.call("luna://com.webos.service.connectionmanager/getStatus", "{}");
    } else {
      done(/^\d+\.\d+\.\d+\.\d+$/.test(location.hostname) ? location.hostname : null);
    }
  }

  function launchHost() {
    try {
      if (PLATFORM === "tizen") {
        var data = tizen.application.getCurrentApplication().getRequestedAppControl().appControl.data;
        for (var i = 0; i < data.length; i++) { if (data[i].key === "pc") { return data[i].value[0]; } }
      } else if (PLATFORM === "webos") {
        var p = JSON.parse((window.webOSSystem || window.PalmSystem).launchParams || "{}");
        if (p.pc) { return p.pc; }
      }
    } catch (e) { /* started without parameters */ }
    return null;
  }

  /* Try one address; ok(socket) when the Oyun Çeviri server answers. */
  function probe(address, ok, fail) {
    var done = false, sock;
    try { sock = new WebSocket("ws://" + (address.indexOf(":") > 0 ? address : address + ":" + PORT)); }
    catch (e) { fail(); return; }
    var timer = setTimeout(function () { if (!done) { done = true; try { sock.close(); } catch (e) { /* */ } fail(); } }, 1500);
    sock.onopen = function () { if (!done) { done = true; clearTimeout(timer); ok(sock); } else { sock.close(); } };
    sock.onerror = function () { if (!done) { done = true; clearTimeout(timer); fail(); } };
  }

  function search() {
    if (searching) { return; }
    searching = true;
    setState("Bilgisayar aranıyor…", false);
    // The PC that installed the app wrote its address into it (pc.js): tried first, so no scan is needed.
    var first = [query("pc"), launchHost(), load("host", null)].concat(window.OC_PC || [])
      .filter(function (x, i, all) { return !!x && all.indexOf(x) === i; });
    tryList(first, function () {
      ownAddress(function (ip) {
        if (!ip) { searching = false; setState("TV'nin ağ adresi alınamadı. Ağ bağlantısını kontrol et.", false); retryLater(); return; }
        var prefix = ip.split(".").slice(0, 3).join(".");
        setState("Bilgisayar aranıyor (" + prefix + ".x)…", false);
        // The usual home-network addresses first (routers hand out .2-.50 and .100-.150), then the rest.
        var list = [], order = [], i;
        for (i = 2; i <= 50; i++) { order.push(i); }
        for (i = 100; i <= 150; i++) { order.push(i); }
        for (i = 1; i < 255; i++) { if (order.indexOf(i) < 0) { order.push(i); } }
        for (i = 0; i < order.length; i++) { if (prefix + "." + order[i] !== ip) { list.push(prefix + "." + order[i]); } }
        scan(list, function () { searching = false; setState("Bilgisayar bulunamadı. Bilgisayarda Oyun Çeviri açık mı?", false); retryLater(); });
      });
    });
  }

  function tryList(list, none) {
    if (!list.length) { none(); return; }
    probe(list[0], use, function () { tryList(list.slice(1), none); });
  }

  /* 40 addresses at a time; the first that answers wins. */
  function scan(list, none) {
    var next = 0, open = 0, found = false;
    function pump() {
      while (!found && open < 40 && next < list.length) {
        open++;
        (function (address) {
          probe(address, function (sock) {
            open--;
            if (found) { sock.close(); return; }
            found = true; use(sock);
          }, function () { open--; if (!found) { if (next >= list.length && open === 0) { none(); } else { pump(); } } });
        })(list[next++]);
      }
    }
    pump();
  }

  function retryLater() { setTimeout(search, 5000); }

  function use(sock) {
    searching = false;
    ws = sock;
    host = sock.url.replace(/^ws:\/\//, "").replace(/\/$/, "");
    save("host", host.split(":")[0]);
    setState("Bağlandı: " + host.split(":")[0], true);
    sock.send(JSON.stringify({ type: "hello", version: VERSION + "-" + PLATFORM, style: style }));
    sock.onmessage = function (e) { var m; try { m = JSON.parse(e.data); } catch (x) { return; } handle(m); };
    sock.onclose = function () {
      ws = null;
      setBoxes([], "screen");
      setBoxes([], "regions");
      hideLine();
      setState("Bağlantı koptu, yeniden aranıyor…", false);
      showHelp(true);
      setTimeout(search, 1000);
    };
    setTimeout(function () { if (ws) { showHelp(false); } }, 2500);
  }

  // ---------------------------------------------------------------- messages

  function handle(m) {
    if (m.type === "line") {
      showLine(m);
      if (ws) { ws.send(JSON.stringify({ type: "ack", id: m.id })); }
    } else if (m.type === "clear") {
      clearLine();
    } else if (m.type === "style" && m.style) {
      style = merge(DEFAULT_STYLE, merge(style, m.style));
      save("style", style);
      applyStyle();
    } else if (m.type === "screen") {
      setBoxes(m.boxes || [], "screen");
    } else if (m.type === "regions") {
      setBoxes(m.boxes || [], "regions");
    }
  }

  // ---------------------------------------------------------------- subtitles

  /* Rows on screen, oldest first; the newest is at the edge. In a busy scene up to maxLines stay stacked, each until
   * it could be read. A line can be written over its row later ("replaces": the rest of a split sentence came, it was
   * read better, the same person said something short again). */
  var rows = [], shownAt = 0, hideTimer = null, expireTimer = null;

  function rgba(hex, alpha) {
    var h = (hex || "#000000").replace("#", "");
    if (h.length === 8) { h = h.slice(2); }
    return "rgba(" + parseInt(h.slice(0, 2), 16) + "," + parseInt(h.slice(2, 4), 16) + "," + parseInt(h.slice(4, 6), 16) + "," + alpha + ")";
  }

  function readTime(text) {
    return Math.min(style.readMaxMs, style.readBaseMs + style.readPerCharMs * String(text || "").length);
  }

  function applyStyle() {
    var subs = $("subs");
    subs.style.top = subs.style.bottom = "auto";
    var off = (style.offset / 100 * 1080) + "px";
    if (style.position === "top") { subs.style.top = off; }
    else if (style.position === "middle") { subs.style.top = "45%"; }
    else { subs.style.bottom = off; }
    subs.style.textAlign = style.align;
    subs.style.transform = "translateX(" + ((style.xOffset || 0) / 100 * 1920) + "px)";   // moved left / right
    render();
  }

  function styleLine(el, old) {
    var shadow = [];
    for (var i = 0; i < 8; i++) {
      var a = i * Math.PI / 4, o = style.outline * 0.7;
      if (style.outline > 0) { shadow.push((Math.cos(a) * o).toFixed(1) + "px " + (Math.sin(a) * o).toFixed(1) + "px 0 " + style.outlineColor); }
    }
    if (style.shadow > 0) { shadow.push("0 " + style.shadow / 2 + "px " + style.shadow + "px rgba(0,0,0,0.8)"); }
    el.style.fontSize = (style.textSize * scale * (old && style.prevSmaller ? 0.8 : 1)) + "px";
    el.style.fontWeight = style.bold ? "700" : "400";
    el.style.color = old ? rgba(style.textColor, 0.75) : style.textColor;
    el.style.lineHeight = (style.lineSpacing / 100) + "";
    el.style.maxWidth = style.maxWidth + "%";
    el.style.background = rgba(style.bgColor, style.bgOpacity / 100);
    el.style.borderRadius = style.bgRadius * scale + "px";
    el.style.padding = (style.bgPadding * scale * 0.6) + "px " + (style.bgPadding * scale) + "px";
    el.style.marginTop = el.style.marginBottom = "8px";
    el.style.textShadow = shadow.join(", ");
    el.style.textTransform = style.uppercase ? "uppercase" : "none";
    el.style.display = style.align === "center" ? "table" : "inline-block";
  }

  function html(text) {
    return String(text || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/\n/g, "<br>");          // a sentence's rest added under its beginning
  }

  /* The speaker's own color from the PC (same name, same color), or the one name color of the style. */
  function speakerColor(r, old) {
    var c = (style.speakerColors !== false && r.color) ? r.color : style.speakerColor;
    return old ? rgba(c, 0.75) : c;
  }

  function lineHtml(r, old) {
    var out = "";
    if (r.speaker && style.speakerShow) {
      out += '<span class="spk" style="color:' + speakerColor(r, old) + '">' + html(r.speaker) + ":</span>"
        + (style.speakerOwnLine ? "<br>" : " ");
    }
    out += html(r.tr);
    if (!old && r.partial && style.provisional !== false && !/(…|\.\.\.)\s*$/.test(r.tr || "")) { out += " …"; }
    if (!old && style.showEnglish && r.en) {
      out += '<span class="en" style="font-size:' + style.englishSize + '%;color:' + style.englishColor + '">' + html(r.en) + "</span>";
    }
    return out;
  }

  function render() {
    var subs = $("subs"), list = rows.slice();
    subs.innerHTML = "";
    // Older rows away from the screen edge: above the newest at the bottom, below it at the top.
    if (style.position === "top") { list.reverse(); }
    for (var i = 0; i < list.length; i++) {
      var r = list[i], old = r !== rows[rows.length - 1], el = document.createElement("div");
      el.className = "line";
      el.innerHTML = lineHtml(r, old);
      el.style.fontStyle = !old && r.partial && style.provisional !== false ? "italic" : "normal";
      styleLine(el, old);
      subs.appendChild(el);
    }
  }

  function showLine(m) {
    clearTimeout(hideTimer);
    var now = Date.now(), i, r;
    var line = { id: m.id, speaker: m.speaker, tr: m.tr, en: m.en, color: m.color, partial: !!m.partial, until: 0 };
    if (m.replaces !== undefined && m.replaces !== null) {
      for (i = 0; i < rows.length; i++) {
        if (rows[i].id === m.replaces) {
          if (i === rows.length - 1) { shownAt = now; }        // the newest row: its reading time starts again
          else { line.until = Math.max(rows[i].until, now + readTime(m.tr)); }
          rows[i] = line;
          render();
          expire();
          return;
        }
      }
    } else if (m.update && rows.length) {
      rows[rows.length - 1] = line;
      shownAt = now;
      render();
      return;
    }
    if (rows.length && (style.stackPrevious || style.prevHoldMs > 0)) {
      r = rows[rows.length - 1];
      r.until = style.stackPrevious ? Infinity : Math.max(shownAt + readTime(r.tr), now + style.prevHoldMs);
    } else {
      rows = [];
    }
    rows.push(line);
    var max = Math.max(1, Math.min(6, style.maxLines || 4));
    while (rows.length > max) { rows.shift(); }
    shownAt = now;
    render();
    expire();
  }

  /* Rows moved up go when their time is up. */
  function expire() {
    clearTimeout(expireTimer);
    var now = Date.now(), next = Infinity, kept = [], i;
    for (i = 0; i < rows.length; i++) {
      var newest = i === rows.length - 1;
      if (!newest && rows[i].until <= now) { continue; }
      kept.push(rows[i]);
      if (!newest && rows[i].until < next) { next = rows[i].until; }
    }
    if (kept.length !== rows.length) { rows = kept; render(); }
    if (next !== Infinity) { expireTimer = setTimeout(expire, Math.max(50, next - now)); }
  }

  /* The game removed its line: ours stays until it (and the rows above) could be read. */
  function clearLine() {
    if (!rows.length) { return; }
    var now = Date.now(), wait = Math.max(style.lingerMs, readTime(rows[rows.length - 1].tr) - (now - shownAt));
    for (var i = 0; i < rows.length - 1; i++) {
      if (rows[i].until !== Infinity) { wait = Math.max(wait, rows[i].until - now); }
    }
    clearTimeout(hideTimer);
    hideTimer = setTimeout(hideLine, wait);
  }

  function hideLine() {
    rows = [];
    clearTimeout(expireTimer);
    render();
  }

  // ---------------------------------------------------------------- screen translation boxes

  function setBoxes(list, layerId) {
    var layer = $(layerId || "screen");
    layer.innerHTML = "";
    for (var i = 0; i < list.length; i++) {
      var b = list[i], el = document.createElement("div");
      var w = b.w * 1920, h = b.h * 1080, lineH = h / Math.max(1, b.lines || 1), pad = Math.min(lineH * 0.12, 6);
      // the room the Turkish may use without covering the next translated text (sent by the PC)
      var roomW = Math.max(w, (b.mw || b.w * 1.8) * 1920), roomH = Math.max(h, (b.mh || b.h) * 1080);
      var alpha = b.alpha === undefined ? 0.9 : b.alpha;
      el.className = "box";
      el.style.left = (b.x * 1920 - pad) + "px";
      el.style.top = (b.y * 1080 - pad) + "px";
      el.style.width = (roomW + pad) + "px";
      el.style.maxHeight = (roomH + pad) + "px";
      el.style.overflow = "hidden";
      el.style.padding = pad + "px";
      el.style.color = b.fg || "#fff";
      el.style.background = alpha > 0 ? rgba(b.bg || "#000000", alpha) : "transparent";
      if (b.shadow) { el.style.textShadow = "0 " + lineH * 0.05 + "px " + lineH * 0.15 + "px #000, 0 0 2px #000"; }
      fillText(el, b.tr || "", b.icons);
      layer.appendChild(el);
      fit(el, lineH, roomH, b.scale || 1);
      el.style.width = "auto";                       // the box hugs the text, at least the English text's width
      el.style.minWidth = (w + pad) + "px";
      el.style.maxWidth = (roomW + pad) + "px";
      if (b.align === "center") {
        // centred on the English text (a mission objective under the subtitles)
        el.style.textAlign = "center";
        el.style.left = (b.x * 1920 + w / 2 - el.offsetWidth / 2) + "px";
      }
    }
  }

  /* The text, with "⟦1⟧" replaced by the button icon's picture (as high as the letters). */
  function fillText(el, text, icons) {
    var re = /⟦(\d+)⟧/g, last = 0, m;
    el.textContent = "";
    while ((m = re.exec(text)) !== null) {
      el.appendChild(document.createTextNode(text.slice(last, m.index)));
      if (icons && icons[m[1]]) {
        var img = document.createElement("img");
        img.className = "icon";
        img.src = "data:image/png;base64," + icons[m[1]];
        el.appendChild(img);
      }
      last = re.lastIndex;
    }
    el.appendChild(document.createTextNode(text.slice(last)));
  }

  /* The English text's height x the chosen size first, smaller until it fits the room. */
  function fit(el, lineH, roomH, scale) {
    var size = lineH * 0.72 * scale, min = lineH * 0.35;
    el.style.fontSize = size + "px";
    while (size > min && (el.scrollHeight > roomH * 1.02 || el.scrollWidth > el.clientWidth + 1)) {
      size *= 0.92;
      el.style.fontSize = size + "px";
    }
  }

  // ---------------------------------------------------------------- guide, toast, keys

  function setState(text, ok) { var s = $("state"); s.textContent = text; s.className = ok ? "state ok" : "state"; }

  /* Shown on the help card and as a long toast, so a failure cannot be missed or overwritten. */
  function diag(text) {
    var d = $("diag");
    if (d) { d.textContent = text; }
    var t = $("toast");
    t.textContent = text;
    t.style.display = "block";
    clearTimeout(toast.timer);
    toast.timer = setTimeout(function () { t.style.display = "none"; }, 8000);
  }
  function showHelp(on) { $("help").style.display = on ? "block" : "none"; }
  function toast(text) {
    var t = $("toast");
    t.textContent = text;
    t.style.display = "block";
    clearTimeout(toast.timer);
    toast.timer = setTimeout(function () { t.style.display = "none"; }, 2500);
  }

  var BACK = [8, 27, 461, 10009];
  document.addEventListener("keydown", function (e) {
    var k = e.keyCode;
    if (k >= 49 && k <= 52) { showHdmi(k - 48); e.preventDefault(); }
    else if (k === 48) { if (!ws) { search(); } toast("Bilgisayar aranıyor…"); }
    else if (BACK.indexOf(k) >= 0) { showHelp($("help").style.display === "none"); e.preventDefault(); }
  });

  if (PLATFORM === "tizen") {
    try { ["1", "2", "3", "4", "0"].forEach(function (key) { tizen.tvinputdevice.registerKey(key); }); }
    catch (e) { /* number keys still arrive on most models */ }
  }

  applyStyle();
  showHdmi(hdmi);
  showHelp(true);
  search();
})();
