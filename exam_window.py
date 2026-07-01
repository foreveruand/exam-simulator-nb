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
    <div id="status-header-row">
      <span id="status-title">QUESTION STATUS</span>
      <span id="progress">Done: <b id="ans-count">0</b>/{n}</span>
    </div>
    <div id="status-grid"></div>
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
    if (q.answer_mode === "short") {{
      opts = `
        <textarea class="short-answer-input" id="short-${{i}}" rows="6"
          placeholder="Type your answer here"
          oninput="setShortAnswer(${{i}}, this.value)"></textarea>`;
    }} else {{
      for (const [l, t] of Object.entries(q.options))
        opts += `
          <button type="button" class="q-opt" id="opt-${{i}}-${{l}}" onclick="toggle(${{i}},'${{l}}')">
            <span class="opt-box" id="mark-${{i}}-${{l}}"></span>
            <span class="opt-letter">${{l}}.</span>
            <span class="opt-text">${{t}}</span>
          </button>`;
    }}
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

function isAnswered(value) {{
  if (value instanceof Set) return value.size > 0;
  return typeof value === "string" && value.trim().length > 0;
}}

function updateQuestionStatus(qi) {{
  const statusCell = document.getElementById(`status-${{qi}}`);
  if (statusCell) statusCell.classList.toggle("status-done", isAnswered(answers[qi]));
  document.getElementById("ans-count").textContent =
    Object.values(answers).filter(isAnswered).length;
}}

function setShortAnswer(qi, value) {{
  answers[qi] = value;
  updateQuestionStatus(qi);
}}

/* ── Status navigator ───────────────────────────────────────────────────── */
function renderStatusGrid() {{
  const grid = document.getElementById("status-grid");
  QUESTIONS.forEach((q, i) => {{
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "status-cell";
    btn.id = "status-" + i;
    btn.textContent = i + 1;
    btn.title = "Jump to Q" + (i + 1);
    btn.onclick = () => scrollToQ(i);
    grid.appendChild(btn);
  }});
}}

function toggle(qi, l) {{
  if (!answers[qi]) answers[qi] = new Set();
  const s  = answers[qi];
  if (!(s instanceof Set)) answers[qi] = new Set();
  const q = QUESTIONS[qi] || {{}};
  const answerMode = q.answer_mode || ((q.correct || []).length > 1 ? "multi" : "single");
  const choiceSet = answers[qi];

  function setOptionState(letter, selected) {{
    const opt = document.getElementById(`opt-${{qi}}-${{letter}}`);
    const mark = document.getElementById(`mark-${{qi}}-${{letter}}`);
    if (!opt || !mark) return;
    if (selected) {{
      opt.classList.add("q-opt-on");
      mark.textContent = "✕";
    }} else {{
      opt.classList.remove("q-opt-on");
      mark.textContent = "";
    }}
  }}

  if (choiceSet.has(l)) {{
    choiceSet.delete(l);
    setOptionState(l, false);
  }} else {{
    if (answerMode !== "multi") {{
      Array.from(choiceSet).forEach(prev => setOptionState(prev, false));
      choiceSet.clear();
    }}
    choiceSet.add(l);
    setOptionState(l, true);
  }}
  updateQuestionStatus(qi);
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
  const done      = Object.values(answers).filter(isAnswered).length;
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
    if (answers[k] instanceof Set && answers[k].size > 0)
      payload[k] = Array.from(answers[k]).sort();
    else if (typeof answers[k] === "string" && answers[k].trim())
      payload[k] = answers[k];
  }});
  document.getElementById("submit-btn").disabled    = true;
  document.getElementById("submit-btn").textContent = "Grading…";
  if (pybridge) pybridge.submitExam(JSON.stringify(payload));
}}

renderQuestions();
renderStatusGrid();
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
.q-opts { display: flex; flex-direction: column; gap: 6px; padding-left: 22px; }
.q-opt  {
  display: flex; gap: 8px; align-items: flex-start;
  width: 100%; padding: 5px 8px;
  background: #fff; border: 1px solid transparent;
  font-family: "Times New Roman", Times, serif;
  font-size: .96em; line-height: 1.6; text-align: left;
  cursor: pointer;
}
.q-opt:hover { background: #eff6ff; border-color: #bfdbfe; }
.q-opt-on {
  background: #dbeafe;
  border-color: #2563eb;
  box-shadow: inset 0 0 0 1px rgba(37,99,235,.2);
}
.opt-box {
  width: 20px; height: 20px; margin-top: 2px;
  border: 1.5px solid #444; background: #fff;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0; font-family: Arial, sans-serif;
  font-size: 13px; font-weight: bold; line-height: 1;
}
.q-opt-on .opt-box { border-color: #1d4ed8; color: #0f172a; }
.opt-letter { font-weight: bold; flex-shrink: 0; min-width: 18px; }
.opt-text   { color: #111; flex: 1; }
.short-answer-input {
  width: 100%;
  min-height: 130px;
  resize: vertical;
  padding: 10px 12px;
  border: 1px solid #9ca3af;
  border-radius: 4px;
  font-family: "Times New Roman", Times, serif;
  font-size: .96em;
  line-height: 1.6;
  color: #111;
  background: #fff;
}
.short-answer-input:focus {
  outline: none;
  border-color: #2563eb;
  box-shadow: 0 0 0 2px rgba(37,99,235,.14);
}
.q-source   { margin-top: 10px; padding-left: 22px; font-size: .85em; font-style: italic; color: #555; }

/* Right panel / status navigator */
#right-panel {
  flex: 0 0 260px; min-width: 220px; max-width: 300px;
  background: #f5f5f0; display: flex; flex-direction: column;
  padding: 14px 10px 10px; gap: 6px; font-family: Arial, sans-serif;
  border-left: 2px solid #999;
}
#status-header-row {
  display: flex; justify-content: space-between; align-items: baseline;
  padding: 0 4px 4px; border-bottom: 2px solid #333; margin-bottom: 2px;
}
#status-title { font-size: 11px; font-weight: bold; letter-spacing: 1.5px; text-transform: uppercase; color: #333; }
#progress     { font-size: 11px; color: #555; }
#status-grid  {
  flex: 1; overflow-y: auto;
  display: grid; grid-template-columns: repeat(5, 1fr);
  grid-auto-rows: 34px; gap: 6px;
  align-content: start; padding: 8px 2px 2px;
}
.status-cell {
  border: 1px solid #bbb; background: #fff; color: #444;
  font-size: 12px; font-weight: bold; cursor: pointer;
  font-family: Arial, sans-serif; user-select: none;
}
.status-cell:hover { color: #2563eb; background: #dbeafe; border-color: #2563eb; }
.status-done { color: #15803d !important; background: #dcfce7 !important; border-color: #22c55e !important; }

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
