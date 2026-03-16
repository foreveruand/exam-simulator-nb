"""
ExamWindow — split-panel exam interface.

Left : scrollable exam-paper question sheet  (+/- zoom widget)
Right: physical square answer grid (Q# × A B C D E, ✕ when selected)
Top  : topbar with title, timer, submit button
"""

import json
from PyQt6.QtCore import QObject, QTimer, pyqtSlot
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWidgets import QMainWindow
from aqt.qt import Qt
from PyQt6.QtWebEngineWidgets import QWebEngineView
from aqt import mw


# ── Bridge ────────────────────────────────────────────────────────────────────

class _Bridge(QObject):
    def __init__(self, window: "ExamWindow"):
        super().__init__()
        self._win = window

    @pyqtSlot(str)
    def submitExam(self, answers_json: str):
        try:
            answers = json.loads(answers_json)
        except Exception:
            answers = {}
        self._win._on_submit(answers)

    @pyqtSlot()
    def timeUp(self):
        pass

    @pyqtSlot()
    def closeExam(self):
        QTimer.singleShot(0, self._win.close)

    @pyqtSlot()
    def takeAnotherExam(self):
        QTimer.singleShot(0, self._win._take_another_exam)

    @pyqtSlot(str, str)
    def tagNotes(self, nids_json: str, tag: str):
        try:
            nids = json.loads(nids_json)
        except Exception:
            nids = []
        self._win._tag_notes(nids, tag)

    @pyqtSlot(str, int)
    def flagNotes(self, nids_json: str, flag_num: int):
        try:
            nids = json.loads(nids_json)
        except Exception:
            nids = []
        self._win._flag_notes(nids, flag_num)


# ── Main window ───────────────────────────────────────────────────────────────

class ExamWindow(QMainWindow):
    def __init__(self, parent, questions: list, timer_seconds: int,
                 scoring: dict, exam_name: str = "Exam", save_history: bool = True):
        super().__init__(parent)
        self.questions     = questions
        self.timer_seconds = timer_seconds
        self.scoring       = scoring
        self.exam_name     = exam_name
        self.save_history  = save_history

        self.setWindowTitle(
            f"Exam Simulator — {len(questions)} Questions  |  {exam_name}")

        self._web = QWebEngineView()
        self._web.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.setCentralWidget(self._web)

        self._channel = QWebChannel()
        self._bridge  = _Bridge(self)
        self._channel.registerObject("pybridge", self._bridge)
        self._web.loadFinished.connect(self._rebind_webchannel)
        self._rebind_webchannel()

        self._web.setHtml(self._build_exam_html())

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _rebind_webchannel(self, *_args):
        try:
            self._web.page().setWebChannel(self._channel)
        except Exception:
            pass


    def _take_another_exam(self):
        from .launcher import LauncherDialog

        self.close()
        dlg = LauncherDialog(mw)
        dlg.exec()

    def _tag_notes(self, nids, tag):
        try:
            clean_tag = str(tag).strip().replace(" ", "_")
            ids = [int(nid) for nid in nids if str(nid).strip()]
        except Exception:
            return
        if not clean_tag or not ids:
            return
        changed = False
        for nid in ids:
            try:
                note = mw.col.get_note(int(nid))
                note.add_tag(clean_tag)
                note.flush()
                changed = True
            except Exception:
                pass
        if changed:
            try:
                mw.col.setMod()
            except Exception:
                pass
            try:
                mw.reset()
            except Exception:
                pass

    def _flag_notes(self, nids, flag_num):
        try:
            ids = [int(nid) for nid in nids if str(nid).strip()]
            flag_num = int(flag_num)
        except Exception:
            return
        if not ids:
            return
        changed = False
        for nid in ids:
            try:
                note = mw.col.get_note(int(nid))
                for card in note.cards():
                    card.set_user_flag(flag_num)
                    card.flush()
                    changed = True
            except Exception:
                pass
        if changed:
            try:
                mw.col.setMod()
            except Exception:
                pass
            try:
                mw.reset()
            except Exception:
                pass


    def _on_submit(self, answers_dict: dict):
        from .history_store import record_simulation
        from .scorer import compute_score, build_results_html

        if self.save_history:
            note_ids = [int(q["nid"]) for q in self.questions if q.get("nid") is not None]
            record_simulation(self.exam_name, note_ids)

        results = compute_score(self.questions, answers_dict, self.scoring)
        results["exam_name"] = self.exam_name
        self._web.setHtml(build_results_html(results))
        self._rebind_webchannel()

    # ── HTML builders ─────────────────────────────────────────────────────────

    def _build_exam_html(self) -> str:
        q_json  = json.dumps(self.questions, ensure_ascii=False)
        n       = len(self.questions)
        timer_s = self.timer_seconds
        hidden  = "hidden" if not timer_s else ""

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Exam — {self.exam_name}</title>
<style>{_EXAM_CSS}</style>
</head>
<body>

