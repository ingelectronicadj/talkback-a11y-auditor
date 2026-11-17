"""Generacion de clips cortos .mp4 para Jira (por hallazgo, por sonda y Before/After) y reporte --diff."""

import html
import json
import os
import subprocess
import sys
import tempfile
from . import VERSION
from .config import SCRIPT_DIR
from .wcag_catalog import WCAG_CATALOG, WCAG_ORDER, classify_issue_key, resolve_wcag_meta


def ensure_video_binary():
    """Compila bajo demanda tb_video.swift en macOS (AVFoundation, sin ffmpeg externo)."""
    if sys.platform != "darwin":
        return None
    src = os.path.join(SCRIPT_DIR, "tb_video.swift")
    binpath = os.path.join(SCRIPT_DIR, "tb_video")
    if not os.path.exists(src):
        return None
    if os.path.exists(binpath) and os.path.getmtime(binpath) >= os.path.getmtime(src):
        return binpath
    try:
        subprocess.run(
            ["swiftc", "-O", src, "-o", binpath],
            check=True,
            capture_output=True,
            timeout=120,
        )
        return binpath
    except Exception as e:
        print("      [video] codificador tb_video no disponible (%s)" % e)
        return None


def _run_video_spec(binpath, spec_dict):
    if not binpath:
        return None
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tf:
        json.dump(spec_dict, tf, ensure_ascii=False)
        spec_path = tf.name
    try:
        res = subprocess.run(
            [binpath, spec_path],
            capture_output=True,
            text=True,
            timeout=90,
        )
        out = (res.stdout or "").strip()
        if res.returncode == 0 and out and os.path.isfile(out) and os.path.getsize(out) > 256:
            return out
        return None
    except Exception:
        return None
    finally:
        try:
            os.remove(spec_path)
        except OSError:
            pass


def _select_clip_window(steps, flagged_nums, max_slides=7):
    """Selecciona una ventana corta de pasos (con 1 paso de contexto antes y despues) lista para Jira."""
    if not steps or not flagged_nums:
        return []
    step_by_i = {s["i"]: s for s in steps if os.path.isfile(s.get("png") or "")}
    if not step_by_i:
        return []
    valid_flagged = [n for n in sorted(set(flagged_nums)) if n in step_by_i]
    if not valid_flagged:
        return []
    first_n = valid_flagged[0]
    ordered_ids = sorted(step_by_i.keys())
    pos = ordered_ids.index(first_n)
    start_pos = max(0, pos - 1)
    chosen_ids = ordered_ids[start_pos : start_pos + max_slides]
    if len(chosen_ids) == 1 and len(ordered_ids) > 1:
        end_pos = min(len(ordered_ids), start_pos + 2)
        chosen_ids = ordered_ids[max(0, end_pos - 2) : end_pos]
    return [step_by_i[cid] for cid in chosen_ids]


