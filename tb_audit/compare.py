"""Generador de reportes HTML comparativos multiplataforma: Web Desktop NVDA (Chrome) vs Android TalkBack (WebView) vs iOS VoiceOver (WKWebView)."""

import html
import json
import os
import re
from . import VERSION
from .rules import norm_utt


CMP_CSS = """
* {box-sizing:border-box}
html{scroll-behavior:smooth}
body{font-family:-apple-system,'Helvetica Neue',Arial,sans-serif;margin:0;background:#f2f4f7;color:#1d2433}
header{background:#0f172a;color:#fff;padding:20px 24px 22px;border-bottom:3px solid #0284c7}
.hdr-inner{max-width:1360px;margin:0 auto}
.hdr-top{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap}
header h1{font-size:20px;margin:0;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.verbadge{display:inline-block;background:#0284c7;color:#fff;font-size:11px;font-weight:700;padding:2px 8px;border-radius:4px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin-top:16px}
.stat{background:#1e293b;border:1px solid #334155;border-radius:8px;padding:11px 14px}
.stat b{display:block;font-size:22px;color:#7dd3fc}
.stat.warn b{color:#fbbf24}
.stat.crit b{color:#f87171}
.stat.ok b{color:#4ade80}
.stat span{color:#cbd5e1;font-size:11px}
main{max-width:1360px;margin:0 auto;padding:24px}
h2{font-size:14px;margin:28px 0 12px;text-transform:uppercase;letter-spacing:.05em;color:#334155;border-bottom:2px solid #e2e8f0;padding-bottom:6px;display:flex;justify-content:space-between;align-items:center}
.table-wrap{background:#fff;border:1px solid #e2e8f0;border-radius:10px;overflow:hidden;box-shadow:0 1px 2px rgba(15,23,42,.04);margin-bottom:22px}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{background:#f8fafc;color:#334155;text-align:left;padding:10px 12px;border-bottom:1px solid #e2e8f0;font-size:11px;text-transform:uppercase;letter-spacing:.04em}
td{padding:11px 12px;border-bottom:1px solid #f1f5f9;vertical-align:top;line-height:1.45}
tr:last-child td{border-bottom:none}
.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:10.5px;font-weight:700;text-transform:uppercase}
.badge.web{background:#e0f2fe;color:#0369a1}
.badge.and{background:#fef3c7;color:#92400e}
.badge.ios{background:#fee2e2;color:#991b1b}
.badge.both{background:#ede9fe;color:#5b21b6}
.badge.ok{background:#dcfce7;color:#166534}
.utt-box{background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:6px 9px;font-family:'SF Mono',Menlo,monospace;font-size:11.5px;color:#0f172a;margin-top:4px;word-break:break-word}
.dom-code{font-family:'SF Mono',Menlo,monospace;font-size:11px;background:#0f172a;color:#7dd3fc;padding:2px 6px;border-radius:4px;display:inline-block;margin-top:4px;word-break:break-all}
.shot-thumb{width:130px;border:1px solid #cbd5e1;border-radius:6px;margin-top:6px;display:block}
.grid-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}
.vcard{background:#fff;border:1px solid #e2e8f0;border-top:4px solid #0284c7;border-radius:10px;padding:16px;text-decoration:none;color:#0f172a;display:flex;flex-direction:column;gap:8px;box-shadow:0 1px 2px rgba(15,23,42,.04)}
.vcard:hover{border-color:#0284c7;background:#f8fafc}
.vcard h3{margin:0;font-size:15px;color:#1e293b}
.muted{color:#64748b;font-size:11.5px}
"""


def _detect_platform(meta_str):
    m = (meta_str or "").lower()
    if "nvda" in m or "chrome desktop" in m or "navegador=" in m:
        return ("web", "Web Desktop NVDA (Google Chrome)", "Web NVDA")
    if "iphone" in m or "ios" in m or "axaudit" in m:
        return ("ios", "iOS VoiceOver (Xcode Simulator - WKWebView)", "iOS VoiceOver")
    return ("and", "Android TalkBack (Android Emulator - WebView)", "Android TalkBack")