<!-- TOPBAR -->
<div id="topbar">
  <div id="exam-title">Exam &nbsp;·&nbsp; {n} Questions &nbsp;·&nbsp; {self.exam_name}</div>
  <div id="timer-wrap" class="{hidden}"><span id="timer-text">--:--</span></div>
  <button id="submit-btn" onclick="askSubmit()">Submit Exam</button>
</div>

<!-- MAIN -->
<div id="main">
  <div id="left-panel">
    <div id="zoom-ctrl">
      <button class="zoom-btn" onclick="zoomIn()" title="Zoom in">＋</button>
      <button class="zoom-btn" onclick="zoomOut()" title="Zoom out">－</button>
    </div>
    <div id="questions-container"></div>
  </div>
  <div id="right-panel">
    <div id="grid-header-row">
      <span id="grid-title">ANSWER SHEET</span>
      <span id="progress">Done: <b id="ans-count">0</b>/{n}</span>
    </div>
    <div id="grid-scroll">
      <table id="answer-grid">
        <thead id="grid-head"></thead>
        <tbody id="grid-body"></tbody>
      </table>
    </div>
  </div>
</div>

<!-- Custom confirm modal -->
<div id="modal-overlay" style="display:none;">
  <div id="modal-box">
    <div id="modal-title">Confirmation</div>
    <div id="modal-msg"></div>
    <div id="modal-btns">
      <button id="modal-cancel" onclick="modalCancel()">Cancel</button>
      <button id="modal-ok"     onclick="modalOk()">Submit anyway</button>
    </div>
  </div>
</div>

<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<script>
"use strict";

const QUESTIONS     = {q_json};
const TIMER_SECONDS = {timer_s};
const N             = QUESTIONS.length;

let pybridge      = null;
let answers       = {{}};
let timerLeft     = TIMER_SECONDS;
let timerInterval = null;
let fontSize      = 14;
let _modalResolve = null;

new QWebChannel(qt.webChannelTransport, ch => {{
  pybridge = ch.objects.pybridge || null;
}});

/* ── Questions ──────────────────────────────────────────────────────────── */
function renderQuestions() {{
  const c = document.getElementById("questions-container");
  QUESTIONS.forEach((q, i) => {{
    const block = document.createElement("div");
    block.className = "q-block";
    block.id        = "qblock-" + i;
    let opts = "";
    for (const [l, t] of Object.entries(q.options))
      opts += `<div class="q-opt"><span class="opt-letter">${{l}}.</span><span class="opt-text">${{t}}</span></div>`;
    const src = q.source ? `<div class="q-source">Source: ${{q.source}}</div>` : "";
    block.innerHTML = `
      <div class="q-header">
        <span class="q-num">${{i+1}}.</span>
        <span class="q-text">${{q.question}}</span>
      </div>
      <div class="q-opts">${{opts}}</div>${{src}}`;
    c.appendChild(block);
  }});
}}

/* ── Grid ───────────────────────────────────────────────────────────────── */
function renderGrid() {{
  const ALL = ["A","B","C","D","E"];
  const used = new Set();
  QUESTIONS.forEach(q => Object.keys(q.options).forEach(l => used.add(l)));
  const cols = ALL.filter(l => used.has(l));

  document.getElementById("grid-head").innerHTML =
    "<tr><th class='th-num'></th>" + cols.map(l=>`<th>${{l}}</th>`).join("") + "</tr>";

  const tbody = document.getElementById("grid-body");
  QUESTIONS.forEach((q, i) => {{
    const tr = document.createElement("tr");
    tr.id = "grow-" + i;
    let cells = `<td class="td-num" onclick="scrollToQ(${{i}})" title="Jump to Q${{i+1}}">Q${{i+1}}</td>`;
    cols.forEach(l => {{
      if (q.options[l] !== undefined)
        cells += `<td><div class="box" id="b-${{i}}-${{l}}" onclick="toggle(${{i}},'${{l}}')"></div></td>`;
      else
        cells += `<td><div class="box box-na"></div></td>`;
    }});
    tr.innerHTML = cells;
    tbody.appendChild(tr);
  }});
}}

function toggle(qi, l) {{
  if (!answers[qi]) answers[qi] = new Set();
  const s  = answers[qi];
  const el = document.getElementById(`b-${{qi}}-${{l}}`);
  if (s.has(l)) {{ s.delete(l); el.classList.remove("box-on"); el.textContent = ""; }}
  else          {{ s.add(l);    el.classList.add("box-on");    el.textContent = "✕"; }}
  const numCell = document.querySelector(`#grow-${{qi}} .td-num`);
  if (numCell) numCell.classList.toggle("td-done", s.size > 0);
  document.getElementById("ans-count").textContent =
    Object.values(answers).filter(s=>s&&s.size>0).length;
}}