def generate_finding_clips(steps, by_rule, out_dir, probes=None):
    """Genera clips .mp4 cortos (4 a 11 s) en out_dir/video/ para cada regla TB-* con hallazgos."""
    binpath = ensure_video_binary()
    if not binpath:
        return {}, {}
    vid_dir = os.path.join(out_dir, "video")
    os.makedirs(vid_dir, exist_ok=True)
    rule_clips = {}
    total_steps = len(steps)

    for rk in WCAG_ORDER:
        items = by_rule.get(rk)
        if not items:
            continue
        cat = WCAG_CATALOG[rk]
        rule_id = cat["rule_id"]
        flagged_set = {i for i, _ in items}
        win_steps = _select_clip_window(steps, flagged_set, max_slides=7)
        if not win_steps:
            continue
        slides = []
        for s in win_steps:
            is_flag = s["i"] in flagged_set
            utt = (s.get("utterance") or "").strip()
            lbl = (s.get("label") or "").strip()
            ptitle = (s.get("page_title") or "").strip()
            if utt:
                main_txt = "TalkBack: \"%s\"" % utt[:95]
            elif s.get("is_skeleton"):
                main_txt = "Skeleton sin anuncio de carga (%s)" % (ptitle or "vista")[:60]
            else:
                main_txt = lbl[:95] or "(sin anuncio capturado)"
            badge = "PASO #%d/%d%s" % (
                s["i"],
                total_steps,
                " [HALLAZGO]" if is_flag else " [CONTEXTO]",
            )
            slides.append({
                "png": s["png"],
                "label": main_txt,
                "badge": badge,
                "isFlagged": is_flag,
                "durationSec": 1.75 if is_flag else 1.25,
            })
        fname = "%s_steps_%03d_%03d.mp4" % (rule_id.lower(), win_steps[0]["i"], win_steps[-1]["i"])
        out_mp4 = os.path.join(vid_dir, fname)
        built = _run_video_spec(
            binpath,
            {
                "mode": "slides",
                "output": out_mp4,
                "title": "%s · WCAG %s" % (rule_id, cat["criterion"]),
                "maxHeight": 1180,
                "fps": 10,
                "slides": slides,
            },
        )
        if built:
            rule_clips[rk] = os.path.relpath(built, out_dir)

    probe_clips = {}
    for idx, pr in enumerate(probes or [], 1):
        shots = pr.get("screenshots") or []
        valid_shots = [
            os.path.join(out_dir, "img", fn)
            for fn in shots
            if os.path.isfile(os.path.join(out_dir, "img", fn))
        ]
        if len(valid_shots) >= 2:
            ptype = pr.get("type") or "probe"
            slides = []
            for s_idx, sp in enumerate(valid_shots, 1):
                slides.append({
                    "png": sp,
                    "label": "%s · captura %d (%s)" % (ptype, s_idx, os.path.basename(sp)),
                    "badge": "SONDA %d/%d" % (s_idx, len(valid_shots)),
                    "isFlagged": bool(pr.get("potential_issue") or (ptype == "loading_probe" and not pr.get("loading_announced"))),
                    "durationSec": 1.65,
                })
            out_mp4 = os.path.join(vid_dir, "probe_%02d_%s.mp4" % (idx, ptype))
            built = _run_video_spec(
                binpath,
                {
                    "mode": "slides",
                    "output": out_mp4,
                    "title": "Sonda dinamica: %s" % ptype,
                    "maxHeight": 1180,
                    "fps": 10,
                    "slides": slides,
                },
            )
            if built:
                probe_clips[idx - 1] = os.path.relpath(built, out_dir)

    return rule_clips, probe_clips


def _collect_rules_from_saved(saved_data, dir_path):
    """Extrae el mapa rule_key -> [(step_i, issue_msg)] desde un steps.json guardado."""
    from .rules import analyze_sequence_issues, node_issues, text_a11y_issues

    steps = []
    for s in saved_data.get("steps") or []:
        cp = dict(s)
        cp["png"] = os.path.join(dir_path, s.get("png") or "")
        steps.append(cp)
    analyze_sequence_issues(steps)
    dom_snap = saved_data.get("dom_snapshot") or {}
    exp_loc = dom_snap.get("lang") or "es"
    by_rule = {}
    for s in steps:
        if s.get("is_duplicate") or s.get("in_overlay"):
            continue
        issues = []
        if s.get("node"):
            for it in node_issues(s["node"], expected_locale=exp_loc):
                if it not in issues:
                    issues.append(it)
        for txt in (s.get("label") or "", s.get("utterance") or ""):
            for it in text_a11y_issues(txt, expected_locale=exp_loc):
                if it not in issues:
                    issues.append(it)
        for it in s.get("seq_issues") or []:
            if it not in issues:
                issues.append(it)
        for it in issues:
            if "ruido" in it:
                continue
            rk = classify_issue_key(it)
            by_rule.setdefault(rk, []).append((s["i"], it))
    return steps, by_rule


