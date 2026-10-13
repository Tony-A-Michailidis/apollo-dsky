/* DSKY front end: draws the panel from the state the server pushes, sends keys back. */
(function () {
  "use strict";

  // ------------------------------------------------------------ seven-segment digits
  const SEGS = {
    "0": "abcdef", "1": "bc", "2": "abdeg", "3": "abcdg", "4": "bcfg",
    "5": "acdfg", "6": "acdefg", "7": "abc", "8": "abcdefg", "9": "abcdfg", " ": "",
  };
  const PTS = {
    a: "4,2 18,2 20,4 18,6 4,6 2,4",
    b: "19,5 21,7 21,17 19,19 17,17 17,7",
    c: "19,19 21,21 21,31 19,33 17,31 17,21",
    d: "4,30 18,30 20,32 18,34 4,34 2,32",
    e: "3,19 5,21 5,31 3,33 1,31 1,21",
    f: "3,5 5,7 5,17 3,19 1,17 1,7",
    g: "4,16 18,16 20,18 18,20 4,20 2,18",
  };
  function digitSvg(ch) {
    const on = SEGS[ch] || "";
    let s = '<svg class="seg" viewBox="0 0 22 36">';
    for (const k of "abcdefg") s += `<polygon class="s${on.includes(k) ? " on" : ""}" points="${PTS[k]}"/>`;
    return s + "</svg>";
  }
  function signSvg(sign) {
    const plus = sign === "+" || sign === "±";
    const minus = sign === "-" || sign === "±" || sign === "+";
    return (
      '<svg class="sign" viewBox="0 0 22 36">' +
      `<rect class="s${minus ? " on" : ""}" x="3" y="16" width="16" height="4" rx="1"/>` +
      `<rect class="s${plus ? " on" : ""}" x="9" y="10" width="4" height="16" rx="1"/>` +
      "</svg>"
    );
  }
  function setDigits(el, text, n) {
    const t = (text || "").padEnd(n).slice(0, n);
    let html = "";
    for (const ch of t) html += digitSvg(ch);
    if (el.dataset.last !== html) { el.innerHTML = html; el.dataset.last = html; }
  }
  function setRegister(el, reg) {
    const html = signSvg(reg.sign) + [...reg.digits.padEnd(5)].map(digitSvg).join("");
    if (el.dataset.last !== html) { el.innerHTML = html; el.dataset.last = html; }
  }

  // ------------------------------------------------------------ lamps
  const LEFT = ["UPLINK ACTY", "NO ATT", "STBY", "KEY REL", "OPR ERR", "", ""];
  const RIGHT = ["TEMP", "GIMBAL LOCK", "PROG", "RESTART", "TRACKER", "ALT", "VEL"];
  const lampsEl = document.getElementById("lamps");
  const lampEls = {};
  for (let i = 0; i < 7; i++) {
    for (const [name, cls] of [[LEFT[i], "white"], [RIGHT[i], "amber"]]) {
      const d = document.createElement("div");
      d.className = "lamp " + cls + (name ? "" : " blank");
      d.textContent = name;
      lampsEl.appendChild(d);
      if (name) lampEls[name] = d;
    }
  }

  // ------------------------------------------------------------ keyboard
  const KEYS = [
    ["+", "+"], ["7", "7"], ["8", "8"], ["9", "9"], ["CLR", "CLR"],
    ["-", "-"], ["4", "4"], ["5", "5"], ["6", "6"], ["PRO", "PRO"],
    ["0", "0"], ["1", "1"], ["2", "2"], ["3", "3"], ["KEY REL", "KEY REL"],
  ];
  const kb = document.getElementById("keyboard");
  const keyButtons = {};
  function mkKey(label, key) {
    const b = document.createElement("button");
    b.className = "key" + (/^\d$/.test(label) ? " digit" : "");
    b.innerHTML = label.replace(" ", "<br>");
    b.addEventListener("click", () => sendKey(key));
    keyButtons[key] = b;
    return b;
  }
  const left = document.createElement("div"); left.className = "kcol";
  left.append(mkKey("VERB", "VERB"), mkKey("NOUN", "NOUN"));
  kb.appendChild(left);
  for (const [label, key] of KEYS) kb.appendChild(mkKey(label, key));
  const right = document.createElement("div"); right.className = "kcol right";
  right.append(mkKey("ENTR", "ENTR"), mkKey("RSET", "RSET"));
  kb.appendChild(right);

  // ------------------------------------------------------------ transport
  let ws = null;
  const connEl = document.getElementById("conn");
  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onopen = () => { connEl.textContent = "live"; connEl.className = "conn ok"; };
    ws.onclose = () => { connEl.textContent = "disconnected"; connEl.className = "conn down"; setTimeout(connect, 1500); };
    ws.onmessage = (ev) => render(JSON.parse(ev.data));
  }
  function sendKey(key) {
    const b = keyButtons[key];
    if (b) { b.classList.add("down"); setTimeout(() => b.classList.remove("down"), 120); }
    if (ws && ws.readyState === 1) ws.send(JSON.stringify({ key }));
    else fetch("/api/key", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key }) });
  }
  async function post(url, body) {
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (r.ok) render(await r.json());
  }

  // physical keyboard
  const KEYMAP = { v: "VERB", n: "NOUN", "+": "+", "-": "-", Enter: "ENTR", Backspace: "CLR", c: "CLR", p: "PRO", k: "KEY REL", r: "RSET" };
  document.addEventListener("keydown", (ev) => {
    if (ev.target.tagName === "INPUT" || ev.ctrlKey || ev.metaKey || ev.altKey) return;
    let key = null;
    if (/^\d$/.test(ev.key)) key = ev.key;
    else if (KEYMAP[ev.key] !== undefined) key = KEYMAP[ev.key];
    else if (KEYMAP[ev.key.toLowerCase()] !== undefined) key = KEYMAP[ev.key.toLowerCase()];
    if (key) { ev.preventDefault(); sendKey(key); }
  });

  // side-panel controls
  document.querySelectorAll("[data-sim]").forEach((b) => b.addEventListener("click", () => post("/api/sim", JSON.parse(b.dataset.sim))));
  document.querySelectorAll("[data-rr]").forEach((b) => b.addEventListener("click", () => post("/api/sim", { rr_switch: b.dataset.rr })));
  let paused = false;
  document.getElementById("pause").addEventListener("click", () => post("/api/sim", { paused: !paused }));
  const uplinkIn = document.getElementById("uplink");
  function sendUplink() {
    const seq = uplinkIn.value.trim();
    if (!seq) return;
    post("/api/keys", { sequence: seq, uplink: true });
    uplinkIn.value = "";
  }
  document.getElementById("uplink-send").addEventListener("click", sendUplink);
  uplinkIn.addEventListener("keydown", (ev) => { if (ev.key === "Enter") sendUplink(); });

  // ------------------------------------------------------------ rendering
  const el = (id) => document.getElementById(id);
  const vnEls = [el("verb"), el("noun")];
  function cell(k, v, cls) { return `<div class="cell"><span class="k">${k}</span><span class="v ${cls || ""}">${v}</span></div>`; }
  function fmt(x, d) { return x === null || x === undefined ? "-" : Number(x).toFixed(d === undefined ? 0 : d); }
  let lastEventsLen = -1, lastEventsFirst = null;

  function render(s) {
    const d = s.display;
    el("get").textContent = s.get_text;
    setDigits(el("prog"), d.prog, 2);
    setDigits(el("verb"), d.verb, 2);
    setDigits(el("noun"), d.noun, 2);
    for (const e of vnEls) e.classList.toggle("flash", !!d.flash);
    setRegister(el("r1"), d.r1);
    setRegister(el("r2"), d.r2);
    setRegister(el("r3"), d.r3);
    el("comp-acty").classList.toggle("on", !!d.comp_acty);
    for (const name in lampEls) lampEls[name].classList.toggle("on", !!d.lamps[name]);

    // what the computer is waiting for
    const pr = s.program_request;
    let pend = "";
    if (s.standby) pend = "STANDBY: PRO to resume";
    else if (pr && pr.waiting_for === "PRO") pend = `FL V${pad(pr.verb)}N${pad(pr.noun)} waiting for PRO`;
    else if (pr && pr.waiting_for === "data") pend = `FL V${pad(pr.verb)}N${pad(pr.noun)} waiting for data`;
    if (s.key_rel_pending) pend += (pend ? "  |  " : "") + "program wants the display: KEY REL";
    el("pending").textContent = pend;

    const lm = s.lm;
    el("computer").innerHTML =
      cell("Program", `P${pad(s.program)} ${s.program_name}`) +
      cell("Stage", s.stage || "-") +
      cell("Display owner", s.painted_by || "-") +
      cell("Keyboard", s.keyboard.entry ? `${s.keyboard.entry} ${s.keyboard.verb_buf}${s.keyboard.noun_buf}${s.keyboard.data}` : "idle") +
      cell("TIG", s.tig || "-") +
      cell("TFI", s.tfi === null ? "-" : fmt(s.tfi, 1) + " s") +
      cell("TGO (braking)", fmt(s.tgo, 0) + " s") +
      cell("TTG (approach)", fmt(s.ttg, 0) + " s") +
      cell("RR switch", s.rr_switch, s.rr_switch === "LGC" ? "good" : "warn") +
      cell("LR updates", lm.lr_permit ? "permitted (V57)" : "inhibited", lm.lr_permit ? "good" : "warn") +
      cell("ROD command", s.program === 66 ? fmt(s.vh_cmd, 0) + " ft/s" : "-") +
      cell("Sim rate", (s.paused ? "paused " : "") + s.rate + "x");

    el("vehicle").innerHTML =
      cell("Altitude (true)", fmt(lm.h_ft) + " ft") +
      cell("Altitude (PGNS)", fmt(lm.computed_h_ft) + " ft", Math.abs(lm.alt_err_ft) > 500 ? "warn" : "") +
      cell("Altitude rate", fmt(lm.vh_fps, 1) + " ft/s", lm.vh_fps < -15 && lm.h_ft < 500 ? "bad" : "") +
      cell("Forward velocity", fmt(-lm.vx_fps, 1) + " ft/s") +
      cell("Range to site", fmt(lm.range_site_nmi, 2) + " nmi") +
      cell("Pitch from vertical", fmt(lm.pitch_deg, 1) + " deg") +
      cell("Engine", lm.engine_on ? `ON ${fmt(lm.throttle_pct)}%` : "off", lm.engine_on ? "good" : "") +
      cell("Propellant", `${fmt(lm.fuel_lb)} lb` + (lm.fuel_seconds !== null ? ` (${fmt(lm.fuel_seconds)} s)` : ""), lm.fuel_low ? "bad" : "") +
      cell("Landing radar", lm.lr_locked ? "locked" : "no lock") +
      cell("Burn time", fmt(lm.t_burn_s) + " s") +
      cell("Delta-V", fmt(lm.dv_acc_fps) + " ft/s") +
      cell("Site shift", fmt(lm.site_shift_ft) + " ft") +
      (lm.landed ? cell("Touchdown", `${fmt(Math.abs(lm.touchdown_vh_fps), 1)} ft/s down`, Math.abs(lm.touchdown_vh_fps) > 10 ? "bad" : "good") : "");
    el("contact").classList.toggle("on", !!lm.contact);

    document.querySelectorAll("[data-rr]").forEach((b) => b.classList.toggle("active", b.dataset.rr === s.rr_switch));
    paused = !!s.paused;
    el("pause").textContent = paused ? "resume" : "pause";
    el("pause").classList.toggle("active", paused);
    document.querySelectorAll('[data-sim*="rate"]').forEach((b) => b.classList.toggle("active", JSON.parse(b.dataset.sim).rate === s.rate));

    el("alarms").innerHTML = s.alarms.length
      ? s.alarms.map((a) => `<div class="a">${a.code}  ${a.text}</div>`).join("") + `<div>FAILREG: ${s.failreg.join("  ")}</div>`
      : "none";

    const ev = s.events;
    if (ev.length !== lastEventsLen || (ev.length && ev[ev.length - 1].text !== lastEventsFirst)) {
      lastEventsLen = ev.length; lastEventsFirst = ev.length ? ev[ev.length - 1].text : null;
      const box = el("events");
      box.innerHTML = ev.slice().reverse().map((e) => `<div class="e ${e.level}"><span class="t">${e.get}</span><span class="x">${esc(e.text)}</span></div>`).join("");
    }
  }
  function pad(n) { return n === null || n === undefined ? "  " : String(n).padStart(2, "0"); }
  function esc(t) { return String(t).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])); }

  // initial blank panel, then connect
  render({
    get_text: "000:00:00", display: { prog: "  ", verb: "  ", noun: "  ", r1: { sign: "", digits: "     " }, r2: { sign: "", digits: "     " }, r3: { sign: "", digits: "     " }, flash: false, comp_acty: false, lamps: {} },
    program: 0, program_name: "", stage: null, standby: false, program_request: null, key_rel_pending: false, keyboard: { entry: null, verb_buf: "", noun_buf: "", data: "" },
    tig: null, tfi: null, tgo: 0, ttg: 0, rr_switch: "LGC", vh_cmd: 0, rate: 1, paused: false, alarms: [], failreg: [], events: [],
    lm: { h_ft: 0, computed_h_ft: 0, alt_err_ft: 0, vh_fps: 0, vx_fps: 0, range_site_nmi: 0, pitch_deg: 0, engine_on: false, throttle_pct: 0, fuel_lb: 0, fuel_seconds: null, fuel_low: false, lr_locked: false, lr_permit: false, t_burn_s: 0, dv_acc_fps: 0, site_shift_ft: 0, contact: false, landed: false },
  });
  connect();
})();