function scrollToQ(i) {{
  const el = document.getElementById("qblock-"+i);
  if (el) el.scrollIntoView({{behavior:"smooth",block:"start"}});
}}

/* ── Zoom ───────────────────────────────────────────────────────────────── */
function zoomIn()  {{ fontSize = Math.min(fontSize + 2, 26); applyZoom(); }}
function zoomOut() {{ fontSize = Math.max(fontSize - 2,  9); applyZoom(); }}
function applyZoom() {{
  document.getElementById("questions-container").style.fontSize = fontSize + "px";
}}

/* ── Timer ──────────────────────────────────────────────────────────────── */
function startTimer() {{
  if (!TIMER_SECONDS) return;
  renderTimer();
  timerInterval = setInterval(() => {{
    timerLeft--;
    renderTimer();
    if (timerLeft <= 300) document.getElementById("timer-wrap").classList.add("timer-warn");
    if (timerLeft <= 0)   {{ clearInterval(timerInterval); if(pybridge) pybridge.timeUp(); doSubmit(); }}
  }}, 1000);
}}
function renderTimer() {{
  const m = String(Math.floor(timerLeft/60)).padStart(2,"0");
  const s = String(timerLeft%60).padStart(2,"0");
  document.getElementById("timer-text").textContent = m+":"+s;
}}

/* ── Custom confirm modal ───────────────────────────────────────────────── */
function showModal(msg) {{
  return new Promise(resolve => {{
    _modalResolve = resolve;
    document.getElementById("modal-msg").textContent = msg;
    document.getElementById("modal-overlay").style.display = "flex";
  }});
}}
function modalOk()     {{ document.getElementById("modal-overlay").style.display="none"; if(_modalResolve) _modalResolve(true);  }}
function modalCancel() {{ document.getElementById("modal-overlay").style.display="none"; if(_modalResolve) _modalResolve(false); }}

async function askSubmit() {{
  const done      = Object.values(answers).filter(s=>s&&s.size>0).length;
  const remaining = N - done;
  if (remaining > 0) {{
    const ok = await showModal(`${{remaining}} question(s) still unanswered. Submit anyway?`);
    if (!ok) return;
  }}
  doSubmit();
}}

function doSubmit() {{
  if (timerInterval) clearInterval(timerInterval);
  const payload = {{}};
  Object.keys(answers).forEach(k => {{
    if (answers[k] && answers[k].size > 0)
      payload[k] = Array.from(answers[k]).sort();
  }});
  document.getElementById("submit-btn").disabled    = true;
  document.getElementById("submit-btn").textContent = "Grading…";
  if (pybridge) pybridge.submitExam(JSON.stringify(payload));
}}