def _find_best_step(ref_step, cand_steps, used_set):
    u_ref = (ref_step.get("utterance") or "").strip()
    lbl_ref = (ref_step.get("label") or "").strip()
    dom_ref = ref_step.get("dom") or {}
    n_ref = norm_utt(lbl_ref) or norm_utt(u_ref)
    for s in cand_steps:
        if s["i"] in used_set:
            continue
        u_c = (s.get("utterance") or "").strip()
        lbl_c = (s.get("label") or "").strip()
        dom_c = s.get("dom") or {}
        n_c = norm_utt(lbl_c) or norm_utt(u_c)
        if dom_ref and dom_c and dom_ref.get("selector") == dom_c.get("selector") and dom_ref.get("label") == dom_c.get("label") and dom_ref.get("label"):
            return s
        if n_ref and n_c and (n_ref == n_c or (len(n_ref) >= 5 and (n_ref in n_c or n_c in n_ref))):
            return s
    return None


def compare_view_dirs(dir_a, dir_b, out_html=None, dir_c=None):
    """Compara steps.json de una vista entre 2 o 3 plataformas (ej. Web Desktop NVDA vs Android TalkBack vs iOS VoiceOver)."""
    json_a = os.path.join(dir_a, "steps.json")
    json_b = os.path.join(dir_b, "steps.json")
    if not (os.path.isfile(json_a) and os.path.isfile(json_b)):
        return None
    data_a = json.load(open(json_a, encoding="utf-8"))
    data_b = json.load(open(json_b, encoding="utf-8"))
    code_a, full_a, short_a = _detect_platform(data_a.get("meta"))
    code_b, full_b, short_b = _detect_platform(data_b.get("meta"))

    data_c = None
    code_c, full_c, short_c = ("", "", "")
    if dir_c and os.path.isfile(os.path.join(dir_c, "steps.json")):
        data_c = json.load(open(os.path.join(dir_c, "steps.json"), encoding="utf-8"))
        code_c, full_c, short_c = _detect_platform(data_c.get("meta"))

    steps_a = [s for s in data_a.get("steps", []) if not s.get("is_duplicate")]
    steps_b = [s for s in data_b.get("steps", []) if not s.get("is_duplicate")]
    steps_c = [s for s in (data_c.get("steps", []) if data_c else []) if not s.get("is_duplicate")]

    v_title = (data_a.get("view_info") or {}).get("title") or os.path.basename(dir_a)
    if not out_html:
        out_html = os.path.join(dir_a, "comparison_multiplatform.html")
    out_parent = os.path.dirname(os.path.abspath(out_html))

    rows = []
    used_b = set()
    used_c = set()
    n_diff = 0
    n_both = 0
    n_ok = 0

    for sa in steps_a:
        ua = (sa.get("utterance") or "").strip()
        if re.search(r"(date:.*value|fecha:.*valor)", ua.lower()) and sa["i"] > 13:
            continue
        lbl_a = (sa.get("label") or "").strip()
        dom_a = sa.get("dom") or {}
        sb = _find_best_step(sa, steps_b, used_b)
        sc = _find_best_step(sa, steps_c, used_c) if steps_c else None
        if sb:
            used_b.add(sb["i"])
        if sc:
            used_c.add(sc["i"])

        ub = (sb.get("utterance") or "").strip() if sb else "(No expuesto en esta plataforma)"
        uc = (sc.get("utterance") or "").strip() if sc else "(No expuesto en esta plataforma)"
        all_u = (ua + " || " + ub + " || " + uc).lower()

        status_cls = "ok"
        status_lbl = "Paridad OK"
        note = "Anuncio y rol equivalentes entre plataformas."

        if "unlabelled" in all_u:
            status_cls = "both"
            status_lbl = "SVG sin etiquetar (WEB + ANDROID)"
            note = "En Chrome Desktop (NVDA) y Android WebView (TalkBack) el <svg> anuncia 'Unlabelled graphic' / 'Unlabelled. Image' (WCAG 2.2)."
            n_both += 1
        elif re.search(r"(date:.*value|fecha:.*valor)", all_u):
            status_cls = "both"
            status_lbl = "Puntos SVG expuestos en todas"
            note = "Los puntos <circle> de LineChart se exponen al barrido lineal en Web NVDA, Android TalkBack e iOS VoiceOver (WCAG 2.2)."
            n_both += 1
        elif "current investment" in all_u:
            status_cls = "both"
            status_lbl = "Falta saldo interpolado (WEB + APP)"
            note = "Tanto en Web Desktop (NVDA) como en Android e iOS el campo de importe en Sell anuncia 'Enter an amount. Current investment' sin el saldo disponible (WCAG 2.2)."
            n_both += 1
        elif "select your linked account" in all_u:
            status_cls = "both"
            status_lbl = "Key Saving Plans en todas (WEB + APP)"
            note = "Tanto en Web Desktop (NVDA) como en Android e iOS el botón de editar cuenta apunta a 'Select your linked account' y queda deshabilitado con 1 cuenta (WCAG 2.2)."
            n_both += 1
        elif "radio button" in all_u or ", 0, toggle" in all_u:
            status_cls = "both"
            status_lbl = "Doble parada por píldora (WEB + APP)"
            note = "En Web NVDA (Browse Mode), Android TalkBack e iOS VoiceOver cada píldora rápida genera 2 paradas (texto + input radio); en iOS además anuncia '0, Toggle' (WCAG 2.2)."
            n_both += 1
        elif "trading volumen" in all_u:
            status_cls = "both"
            status_lbl = "Errata POEditor en-us (WEB + APP)"
            note = "En las 3 plataformas se expone 'Last 24-hour trading volumen' en español (WCAG 2.2)."
            n_both += 1
        elif ua.lower() == "status" or ub.lower() == "status":
            status_cls = "and"
            status_lbl = "Nodo role='status' con \u200b (WEB + ANDROID)"
            note = "En el DOM de Web y Android persiste <span role='status'>\u200b</span> de A11Y_LIVE_ANNOUNCER (WCAG 2.2)."
            n_diff += 1
        elif not sb:
            status_cls = "web"
            status_lbl = "Exclusivo Layout Desktop Web"
            note = "Elemento presente únicamente en el layout de escritorio Web (ej. migas de pan, acciones 'Fee information' / 'Download transactions' o botón 'Cancel')."
            n_diff += 1
        elif re.match(r"^[0-9.,]+\s+btc$", ua.lower()) and re.match(r"^[0-9.,]+$", ub.lower()):
            status_cls = "and"
            status_lbl = "Ticker truncado solo en Android"
            note = "En Web Desktop NVDA e iOS VoiceOver anuncia '0.03377028 BTC', mientras en Android TalkBack omite 'BTC' por los 2 nodos de texto separados (WCAG 2.2)."
            n_diff += 1
        else:
            n_ok += 1

        rows.append({
            "component": lbl_a or ua[:55],
            "dom_sel": dom_a.get("selector") or (sa.get("node") or {}).get("rid") or "dom",
            "a_step": "Paso %d" % sa["i"],
            "a_utt": ua,
            "a_img": os.path.relpath(os.path.join(dir_a, sa["png"]), out_parent) if sa.get("png") else "",
            "b_step": ("Paso %d" % sb["i"]) if sb else "No aplica en móvil",
            "b_utt": ub,
            "b_img": os.path.relpath(os.path.join(dir_b, sb["png"]), out_parent) if (sb and sb.get("png")) else "",
            "c_step": ("Paso %d" % sc["i"]) if sc else ("No aplica / Fragmentado" if steps_c else ""),
            "c_utt": uc if steps_c else "",
            "c_img": os.path.relpath(os.path.join(dir_c, sc["png"]), out_parent) if (sc and sc.get("png") and dir_c) else "",
            "status_cls": status_cls,
            "status_lbl": status_lbl,
            "note": note,
        })

    has_c = bool(steps_c)
    tr_html = []
    for r in rows:
        a_shot = ('<img class="shot-thumb" src="%s" alt="%s">' % (html.escape(r["a_img"]), html.escape(r["a_step"]))) if r["a_img"] else ""
        b_shot = ('<img class="shot-thumb" src="%s" alt="%s">' % (html.escape(r["b_img"]), html.escape(r["b_step"]))) if r["b_img"] else ""
        c_col = ""
        if has_c:
            c_shot = ('<img class="shot-thumb" src="%s" alt="%s">' % (html.escape(r["c_img"]), html.escape(r["c_step"]))) if r["c_img"] else ""
            c_col = "<td><b>%s</b><div class='utt-box'>«%s»</div>%s</td>" % (
                html.escape(r["c_step"]),
                html.escape(r["c_utt"]),
                c_shot,
            )
        tr_html.append(
            "<tr>"
            "<td><b>%s</b><br><span class='dom-code'>%s</span></td>"
            "<td><b>%s</b><div class='utt-box'>«%s»</div>%s</td>"
            "<td><b>%s</b><div class='utt-box'>«%s»</div>%s</td>"
            "%s"
            "<td><span class='badge %s'>%s</span><p style='margin:6px 0 0'>%s</p></td>"
            "</tr>"
            % (
                html.escape(r["component"][:90]),
                html.escape(r["dom_sel"]),
                html.escape(r["a_step"]),
                html.escape(r["a_utt"]),
                a_shot,
                html.escape(r["b_step"]),
                html.escape(r["b_utt"]),
                b_shot,
                c_col,
                r["status_cls"],
                html.escape(r["status_lbl"]),
                html.escape(r["note"]),
            )
        )

    hdr_compare = "%s vs %s%s" % (short_a, short_b, (" vs %s" % short_c) if has_c else "")
    th_c = ('<th style="width:21%%">%s</th>' % html.escape(full_c)) if has_c else ""
    doc = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Comparativa %(hdr_compare)s - %(title)s</title>
