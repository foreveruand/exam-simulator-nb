"""
Scoring engine + results HTML builder.
"""

from html import escape

# ── Flag definitions ──────────────────────────────────────────────────────────
FLAG_COLORS = {
    1: ("#ef4444", "Red"),
    2: ("#f97316", "Orange"),
    3: ("#22c55e", "Green"),
    4: ("#3b82f6", "Blue"),
    5: ("#ec4899", "Pink"),
    6: ("#06b6d4", "Turquoise"),
    7: ("#a855f7", "Purple"),
}

# ── Formatting helpers ────────────────────────────────────────────────────────

def _clean_zero(value: float, places: int = 6) -> float:
    rounded = round(float(value), places)
    return 0.0 if abs(rounded) < 10 ** (-places) else rounded


def _fmt_score(value: float) -> str:
    value = _clean_zero(value)
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


# ── compute_score ─────────────────────────────────────────────────────────────

def compute_score(questions, answers_dict, scoring):
    mode = scoring["mode"]

    question_results = []
    total_earned = 0.0
    total_possible = 0.0

    for i, q in enumerate(questions):
        if q.get("answer_mode") == "short":
            chosen_text = answers_dict.get(str(i), "")
            if not isinstance(chosen_text, str):
                chosen_text = ""
            chosen_text = chosen_text.strip()
            status = "manual" if chosen_text else "skipped"
            question_results.append({
                "index": i,
                "question": q["question"],
                "options": q["options"],
                "correct": [],
                "chosen": [],
                "chosen_text": chosen_text,
                "correct_text": q.get("correct_text", ""),
                "answer_mode": "short",
                "status": status,
                "earned": 0.0,
                "possible": 0.0,
                "nid": q.get("nid", ""),
                "explanation": q.get("explanation", ""),
            })
            continue

        correct_set = set(q["correct"])
        chosen_set = set(answers_dict.get(str(i), []))

        correct_chosen = correct_set & chosen_set
        wrong_chosen = chosen_set - correct_set

        possible = 1.0
        earned = 0.0

        if not chosen_set:
            status = "skipped"
            earned = 0.0

        elif mode == "raw":
            if chosen_set == correct_set:
                earned, status = 1.0, "correct"
            else:
                earned, status = 0.0, "wrong"

        elif mode == "partial":
            n = len(correct_set)
            step = 1.0 / n
            raw_earned = len(correct_chosen) * step - len(wrong_chosen) * step
            raw_earned = max(-possible, min(possible, raw_earned))
            earned = max(0.0, raw_earned)
            if earned >= 1.0:
                status = "correct"
            elif earned > 0:
                status = "partial"
            else:
                status = "wrong"

        else:  # negative
            n = len(correct_set)
            step = 1.0 / n
            raw_earned = len(correct_chosen) * step - len(wrong_chosen) * step
            earned = max(-possible, min(possible, raw_earned))
            if earned >= 1.0:
                status = "correct"
            elif earned > 0:
                status = "partial"
            else:
                status = "wrong"

        earned = _clean_zero(earned)
        total_earned += earned
        total_possible += possible

        question_results.append({
            "index": i,
            "question": q["question"],
            "options": q["options"],
            "correct": sorted(correct_set),
            "chosen": sorted(chosen_set),
            "chosen_text": "",
            "correct_text": "",
            "answer_mode": q.get("answer_mode", ""),
            "status": status,
            "earned": earned,
            "possible": possible,
            "nid": q.get("nid", ""),
            "explanation": q.get("explanation", ""),
        })

    total_earned = _clean_zero(total_earned)
    total_possible = _clean_zero(total_possible)
    if mode == "negative":
        total_earned = max(0.0, total_earned)
    pct = _clean_zero((total_earned / total_possible * 100) if total_possible else 0)
    score_20 = _clean_zero(pct / 5)  # maps 0–100% to 0–20

    return {
        "questions": question_results,
        "total_earned": total_earned,
        "total_possible": total_possible,
        "percentage": pct,
        "score_20": score_20,
        "scoring": scoring,
        "n_correct": sum(1 for r in question_results if r["status"] == "correct"),
        "n_partial": sum(1 for r in question_results if r["status"] == "partial"),
        "n_wrong": sum(1 for r in question_results if r["status"] == "wrong"),
        "n_skipped": sum(1 for r in question_results if r["status"] == "skipped"),
        "n_manual": sum(1 for r in question_results if r["status"] == "manual"),
    }