def build_diff_report(before_dir, after_dir, out_dir=None):
    """Compara dos corridas Android TalkBack (Antes vs Despues) y genera diff_report.html + clip Before/After .mp4."""
    b_json_p = os.path.join(before_dir, "steps.json")
    a_json_p = os.path.join(after_dir, "steps.json")
    if not os.path.isfile(b_json_p) or not os.path.isfile(a_json_p):
        raise RuntimeError("Ambos directorios deben contener steps.json (%s, %s)" % (b_json_p, a_json_p))

    b_data = json.load(open(b_json_p, encoding="utf-8"))
    a_data = json.load(open(a_json_p, encoding="utf-8"))
    b_steps, b_rules = _collect_rules_from_saved(b_data, before_dir)
    a_steps, a_rules = _collect_rules_from_saved(a_data, after_dir)

    out_dir = out_dir or os.path.join(after_dir, "diff")
    os.makedirs(out_dir, exist_ok=True)

    b_ver = (b_data.get("dom_snapshot") or {}).get("bundleVersion") or "antes"
    a_ver = (a_data.get("dom_snapshot") or {}).get("bundleVersion") or "despues"
    v_title = ((a_data.get("view_info") or {}).get("title")) or os.path.basename(os.path.abspath(after_dir))

    fixed_rules = [rk for rk in WCAG_ORDER if rk in b_rules and rk not in a_rules]
    persisting_rules = [rk for rk in WCAG_ORDER if rk in b_rules and rk in a_rules]
    new_rules = [rk for rk in WCAG_ORDER if rk not in b_rules and rk in a_rules]

    # Construir pares para el video comparativo Before/After
    binpath = ensure_video_binary()
    video_rel = ""
    if binpath and b_steps and a_steps:
        pairs = []
        # Priorizar pasos donde habia hallazgos resueltos o pasos alineados por indice
        focus_indices = []
        for rk in fixed_rules + persisting_rules + new_rules:
            src_items = b_rules.get(rk) or a_rules.get(rk) or []
            for st_i, _ in src_items[:2]:
                if st_i not in focus_indices:
                    focus_indices.append(st_i)
        if not focus_indices:
            focus_indices = [s["i"] for s in a_steps[:6]]
        b_map = {s["i"]: s for s in b_steps if os.path.isfile(s.get("png") or "")}
        a_map = {s["i"]: s for s in a_steps if os.path.isfile(s.get("png") or "")}
        b_fallback = [s for s in b_steps if os.path.isfile(s.get("png") or "")]
        a_fallback = [s for s in a_steps if os.path.isfile(s.get("png") or "")]
        if b_fallback and a_fallback:
            for idx_num in focus_indices[:8]:
                bs = b_map.get(idx_num) or b_fallback[min(idx_num - 1, len(b_fallback) - 1)]
                as_ = a_map.get(idx_num) or a_fallback[min(idx_num - 1, len(a_fallback) - 1)]
                pairs.append({
                    "leftPng": bs["png"],
                    "leftLabel": "#%d %s" % (bs["i"], (bs.get("utterance") or bs.get("label") or "(sin anuncio)")[:75]),
                    "rightPng": as_["png"],
                    "rightLabel": "#%d %s" % (as_["i"], (as_.get("utterance") or as_.get("label") or "(sin anuncio)")[:75]),
                    "durationSec": 1.85,
                })
            if pairs:
                out_mp4 = os.path.join(out_dir, "video", "before_after_comparison.mp4")
                built = _run_video_spec(
                    binpath,
                    {
                        "mode": "side_by_side",
                        "output": out_mp4,
                        "title": "Validacion TalkBack: %s" % v_title[:55],
                        "leftHeader": "ANTES (v%s)" % b_ver,
                        "rightHeader": "DESPUES (v%s)" % a_ver,
                        "maxHeight": 1120,
                        "fps": 10,
                        "pairs": pairs,
                    },
                )
                if built:
                    video_rel = os.path.relpath(built, out_dir)

    rows_html = []
    for status_lbl, pill_cls, rlist in (
        ("Resuelto", "ok", fixed_rules),
        ("Persiste", "warn", persisting_rules),
        ("Nuevo", "crit", new_rules),
    ):
        for rk in rlist:
            cat = WCAG_CATALOG[rk]
            wmeta = resolve_wcag_meta(cat["criterion"])
            b_cnt = len(b_rules.get(rk, []))
            a_cnt = len(a_rules.get(rk, []))
            sample_msg = ((a_rules.get(rk) or b_rules.get(rk))[0][1]) if (a_rules.get(rk) or b_rules.get(rk)) else ""
            rows_html.append(
                "<tr>"
                "<td><b>%s</b><br><span class='muted'>WCAG %s (%s)</span></td>"
                "<td><span class='pill %s'>%s</span></td>"
                "<td>%d paso(s)</td>"
                "<td>%d paso(s)</td>"
                "<td>%s</td>"
                "</tr>"
                % (
                    html.escape(cat["rule_id"]),
                    html.escape(wmeta["criterion"]),
                    html.escape(wmeta["level"]),
                    pill_cls,
                    status_lbl,
                    b_cnt,
                    a_cnt,
                    html.escape(sample_msg[:140]),
                )
            )
    if not rows_html:
        rows_html.append("<tr><td colspan='5' class='muted'>Sin hallazgos en ninguna de las dos corridas.</td></tr>")

    vid_block = (
        '<div class="vid-card"><h2>Evidencia en video Antes vs Despues (lista para Jira)</h2>'
        '<video controls preload="metadata" src="%s"></video>'
        '<div><a class="dl-btn" href="%s" download>Descargar clip Before/After (.mp4)</a></div></div>'
        % (html.escape(video_rel), html.escape(video_rel))
        if video_rel
        else ""
    )

    doc = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Comparativa Before/After - %(title)s - TalkBack Audit v%(ver)s</title>