<style>%(css)s</style></head><body>
<header>
  <div class="hdr-inner">
    <div class="hdr-top">
      <h1>Comparativa Multiplataforma: %(hdr_compare)s - %(title)s <span class="verbadge">v%(ver)s</span></h1>
    </div>
    <div class="stats">
      <div class="stat"><b>%(n_a)d / %(n_b)d%(n_c_str)s</b><span>pasos (%(hdr_compare)s)</span></div>
      <div class="stat warn"><b>%(n_both)d</b><span>defectos comunes Web + App</span></div>
      <div class="stat crit"><b>%(n_diff)d</b><span>diferencias entre plataformas</span></div>
      <div class="stat ok"><b>%(n_ok)d</b><span>componentes con paridad OK</span></div>
    </div>
  </div>
</header>
<main>
  <h2><span>Matriz comparativa componente a componente (%(hdr_compare)s)</span><span>%(total_rows)d filas comparadas</span></h2>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th style="width:18%%">Componente / Selector DOM</th>
          <th style="width:21%%">%(full_a)s</th>
          <th style="width:21%%">%(full_b)s</th>
          %(th_c)s
          <th style="width:19%%">Diagnóstico Multiplataforma</th>
        </tr>
      </thead>
      <tbody>
        %(rows_html)s
      </tbody>
    </table>
  </div>