renderQuestions();
renderGrid();
startTimer();
</script>
</body>
</html>"""


# ── CSS (plain string — no f-string, single braces are fine) ─────────────────

_EXAM_CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; overflow: hidden; }
body {
  font-family: "Times New Roman", Times, serif;
  font-size: 14px;
  background: #e8e8e8;
  color: #000;
  display: flex;
  flex-direction: column;
}
#main { display: flex; flex: 1; overflow: hidden; }

/* Topbar */
#topbar {
  position: relative;
  display: flex; align-items: center; justify-content: space-between;
  background: #1e293b; color: #fff;
  padding: 10px 24px; flex-shrink: 0; gap: 16px;
  font-family: Arial, sans-serif;
}
#exam-title { font-size: 13px; font-weight: bold; letter-spacing: .5px; text-transform: uppercase; }
#timer-wrap {
  position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%);
  font-size: 22px; font-weight: bold; font-family: monospace;
  color: #7dd3fc; min-width: 90px; text-align: center;
}
#timer-wrap.hidden { visibility: hidden; }
#timer-wrap.timer-warn { color: #f87171; animation: blink 1s steps(1) infinite; }
@keyframes blink { 50% { opacity: .4; } }
#submit-btn {
  background: #2563eb; color: #fff; border: none;
  padding: 8px 20px; font-size: 13px; font-weight: bold;
  cursor: pointer; font-family: Arial, sans-serif;
  text-transform: uppercase; letter-spacing: .5px;
}
#submit-btn:hover    { background: #1d4ed8; }
#submit-btn:disabled { background: #64748b; cursor: default; }

/* Left panel */
#left-panel {
  flex: 3; overflow-y: auto; position: relative;
  padding: 36px 48px 48px; background: #fff; border-right: 1px solid #bbb;
}

/* Zoom widget */
#zoom-ctrl {
  position: sticky; top: 8px; float: right;
  display: flex; flex-direction: column; gap: 4px;
  z-index: 20; margin-left: 12px;
}
.zoom-btn {
  width: 28px; height: 28px;
  background: #f1f5f9; border: 1px solid #cbd5e1;
  border-radius: 4px; font-size: 16px; font-weight: bold;
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  font-family: Arial, sans-serif; line-height: 1; color: #1e293b;
  box-shadow: 0 1px 3px rgba(0,0,0,.1);
}
.zoom-btn:hover { background: #dbeafe; border-color: #2563eb; }

/* Question blocks */
.q-block {
  margin-bottom: 28px; padding-bottom: 22px; border-bottom: 1px solid #ddd;
}
.q-block:last-child { border-bottom: none; }
.q-header { display: flex; gap: 8px; margin-bottom: 10px; line-height: 1.6; }
.q-num  { font-weight: bold; font-size: 1em; flex-shrink: 0; padding-top: 1px; }
.q-text { font-size: 1em; font-weight: bold; line-height: 1.65; }
.q-opts { display: flex; flex-direction: column; gap: 3px; padding-left: 22px; }
.q-opt  { display: flex; gap: 8px; font-size: .96em; line-height: 1.6; }
.opt-letter { font-weight: bold; flex-shrink: 0; min-width: 18px; }
.opt-text   { color: #111; }
.q-source   { margin-top: 10px; padding-left: 22px; font-size: .85em; font-style: italic; color: #555; }

/* Right panel / answer grid */
#right-panel {
  flex: 0 0 280px; min-width: 240px; max-width: 340px;
  background: #f5f5f0; display: flex; flex-direction: column;
  padding: 14px 10px 10px; gap: 6px; font-family: Arial, sans-serif;
  border-left: 2px solid #999;
}
#grid-header-row {
  display: flex; justify-content: space-between; align-items: baseline;
  padding: 0 4px 4px; border-bottom: 2px solid #333; margin-bottom: 2px;
}
#grid-title   { font-size: 11px; font-weight: bold; letter-spacing: 1.5px; text-transform: uppercase; color: #333; }
#progress     { font-size: 11px; color: #555; }
#grid-scroll  { flex: 1; overflow-y: auto; }
#answer-grid  { width: 100%; border-collapse: collapse; font-size: 12px; font-family: Arial, sans-serif; }
#answer-grid thead th {
  background: #333; color: #fff; padding: 5px 0; text-align: center;
  font-size: 12px; font-weight: bold; position: sticky; top: 0; z-index: 5;
  border: 1px solid #555;
}
.th-num { width: 38px; }
#answer-grid tbody tr { border-bottom: 1px solid #ccc; }
#answer-grid tbody td { padding: 2px 3px; text-align: center; border: 1px solid #ccc; }
.td-num {
  font-size: 11px; font-weight: bold; color: #444;
  cursor: pointer; user-select: none; background: #eee; white-space: nowrap;
}
.td-num:hover { color: #2563eb; background: #dbeafe; }
.td-done      { color: #15803d !important; background: #dcfce7 !important; }
.box {
  width: 22px; height: 22px; border: 1.5px solid #444;
  background: #fff; margin: 0 auto; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  font-size: 14px; font-weight: bold; color: #111;
  user-select: none; line-height: 1;
}
.box:hover { background: #dbeafe; border-color: #2563eb; }
.box-on {
  background: #dbeafe !important;
  border: 2px solid #1d4ed8 !important;
  color: #0f172a !important;
  box-shadow: inset 0 0 0 2px rgba(29,78,216,.18), 0 0 0 1px rgba(29,78,216,.14);
}
.box-na    { background: #e5e5e5 !important; border-color: #bbb !important; cursor: default; opacity:.5; }
.box-na:hover { background: #e5e5e5 !important; border-color: #bbb !important; }

/* Custom confirm modal */
#modal-overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,.45);
  display: flex; align-items: center; justify-content: center;
  z-index: 1000;
}
#modal-box {
  background: #fff; border-radius: 10px;
  padding: 28px 32px; min-width: 320px; max-width: 420px;
  box-shadow: 0 8px 32px rgba(0,0,0,.25);
  font-family: Arial, sans-serif;
}
#modal-title {
  font-size: 16px; font-weight: bold; margin-bottom: 12px; color: #1e293b;
}
#modal-msg { font-size: 14px; color: #334155; margin-bottom: 22px; line-height: 1.5; }
#modal-btns { display: flex; justify-content: flex-end; gap: 10px; }
#modal-cancel {
  padding: 8px 18px; border: 1px solid #cbd5e1;
  background: #fff; border-radius: 6px; cursor: pointer; font-size: 13px;
}
#modal-cancel:hover { background: #f1f5f9; }
#modal-ok {
  padding: 8px 18px; border: none;
  background: #2563eb; color: #fff; border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: bold;
}
#modal-ok:hover { background: #1d4ed8; }
"""