<style>
*{box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;margin:0;background:#f2f4f7;color:#1d2433}
header{background:#0f172a;color:#fff;padding:20px 24px;border-bottom:3px solid #0284c7}
.inner{max-width:1080px;margin:0 auto}
h1{font-size:20px;margin:0 0 8px}
.sub{color:#cbd5e1;font-size:12.5px;margin:0}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:16px}
.stat{background:#1e293b;border:1px solid #334155;border-radius:8px;padding:12px 14px}
.stat b{display:block;font-size:22px;color:#7dd3fc}
.stat.ok b{color:#4ade80}
.stat.warn b{color:#fbbf24}
.stat.crit b{color:#f87171}
.stat span{font-size:11.5px;color:#cbd5e1}
main{max-width:1080px;margin:0 auto;padding:24px}
h2{font-size:14px;text-transform:uppercase;letter-spacing:.04em;color:#334155;border-bottom:2px solid #e2e8f0;padding-bottom:6px;margin:22px 0 12px}
.vid-card{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:16px;margin-bottom:20px;text-align:center}
.vid-card video{max-width:100%%;max-height:560px;border-radius:8px;border:1px solid #cbd5e1;background:#0f172a}
.dl-btn{display:inline-block;margin-top:10px;background:#0f172a;color:#fff;text-decoration:none;font-size:12px;font-weight:600;padding:7px 14px;border-radius:6px}
.dl-btn:hover{background:#0284c7}
table{width:100%%;border-collapse:collapse;background:#fff;border:1px solid #e2e8f0;border-radius:8px;overflow:hidden}
th,td{padding:10px 12px;border-bottom:1px solid #e2e8f0;font-size:12.5px;text-align:left}
th{background:#eef2f7;color:#475569;font-size:11px;text-transform:uppercase}
.pill{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700}
.pill.ok{background:#dcfce7;color:#166534}
.pill.warn{background:#fef3c7;color:#92400e}
.pill.crit{background:#fee2e2;color:#991b1b}
.muted{color:#64748b;font-size:11px}
</style></head><body>
<header><div class="inner">
  <h1>Comparativa de regresion TalkBack - %(title)s</h1>
  <p class="sub">Antes: v%(b_ver)s (%(b_n)d pasos) · Despues: v%(a_ver)s (%(a_n)d pasos) · TalkBack Audit v%(ver)s</p>
  <div class="stats">
    <div class="stat ok"><b>%(n_fixed)d</b><span>reglas WCAG resueltas</span></div>
    <div class="stat warn"><b>%(n_pers)d</b><span>reglas persistentes</span></div>
    <div class="stat crit"><b>%(n_new)d</b><span>regresiones nuevas</span></div>
  </div>
</div></header>
<main>
  %(vid_block)s
  <h2>Detalle por regla WCAG 2.2</h2>
  <table>
    <thead><tr><th>Regla</th><th>Estado</th><th>Antes</th><th>Despues</th><th>Detalle</th></tr></thead>
    <tbody>%(rows)s</tbody>
  </table>
</main></body></html>""" % {
        "title": html.escape(v_title),
        "ver": html.escape(VERSION),
        "b_ver": html.escape(str(b_ver)),
        "a_ver": html.escape(str(a_ver)),
        "b_n": len(b_steps),
        "a_n": len(a_steps),
        "n_fixed": len(fixed_rules),
        "n_pers": len(persisting_rules),
        "n_new": len(new_rules),
        "vid_block": vid_block,
        "rows": "\n".join(rows_html),
    }

    html_path = os.path.join(out_dir, "diff_report.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(doc)
    return html_path, (os.path.join(out_dir, video_rel) if video_rel else None)