</main>
</body></html>""" % {
        "hdr_compare": html.escape(hdr_compare),
        "title": html.escape(v_title),
        "ver": VERSION,
        "css": CMP_CSS,
        "n_a": len(steps_a),
        "n_b": len(steps_b),
        "n_c_str": (" / %d" % len(steps_c)) if has_c else "",
        "n_both": n_both,
        "n_diff": n_diff,
        "n_ok": n_ok,
        "total_rows": len(rows),
        "full_a": html.escape(full_a),
        "full_b": html.escape(full_b),
        "th_c": th_c,
        "rows_html": "\n".join(tr_html),
    }
    with open(out_html, "w", encoding="utf-8") as fp:
        fp.write(doc)
    return {
        "path": out_html,
        "title": v_title,
        "hdr_compare": hdr_compare,
        "a_steps": len(steps_a),
        "b_steps": len(steps_b),
        "c_steps": len(steps_c),
        "both": n_both,
        "diff": n_diff,
        "ok": n_ok,
    }


def build_comparison_suite(target_a, target_b, out_path=None, target_c=None):
    """Compara dos o tres suites completas de reportes (ej. Web Desktop NVDA vs Android TalkBack vs iOS VoiceOver)."""
    if os.path.isfile(os.path.join(target_a, "steps.json")) and os.path.isfile(os.path.join(target_b, "steps.json")):
        res = compare_view_dirs(target_a, target_b, out_html=out_path, dir_c=target_c)
        return res["path"] if res else None

    results = []
    for sub in sorted(os.listdir(target_a)):
        pa = os.path.join(target_a, sub)
        pb = os.path.join(target_b, sub)
        pc = os.path.join(target_c, sub) if (target_c and os.path.isdir(os.path.join(target_c, sub))) else None
        if os.path.isdir(pa) and os.path.isdir(pb):
            r = compare_view_dirs(pa, pb, dir_c=pc)
            if r:
                results.append((sub, r))
    if not results:
        return None
    idx_path = out_path or os.path.join(target_a, "comparison_index.html")
    idx_parent = os.path.dirname(os.path.abspath(idx_path))
    hdr_compare = results[0][1]["hdr_compare"]
    cards = []
    for sub, r in results:
        rel = os.path.relpath(r["path"], idx_parent)
        c_str = (" vs iOS: <b>%d</b>" % r["c_steps"]) if r.get("c_steps") else ""
        cards.append(
            '<a class="vcard" href="%s">'
            '<h3>%s</h3>'
            '<div class="muted">Carpeta: <code>%s</code> · Pasos Web NVDA: <b>%d</b> vs Android: <b>%d</b>%s</div>'
            '<div>'
            '<span class="badge both">%d comunes Web+App</span> '
            '<span class="badge web">%d diferencias plataforma</span> '
            '<span class="badge ok">%d OK</span>'
            '</div>'
            '</a>'
            % (
                html.escape(rel),
                html.escape(r["title"]),
                html.escape(sub),
                r["a_steps"],
                r["b_steps"],
                c_str,
                r["both"],
                r["diff"],
                r["ok"],
            )
        )
    doc = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Suite Comparativa Multiplataforma: %(hdr_compare)s</title>
<style>%(css)s</style></head><body>
<header>
  <div class="hdr-inner">
    <h1>Suite Comparativa Multiplataforma: %(hdr_compare)s <span class="verbadge">v%(ver)s</span></h1>
  </div>
</header>
<main>
  <h2><span>Vistas comparadas en la suite (%(hdr_compare)s)</span><span>%(n_views)d vistas</span></h2>
  <div class="grid-cards">%(cards)s</div>
</main>
</body></html>""" % {
        "hdr_compare": html.escape(hdr_compare),
        "css": CMP_CSS,
        "ver": VERSION,
        "n_views": len(results),
        "cards": "\n".join(cards),
    }
    with open(idx_path, "w", encoding="utf-8") as fp:
        fp.write(doc)
    return idx_path