# ── build_results_html ────────────────────────────────────────────────────────

def build_results_html(results):
    pct = _clean_zero(results["percentage"])
    score_20 = _clean_zero(results["score_20"])
    exam_name = results.get("exam_name", "Exam")

    if score_20 >= 17:
        grade_color, grade_label = "#16a34a", "Excellent"
    elif score_20 >= 14:
        grade_color, grade_label = "#2563eb", "Good"
    elif score_20 >= 10:
        grade_color, grade_label = "#d97706", "Pass"
    else:
        grade_color, grade_label = "#dc2626", "Fail"

    score_mode = results["scoring"]["mode"]
    mode_labels = {
        "raw": "All or Nothing",
        "partial": "Partial Positive +",
        "negative": "Partial Negative -",
    }
    mode_label = mode_labels.get(score_mode, "Custom")

    q_rows = ""
    for r in results["questions"]:
        status_colors = {
            "correct": "#16a34a",
            "partial": "#d97706",
            "wrong": "#dc2626",
            "skipped": "#64748b",
            "manual": "#2563eb",
        }
        status_symbols = {
            "correct": "✓",
            "partial": "~",
            "wrong": "✗",
            "skipped": "?",
            "manual": "R",
        }
        sc = status_colors.get(r["status"], "#64748b")
        sym = status_symbols.get(r["status"], "?")
        num = r["index"] + 1
        badge = (
            f'<div class="status-badge" style="background:{sc};" '
            f'data-status="{r["status"]}" title="{r["status"].title()}">'
            f'<span class="badge-sym">{sym}</span>'
            f'</div>'
        )

        opts_html = ""
        if r.get("answer_mode") == "short":
            chosen_text = escape(r.get("chosen_text", "")) or "No answer entered"
            ref_answer = escape(r.get("correct_text", ""))
            opts_html = (
                f'<div class="short-answer-res {"short-answer-empty" if not r.get("chosen_text", "") else ""}">'
                f'<div class="short-answer-label">Your answer</div>'
                f'<div class="short-answer-text">{chosen_text}</div>'
                f'</div>'
            )
            if ref_answer:
                opts_html += (
                    f'<div class="short-answer-res short-answer-reference">'
                    f'<div class="short-answer-label">Reference answer</div>'
                    f'<div class="short-answer-text">{ref_answer}</div>'
                    f'</div>'
                )
        else:
            for letter, text in r["options"].items():
                is_correct = letter in r["correct"]
                is_chosen = letter in r["chosen"]
                classes = ["res-opt"]
                if is_correct:
                    classes.append("opt-correct")
                if is_chosen and not is_correct:
                    classes.append("opt-wrong")
                if is_chosen:
                    classes.append("opt-chosen")
                opts_html += (
                    f'<div class="{" ".join(classes)}">'
                    f'<b class="res-letter">{letter}.</b> {text}'
                    f'</div>'
                )

        expl_html = ""
        if r.get("explanation"):
            expl_html = (
                f'<div class="expl-wrap">'
                f'<button class="expl-toggle" onclick="toggleExpl(this)">'
                f'▶&nbsp; Show Explanation</button>'
                f'<div class="expl-body" style="display:none;">'
                f'{r["explanation"]}</div>'
                f'</div>'
            )

        earned_display = _fmt_score(r["earned"])
        possible_display = _fmt_score(r["possible"])
        score_str = f'{earned_display} / {possible_display}'
        nid = r.get("nid", "")

        q_rows += (
            f'<tr id="qrow-{r["index"]}" data-status="{r["status"]}">'
            f'<td class="td-sel">'
            f'<label class="sel-label">'
            f'<input type="checkbox" class="q-check" data-nid="{nid}" onchange="refreshSelCount()">'
            f'</label>'
            f'</td>'
            f'<td class="td-content" onclick="toggleRowSelection(event, {r["index"]})">'
            f'<div class="res-question"><span class="q-inline-num">{num}.</span> {r["question"]}</div>'
            f'{opts_html}{expl_html}</td>'
            f'<td class="td-score">'
            f'<div class="score-stack">'
            f'<div class="score-value">{score_str}</div>'
            f'{badge}'
            f'</div>'
            f'</td>'
            f'</tr>'
        )

    flag_opts = ''.join(
        f'<option value="{fnum}" style="color:{col};">'
        f'{FLAG_COLORS[fnum][1]}</option>'
        for fnum, (col, _) in FLAG_COLORS.items()
    )

    flag_svg_map = '{' + ','.join(
        f'{fnum}:\'<svg width="14" height="14" viewBox="0 0 24 24" '
        f'xmlns=\\"http://www.w3.org/2000/svg\\" style=\\"vertical-align:middle\\">'
        f'<path fill=\\"{col}\\" d=\\"M5 3v18h2v-7h10l-2-4 2-4H7V3H5z\\"/>'
        f'</svg> {name}\''
        for fnum, (col, name) in FLAG_COLORS.items()
    ) + '}'

    n_q = len(results["questions"])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Results — {exam_name}</title>
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: Arial, sans-serif;
  background: #eef2f7;
  color: #1a1a1a;
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}}

#header {{
  background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
  color: white;
  padding: 18px 28px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
  flex-shrink: 0;
  box-shadow: 0 6px 24px rgba(15, 23, 42, 0.28);
}}
#header-left h1 {{ font-size: 18px; font-weight: 700; margin-bottom: 2px; }}
#header-left .sub {{ color: #cbd5e1; font-size: 12px; }}
#header-center {{ text-align: center; }}
.score-big {{ font-size: 50px; font-weight: bold; color: {grade_color}; line-height: 1; }}
.grade-label {{ font-size: 15px; font-weight: bold; color: {grade_color}; margin-top: 4px; }}
.score-sub {{ color: #cbd5e1; font-size: 12px; margin-top: 3px; }}
#header-right {{ display: flex; flex-direction: column; gap: 10px; align-items: stretch; min-width: 220px; }}
.hdr-btn {{
  padding: 12px 18px;
  font-size: 13px;
  font-weight: 700;
  border: none;
  cursor: pointer;
  border-radius: 10px;
  text-align: center;
  box-shadow: 0 8px 18px rgba(37, 99, 235, 0.22);
}}
.btn-close {{ background: #334155; color: #fff; box-shadow: 0 8px 18px rgba(15, 23, 42, 0.22); }}
.btn-close:hover {{ background: #1e293b; }}
.btn-another {{ background: #2563eb; color: #fff; }}
.btn-another:hover {{ background: #1d4ed8; }}

#stats-bar {{
  display: flex;
  justify-content: center;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  padding: 12px 28px;
  background: #fff;
  border-bottom: 1px solid #e2e8f0;
  flex-shrink: 0;
}}
.stat-box {{
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 9px 16px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 700;
  background: #f8fafc;
  border: 1px solid #dbe3ee;
  cursor: pointer;
  transition: all .15s ease;
}}
.stat-box:hover {{ background: #eef4ff; border-color: #bfdbfe; transform: translateY(-1px); }}
.stat-box.active {{ border-color: #2563eb; background: #dbeafe; box-shadow: 0 0 0 2px rgba(37,99,235,.08); }}
.stat-box.filter-all {{ background: #0f172a; color: white; border-color: #0f172a; }}
.stat-box.filter-all:hover {{ background: #1e293b; border-color: #1e293b; }}
.stat-box.filter-all.active {{ background: #2563eb; border-color: #2563eb; }}
.stat-num {{ font-size: 19px; font-weight: 800; }}

#bulk-panel {{
  padding: 10px 28px 10px;
  background: linear-gradient(180deg, #f8fbff 0%, #eef5ff 100%);
  border-bottom: 1px solid #dbe3ee;
  flex-shrink: 0;
}}
#bulk-card {{
  background: #ffffff;
  border: 1px solid #cfe0ff;
  border-radius: 14px;
  padding: 10px 14px;
  box-shadow: 0 8px 18px rgba(37, 99, 235, 0.06);
}}
#action-bar {{
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}}
#sel-summary {{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 132px;
  height: 44px;
  padding: 0 16px;
  border-radius: 999px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  color: #1d4ed8;
  font-size: 14px;
  font-weight: 800;
  text-align: center;
  white-space: nowrap;
}}
.action-group {{
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 8px 10px;
  border-radius: 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}}
.action-group-title {{
  display: flex;
  align-items: center;
  margin-right: 2px;
}}
.action-group-title strong {{ font-size: 12px; color: #0f172a; text-transform: uppercase; letter-spacing: .7px; }}
.control-stack {{ display: flex; align-items: center; gap: 6px; }}
.control-stack label {{ font-size: 11px; font-weight: 700; color: #475569; text-transform: uppercase; letter-spacing: .7px; }}
#flag-select, #tag-input {{
  height: 40px;
  padding: 0 12px;
  font-size: 13px;
  border: 1px solid #cbd5e1;
  border-radius: 10px;
  background: #fff;
}}
#flag-select {{ min-width: 140px; }}
#tag-input {{ width: 210px; }}
.act-btn {{
  height: 40px;
  padding: 0 14px;
  font-size: 13px;
  font-weight: 700;
  border: 1px solid #cbd5e1;
  background: #fff;
  border-radius: 10px;
  cursor: pointer;
}}
.act-btn:hover {{ background: #f1f5f9; }}
.act-btn-primary {{ background: #2563eb; color: #fff; border-color: #2563eb; box-shadow: 0 8px 18px rgba(37, 99, 235, 0.18); }}
.act-btn-primary:hover {{ background: #1d4ed8; }}
#action-feedback {{ font-size: 12px; font-weight: 700; color: #16a34a; min-width: 130px; }}

#results-scroll {{ flex: 1; overflow-y: auto; padding: 16px 28px 32px; }}

table {{
  width: 100%;
  border-collapse: collapse;
  background: white;
  border-radius: 14px;
  overflow: hidden;
  box-shadow: 0 6px 22px rgba(15, 23, 42, 0.08);
}}
thead th {{
  background: #0f172a;
  color: white;
  padding: 11px 10px;
  text-align: left;
  font-size: 12px;
  position: sticky;
  top: 0;
  z-index: 5;
}}

.td-sel {{
  width: 52px;
  text-align: center;
  padding: 0;
  border-bottom: 1px solid #e2e8f0;
  vertical-align: middle;
}}
.sel-label {{
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  min-height: 56px;
  cursor: pointer;
  padding: 10px;
}}
.q-check {{ width: 18px; height: 18px; cursor: pointer; accent-color: #2563eb; }}

.status-badge {{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: 50%;
  cursor: default;
  line-height: 1;
  flex-shrink: 0;
}}
.badge-sym {{ font-size: 15px; font-weight: bold; color: rgba(255,255,255,0.92); }}

.td-content {{
  padding: 12px 14px;
  border-bottom: 1px solid #e2e8f0;
  vertical-align: top;
  cursor: pointer;
}}
.td-score {{
  width: 96px;
  text-align: center;
  font-weight: bold;
  font-size: 13px;
  white-space: nowrap;
  padding: 8px 6px;
  border-bottom: 1px solid #e2e8f0;
  vertical-align: middle;
}}
.score-stack {{
  min-height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
}}
.score-value {{ font-size: 13px; font-weight: bold; }}

tbody tr:nth-child(even) {{ background: #f8fafc; }}
tbody tr:nth-child(even):hover {{ background: #f1f5f9; }}
tbody tr:nth-child(odd):hover {{ background: #f1f5f9; }}
tbody tr:last-child td {{ border-bottom: none; }}
tr.row-selected td {{
  background: linear-gradient(180deg, #eff6ff 0%, #dbeafe 100%) !important;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.75), inset 0 -1px 0 rgba(191,219,254,.9);
}}
tr.row-selected .td-content {{
  border-left: 4px solid #2563eb;
  box-shadow: inset 0 0 0 1px rgba(37,99,235,.14);
}}
tr.row-selected .res-question {{ color: #0f172a; }}
tr.row-hidden {{ display: none; }}

.res-question {{ font-weight: 600; font-size: 14px; line-height: 1.55; margin-bottom: 8px; }}
.q-inline-num {{ font-weight: 700; margin-right: 4px; }}
.res-opt {{
  display: flex;
  gap: 6px;
  font-size: 13px;
  margin: 3px 0;
  padding: 5px 10px;
  border-radius: 6px;
  border: 1px solid rgba(0,0,0,.08);
  line-height: 1.5;
  background: #fff;
}}
.res-letter {{ font-weight: bold; flex-shrink: 0; min-width: 18px; }}
.opt-correct {{ background: rgba(0,190,0,0.18) !important; border-color: rgba(0,150,0,0.2) !important; }}
.opt-wrong {{ background: rgba(255,38,38,0.22) !important; border-color: rgba(200,0,0,0.2) !important; }}
.opt-chosen {{
  border-color: rgba(59,130,246,0.95) !important;
  box-shadow: inset 0 0 0 2px rgba(59,130,246,0.75) !important;
}}
.short-answer-res {{
  margin: 8px 0;
  padding: 10px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  background: #f8fafc;
}}
.short-answer-reference {{
  background: #eff6ff;
  border-color: #bfdbfe;
}}
.short-answer-label {{
  margin-bottom: 4px;
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: .5px;
  color: #475569;
}}
.short-answer-text {{
  white-space: pre-wrap;
  font-size: 13px;
  line-height: 1.55;
  color: #0f172a;
}}
.short-answer-empty .short-answer-text {{
  color: #64748b;
  font-style: italic;
}}

.expl-wrap {{ margin-top: 10px; border-top: 1px dashed #e2e8f0; padding-top: 8px; }}
.expl-toggle {{
  font-size: 12px;
  font-weight: bold;
  color: #fff;
  background: #2563eb;
  border: none;
  border-radius: 6px;
  padding: 6px 12px;
  cursor: pointer;
  margin-bottom: 6px;
  transition: background .15s;
}}
.expl-toggle:hover {{ background: #1d4ed8; }}
.expl-body {{
  font-size: 13px;
  color: #334155;
  line-height: 1.6;
  padding: 8px 12px;
  background: #eff6ff;
  border-left: 3px solid #2563eb;
  border-radius: 0 6px 6px 0;
}}

@media (max-width: 1120px) {{
  #header {{ align-items: flex-start; flex-wrap: wrap; }}
  #header-right {{ width: 100%; max-width: 280px; }}
  #bulk-top {{ flex-direction: column; }}
}}
</style>
</head>
<body>

<div id="header">
  <div id="header-left">
    <h1>📋 {exam_name}</h1>
    <div class="sub">Scoring: {mode_label} &nbsp;·&nbsp; {n_q} questions</div>
  </div>
  <div id="header-center">
    <div style="font-size:11px;color:#cbd5e1;letter-spacing:1px;margin-bottom:2px;">SCORE</div>
    <div class="score-big">{_fmt_score(score_20)}<span style="font-size:24px;color:#cbd5e1;"> / 20</span></div>
    <div class="grade-label">{grade_label}</div>
    <div class="score-sub">{_fmt_score(pct)}% &nbsp;·&nbsp; {_fmt_score(results["total_earned"])} / {_fmt_score(results["total_possible"])} raw pts</div>
  </div>
  <div id="header-right">
    <button class="hdr-btn btn-close" onclick="finishExam()">Close</button>
    <button class="hdr-btn btn-another" onclick="takeAnotherExam()">📝 Take Another Exam</button>
  </div>
</div>

<div id="stats-bar">
  <div class="stat-box filter-all active" onclick="filterRows('all')">
    All &nbsp;<span class="stat-num">{n_q}</span>
  </div>
  <div class="stat-box" onclick="filterRows('correct')" style="color:#16a34a;">
    <svg width="18" height="18" viewBox="0 0 22 22"><circle cx="11" cy="11" r="11" fill="#16a34a"/><text x="11" y="16" text-anchor="middle" font-size="13" font-weight="bold" fill="white" font-family="Arial">✓</text></svg>
    <span class="stat-num" style="color:#16a34a;">{results["n_correct"]}</span> Correct
  </div>
  {'' if score_mode == 'raw' else f'''<div class="stat-box" onclick="filterRows('partial')" style="color:#d97706;">
    <svg width="18" height="18" viewBox="0 0 22 22"><circle cx="11" cy="11" r="11" fill="#d97706"/><text x="11" y="16" text-anchor="middle" font-size="14" font-weight="bold" fill="white" font-family="Arial">~</text></svg>
    <span class="stat-num" style="color:#d97706;">{results["n_partial"]}</span> Partial
  </div>'''}
  <div class="stat-box" onclick="filterRows('wrong')" style="color:#dc2626;">
    <svg width="18" height="18" viewBox="0 0 22 22"><circle cx="11" cy="11" r="11" fill="#dc2626"/><text x="11" y="16" text-anchor="middle" font-size="13" font-weight="bold" fill="white" font-family="Arial">✗</text></svg>
    <span class="stat-num" style="color:#dc2626;">{results["n_wrong"]}</span> Wrong
  </div>
  <div class="stat-box" onclick="filterRows('skipped')" style="color:#64748b;">
    <svg width="18" height="18" viewBox="0 0 22 22"><circle cx="11" cy="11" r="11" fill="#64748b"/><text x="11" y="16" text-anchor="middle" font-size="13" font-weight="bold" fill="white" font-family="Arial">?</text></svg>
    <span class="stat-num" style="color:#64748b;">{results["n_skipped"]}</span> Skipped
  </div>
  <div class="stat-box" onclick="filterRows('manual')" style="color:#2563eb;">
    <svg width="18" height="18" viewBox="0 0 22 22"><circle cx="11" cy="11" r="11" fill="#2563eb"/><text x="11" y="16" text-anchor="middle" font-size="12" font-weight="bold" fill="white" font-family="Arial">R</text></svg>
    <span class="stat-num" style="color:#2563eb;">{results["n_manual"]}</span> Review
  </div>
</div>

<div id="bulk-panel">
  <div id="bulk-card">
    <div id="action-bar">
      <div id="sel-summary"><span id="sel-count">Selected: 0</span></div>

      <div class="action-group">
        <div class="action-group-title">
          <strong>Select</strong>
        </div>
        <button class="act-btn" onclick="selectAll()">Select all</button>
        <button class="act-btn" onclick="deselectAll()">Deselect all</button>
      </div>

      <div class="action-group">
        <div class="action-group-title">
          <strong>Flag</strong>
        </div>
        <div class="control-stack">
          <select id="flag-select">{flag_opts}</select>
        </div>
        <button class="act-btn act-btn-primary" onclick="applyFlag()">Apply Flag</button>
      </div>

      <div class="action-group">
        <div class="action-group-title">
          <strong>Tag</strong>
        </div>
        <div class="control-stack">
          <input id="tag-input" type="text" placeholder="e.g. needs_review">
        </div>
        <button class="act-btn act-btn-primary" onclick="applyTag()">Apply Tag</button>
      </div>

      <span id="action-feedback"></span>
    </div>
  </div>
</div>

<div id="results-scroll">
<table>
  <thead>
    <tr>
      <th style="width:52px;text-align:center;">Select</th>
      <th>Question &amp; Options</th>
      <th style="width:96px;text-align:center;">Score</th>
    </tr>
  </thead>
  <tbody>{q_rows}</tbody>
</table>
</div>

<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<script>
var pybridge = null;
var FLAG_SVGS = {flag_svg_map};
var currentFilter = 'all';

new QWebChannel(qt.webChannelTransport, function(ch) {{
  pybridge = ch.objects.pybridge;
}});

function finishExam() {{ if (pybridge) pybridge.closeExam(); }}
function takeAnotherExam() {{ if (pybridge) pybridge.takeAnotherExam(); }}

function toggleExpl(btn) {{
  var body = btn.nextElementSibling;
  var open = body.style.display !== 'none';
  body.style.display = open ? 'none' : 'block';
  btn.textContent = (open ? '▶' : '▼') + '\u00a0 ' + (open ? 'Show' : 'Hide') + ' Explanation';
}}

function toggleRowSelection(event, rowIndex) {{
  if (!event) return;
  if (event.target.closest('button, a, input, label, select, textarea, .expl-body')) return;
  var row = document.getElementById('qrow-' + rowIndex);
  if (!row) return;
  var cb = row.querySelector('.q-check');
  if (!cb) return;
  cb.checked = !cb.checked;
  refreshSelCount();
}}

function filterRows(status) {{
  currentFilter = status;
  document.querySelectorAll('.stat-box').forEach(function(b) {{
    b.classList.remove('active');
  }});
  var clicked = document.querySelector('.stat-box[onclick*="' + status + '"]');
  if (clicked) clicked.classList.add('active');

  document.querySelectorAll('tbody tr').forEach(function(tr) {{
    if (status === 'all' || tr.dataset.status === status) {{
      tr.classList.remove('row-hidden');
    }} else {{
      tr.classList.add('row-hidden');
    }}
  }});
  deselectAll();
}}

function refreshSelCount() {{
  var n = document.querySelectorAll('.q-check:checked').length;
  document.getElementById('sel-count').textContent = 'Selected: ' + n;
  document.querySelectorAll('tbody tr').forEach(function(tr) {{
    var cb = tr.querySelector('.q-check');
    if (cb) tr.classList.toggle('row-selected', cb.checked);
  }});
}}

function selectAll() {{
  document.querySelectorAll('tbody tr:not(.row-hidden) .q-check').forEach(function(c) {{
    c.checked = true;
  }});
  refreshSelCount();
}}

function deselectAll() {{
  document.querySelectorAll('.q-check').forEach(function(c) {{ c.checked = false; }});
  refreshSelCount();
}}

function getSelectedNids() {{
  var nids = [];
  document.querySelectorAll('.q-check:checked').forEach(function(cb) {{
    if (cb.dataset.nid) nids.push(cb.dataset.nid);
  }});
  return nids;
}}

function showFeedback(html) {{
  var el = document.getElementById('action-feedback');
  el.innerHTML = html;
  setTimeout(function() {{ el.innerHTML = ''; }}, 3500);
}}

function applyFlag() {{
  var nids = getSelectedNids();
  if (!nids.length) {{ showFeedback('⚠ No questions selected.'); return; }}
  var flagNum = parseInt(document.getElementById('flag-select').value);
  if (pybridge) {{
    pybridge.flagNotes(JSON.stringify(nids), flagNum);
    var label = FLAG_SVGS[flagNum] || ('Flag ' + flagNum);
    showFeedback(label + ' applied to ' + nids.length + ' card(s).');
  }}
}}

function applyTag() {{
  var nids = getSelectedNids();
  if (!nids.length) {{ showFeedback('⚠ No questions selected.'); return; }}
  var tag = document.getElementById('tag-input').value.trim();
  if (!tag) {{ showFeedback('⚠ Enter a tag name.'); return; }}
  if (pybridge) {{
    pybridge.tagNotes(JSON.stringify(nids), tag);
    showFeedback('🏷 Tagged ' + nids.length + ' card(s): ' + tag);
  }}
}}
</script>
</body>
</html>"""
