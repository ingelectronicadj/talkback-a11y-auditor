"""Persistencia steps.json, generador de reporte HTML ejecutivo e índice de suite (v0.3.0)."""

import datetime
import glob
import html
import json
import os
import re
import shutil
import zipfile
from . import VERSION
from .cdp import match_dom_element
from .config import load_config, role_of
from .rules import (
    analyze_heading_hierarchy,
    analyze_sequence_issues,
    analyze_unreachable_elements,
    is_a11y_relevant,
    node_issues,
    node_key,
    text_a11y_issues,
)
from .vision import effective_label, match_node, ocr_step_info
from .wcag_catalog import (
    WCAG_CATALOG,
    WCAG_ORDER,
    classify_issue_key,
    resolve_wcag_meta,
)

CSS = """
* {box-sizing:border-box}
html{scroll-behavior:smooth}
body{font-family:-apple-system,'Helvetica Neue',Arial,sans-serif;margin:0;background:#f2f4f7;color:#1d2433}
header{background:#0f172a;color:#fff;padding:20px 24px 22px;border-bottom:3px solid #0284c7}
.hdr-inner{max-width:1180px;margin:0 auto}
.hdr-top{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap}
header h1{font-size:20px;margin:0;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.verbadge{display:inline-block;background:#0284c7;color:#fff;font-size:11px;font-weight:700;
          padding:2px 8px;border-radius:4px;letter-spacing:.04em}
.view-banner{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:10px;padding:8px 12px;
             background:#16243d;border:1px solid #1e3a5f;border-left:4px solid #38bdf8;border-radius:6px;font-size:13px;color:#e2e8f0}
.view-banner b{color:#fff;font-size:14px}
.view-banner code{background:#0f172a;color:#7dd3fc;padding:2px 7px;border-radius:4px;font-size:11.5px;border:1px solid #334155}
.meta-bar{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
.meta-chip{background:#1e293b;border:1px solid #334155;color:#cbd5e1;font-size:11px;
           padding:3px 9px;border-radius:5px;line-height:1.35}
.hdr-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.navlink,.btn-print{color:#e2e8f0;background:#1e293b;border:1px solid #334155;text-decoration:none;
                    font-size:11px;font-weight:600;padding:6px 11px;border-radius:6px;cursor:pointer;white-space:nowrap}
.navlink:hover,.btn-print:hover{background:#334155;color:#fff}
.stats{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px;margin-top:16px}
.stat{background:#1e293b;border:1px solid #334155;border-radius:8px;padding:11px 14px;
      display:flex;flex-direction:column;justify-content:space-between;gap:4px;min-width:0}
.stat b{display:block;font-size:22px;line-height:1.15;color:#7dd3fc;white-space:nowrap}
.stat .stat-sep{color:#64748b;font-weight:400;font-size:18px;margin:0 2px}
.stat .stat-lbl{color:#cbd5e1;font-size:11px;line-height:1.3}
.stat.warn b{color:#fbbf24}
.stat.crit b{color:#f87171}
main{max-width:1180px;margin:0 auto;padding:24px}
h2{font-size:14px;margin:30px 0 12px;text-transform:uppercase;letter-spacing:.05em;color:#334155;
   border-bottom:2px solid #e2e8f0;padding-bottom:6px;display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap}
.exec-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,440px),1fr));gap:14px;margin-bottom:18px}
.rule-card{background:#fff;border:1px solid #e2e8f0;border-left:4px solid #f59e0b;border-radius:8px;padding:15px 16px;
           box-shadow:0 1px 2px rgba(15,23,42,.04);min-width:0;overflow:hidden}
.rule-card.crit{border-left-color:#dc2626}
.rule-card.info{border-left-color:#0284c7}
.rule-hdr{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap}
.rule-title{font-size:13px;font-weight:700;color:#0f172a;overflow-wrap:anywhere}
.rule-tax{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-bottom:8px;font-size:11px;color:#475569}
.tax-badge{background:#f1f5f9;border:1px solid #cbd5e1;border-radius:4px;padding:1px 6px;font-weight:600;color:#334155}
.tax-lvl{background:#0f172a;color:#fff;border-radius:4px;padding:1px 6px;font-weight:700;font-size:10px}
.tax-link{color:#0284c7;text-decoration:none;font-weight:600}
.tax-link:hover{text-decoration:underline}
.sev{font-size:10px;font-weight:700;text-transform:uppercase;padding:2px 7px;border-radius:4px;letter-spacing:.04em}
.sev.crit{background:#fee2e2;color:#991b1b}
.sev.med{background:#fef3c7;color:#92400e}
.sev.low{background:#e0f2fe;color:#075985}
.rule-desc{font-size:12px;color:#334155;margin-bottom:8px;line-height:1.5;overflow-wrap:anywhere;word-break:break-word}
.rule-impact{font-size:11px;color:#475569;margin-bottom:8px;overflow-wrap:anywhere}
.sr-cmp{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px;margin-bottom:8px;font-size:11px}
.sr-box{border-radius:6px;padding:7px 10px;border:1px solid #e2e8f0;min-width:0;overflow-wrap:anywhere;word-break:break-word;line-height:1.45}
.sr-box.bad{background:#fef2f2;border-color:#fecaca;color:#7f1d1d}
.sr-box.good{background:#f0fdf4;border-color:#bbf7d0;color:#14532d}
.sr-box b{display:block;font-size:10px;text-transform:uppercase;letter-spacing:.04em;margin-bottom:3px}
.rule-rec{font-size:11px;color:#1e293b;background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:7px 10px;margin-bottom:8px;overflow-wrap:anywhere;word-break:break-word;line-height:1.45}
.rem-cmp{display:grid;grid-template-columns:1fr;gap:8px;margin-bottom:10px;font-size:11px}
.rem-box{border-radius:6px;padding:8px 10px;border:1px solid #cbd5e1;background:#f8fafc;color:#1e293b;line-height:1.45;min-width:0;overflow-wrap:anywhere;word-break:break-word}
.rem-box.opta{border-left:3px solid #0284c7}
.rem-box.optb{border-left:3px solid #7c3aed}
.rem-box b{display:block;font-size:10px;text-transform:uppercase;letter-spacing:.04em;margin-bottom:3px;color:#0f172a}
.inl-code{font-family:'SF Mono',Menlo,Consolas,monospace;font-size:10.5px;background:rgba(15,23,42,.07);color:#0f172a;
          padding:1px 5px;border-radius:4px;border:1px solid rgba(15,23,42,.12);overflow-wrap:anywhere;word-break:break-word}
.code-snip{background:#0f172a;color:#e2e8f0;border-radius:6px;padding:8px 10px;margin:6px 0 2px;
           font-family:'SF Mono',Menlo,Consolas,monospace;font-size:11px;line-height:1.48;overflow-x:auto;
           white-space:pre-wrap;overflow-wrap:anywhere;word-break:normal;border:1px solid #1e293b}
.jira-chip{display:inline-block;background:#eff6ff;border:1px solid #93c5fd;color:#1d4ed8;text-decoration:none;
           font-size:10px;font-weight:700;padding:1px 7px;border-radius:4px}
.jira-chip:hover{background:#1d4ed8;color:#fff;border-color:#1d4ed8}
.step-links{display:flex;gap:5px;flex-wrap:wrap}
.step-chip{display:inline-block;background:#f1f5f9;border:1px solid #cbd5e1;color:#0f172a;text-decoration:none;
           font-size:11px;font-weight:600;padding:2px 7px;border-radius:4px}
.step-chip:hover{background:#0f172a;color:#fff;border-color:#0f172a}
.filmstrip{display:flex;gap:8px;overflow-x:auto;padding:10px 4px 12px;background:#fff;border:1px solid #e2e8f0;
           border-radius:8px;margin-bottom:16px}
.fnode{flex:0 0 135px;border:1px solid #cbd5e1;border-radius:6px;padding:7px 8px;text-decoration:none;color:#1e2933;
       background:#f8fafc;font-size:11px;display:flex;flex-direction:column;gap:4px}
.fnode:hover{border-color:#0284c7;background:#f0f9ff}
.fnode .fn-top{display:flex;justify-content:space-between;align-items:center;font-weight:700;color:#475569;font-size:10px}
.fnode .dot{width:8px;height:8px;border-radius:50%;background:#64748b;display:inline-block}
.fnode.crit .dot{background:#dc2626}
.fnode.warn .dot{background:#f59e0b}
.fnode.modal .dot{background:#7c3aed}
.fnode .fn-txt{color:#0f172a;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:12px 0 16px;justify-content:space-between}
.flt-group{display:flex;gap:6px;flex-wrap:wrap}
.flt{appearance:none;border:1px solid #cbd5e1;background:#fff;color:#334155;border-radius:6px;
     padding:6px 12px;font-size:12px;font-weight:600;cursor:pointer}
.flt.active{background:#0f172a;color:#fff;border-color:#0f172a}
.searchbox{border:1px solid #cbd5e1;border-radius:6px;padding:6px 11px;font-size:12px;min-width:240px;background:#fff}
.step{display:flex;gap:18px;background:#fff;border:1px solid #e2e8f0;border-radius:10px;
      padding:14px;margin:12px 0;box-shadow:0 1px 2px rgba(15,23,42,.05);transition:box-shadow .2s,border-color .2s}
.step:target{border-color:#0284c7;box-shadow:0 0 0 3px rgba(2,132,199,.2)}
.step.is-dup{opacity:.78;border-style:dashed}
.step.is-noise{background:#f8fafc}
.step .shotwrap{flex:0 0 230px}
.step img.shot{width:230px;border:1px solid #cbd5e1;border-radius:6px;display:block;cursor:zoom-in}
.step .body{flex:1;min-width:0}
.step .n{font-size:11px;font-weight:700;color:#64748b;letter-spacing:.05em;margin-bottom:6px;display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.pill{display:inline-block;padding:2px 7px;border-radius:4px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.04em}
.pill.scr{background:#e0f2fe;color:#0369a1}
.pill.skel{background:#fef3c7;color:#92400e;border:1px solid #f59e0b}
.pill.loadok{background:#dcfce7;color:#166534;border:1px solid #22c55e}
.pill.dup{background:#f1f5f9;color:#475569}
.pill.modal{background:#ede9fe;color:#5b21b6}
.pill.noise{background:#e2e8f0;color:#475569}
.pill.coords{background:#f8fafc;border:1px solid #e2e8f0;color:#64748b;font-family:Menlo,monospace;text-transform:none}
.step .say{font-size:15px;font-weight:600;line-height:1.45;margin-bottom:8px;word-break:break-word;color:#0f172a}
.step .say.none{color:#94a3b8;font-weight:400;font-style:italic}
.rolebadge{display:inline-block;background:#e0e7ff;color:#3730a3;border-radius:4px;
           padding:1px 7px;font-size:11px;font-weight:600;margin-left:6px;vertical-align:middle}
.nodeline{font-size:12px;color:#475569;margin-bottom:6px;word-break:break-word}
.dombox{background:#0f172a;color:#e2e8f0;border-radius:8px;margin:8px 0;border:1px solid #1e293b;
        font-family:'SF Mono',Menlo,Consolas,monospace;font-size:11px;line-height:1.5;overflow:hidden}
.dom-hdr{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;
         background:#1e293b;padding:6px 10px;border-bottom:1px solid #334155}
.dom-hdr-left{display:flex;align-items:center;gap:6px;flex-wrap:wrap;min-width:0}
.dom-badge{background:#0284c7;color:#fff;font-size:9.5px;font-weight:700;padding:1px 6px;border-radius:4px;letter-spacing:.04em}
.dom-sel-txt{color:#38bdf8;font-weight:700;overflow-wrap:anywhere}
.dom-attr-pill{background:#0f172a;border:1px solid #334155;color:#cbd5e1;font-size:10px;padding:1px 6px;border-radius:4px}
.dom-copy{appearance:none;background:#0f172a;border:1px solid #475569;color:#e2e8f0;font-size:10px;font-weight:600;
          padding:2px 8px;border-radius:4px;cursor:pointer;font-family:-apple-system,sans-serif}
.dom-copy:hover{background:#0284c7;border-color:#0284c7;color:#fff}
.dom-po-bar{display:flex;align-items:center;gap:6px;flex-wrap:wrap;background:#172033;padding:5px 10px;
            border-bottom:1px solid #1e293b;font-size:10.5px}
.po-pill{background:#854d0e;color:#fef08a;font-size:9.5px;font-weight:700;padding:1px 6px;border-radius:4px;text-transform:uppercase}
.po-key-txt{color:#fde047;font-weight:600;overflow-wrap:anywhere}
.po-origin-pill{background:#064e3b;border:1px solid #059669;color:#6ee7b7;font-size:10px;font-weight:600;padding:1px 6px;border-radius:4px;overflow-wrap:anywhere}
.po-origin-pill.warn{background:#451a03;border-color:#d97706;color:#fcd34d}
.dom-pre{margin:0;padding:8px 11px;white-space:pre-wrap;overflow-wrap:anywhere;word-break:normal;overflow-x:auto;color:#f8fafc}
.hl-tag{color:#7dd3fc;font-weight:600}
.hl-attr{color:#c4b5fd}
.hl-val{color:#86efac}
.hl-cm{color:#64748b;font-style:italic}
.flag{background:#fef3c7;border-left:3px solid #f59e0b;padding:5px 9px;margin:5px 0;
      font-size:11px;border-radius:0 4px 4px 0}
.flag::before{content:"";display:inline-block;width:6px;height:6px;border-radius:50%;
              background:#d97706;margin-right:6px;vertical-align:middle}
.flag.crit{background:#fee2e2;border-left-color:#dc2626;color:#7f1d1d}
.flag.crit::before{background:#dc2626}
.flag.noise{background:#f1f5f9;border-left-color:#94a3b8;color:#64748b}
.flag.noise::before{background:#94a3b8}
.screenbreak{display:flex;align-items:center;gap:10px;margin:22px 0 4px;
             color:#7c3aed;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.05em}
.screenbreak:before,.screenbreak:after{content:"";flex:1;height:1px;background:#ddd6fe}
.table-wrap{width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch;border-radius:8px;border:1px solid #e2e8f0;background:#fff}
table{border-collapse:collapse;width:100%;table-layout:fixed;background:#fff;min-width:640px}
col.c-lbl{width:34%}
col.c-role{width:15%}
col.c-state{width:18%}
col.c-find{width:33%}
th,td{border-bottom:1px solid #e2e8f0;padding:10px 12px;font-size:12px;vertical-align:middle;text-align:left;overflow-wrap:break-word}
th{background:#eef2f7;color:#475569;font-size:11px;text-transform:uppercase;letter-spacing:.04em;white-space:nowrap}
td.td-role,td.td-state{white-space:nowrap}
.state-pill{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600}
.state-pill.ok{background:#dcfce7;color:#166534}
.state-pill.warn{background:#fef3c7;color:#92400e}
.state-pill.muted{background:#f1f5f9;color:#64748b}
.muted{color:#94a3b8}
footer{max-width:1180px;margin:20px auto 40px;padding:0 24px;color:#64748b;font-size:11px;display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap}
#btn-top{position:fixed;bottom:24px;right:24px;z-index:80;background:#0f172a;color:#fff;border:1px solid #334155;
         border-radius:999px;padding:10px 14px;font-size:12px;font-weight:700;cursor:pointer;display:inline-flex;
         align-items:center;gap:7px;box-shadow:0 4px 12px rgba(15,23,42,.25);opacity:0;pointer-events:none;
         transform:translateY(8px);transition:opacity .2s,transform .2s,background .15s}
#btn-top.vis{opacity:1;pointer-events:auto;transform:translateY(0)}
#btn-top:hover{background:#0284c7;border-color:#0284c7}
#btn-top::before{content:"";display:inline-block;width:7px;height:7px;border-top:2px solid #fff;
                 border-left:2px solid #fff;transform:rotate(45deg);margin-top:3px}
#lb{position:fixed;inset:0;background:rgba(15,23,42,.88);display:none;flex-direction:column;align-items:center;
    justify-content:center;z-index:99;cursor:zoom-out;padding:16px}
#lb img{max-height:84vh;max-width:94vw;border-radius:8px;box-shadow:0 10px 25px rgba(0,0,0,.5)}
#lbcap{color:#f8fafc;font-size:13px;margin-top:10px;background:rgba(15,23,42,.9);padding:6px 14px;border-radius:6px;max-width:92vw;text-align:center}
@media (max-width: 960px){
  .stats{grid-template-columns:repeat(3,minmax(0,1fr))}
}
@media (max-width: 820px){
  header{padding:16px 18px}
  main{padding:16px}
  .toolbar{flex-direction:column;align-items:stretch}
  .searchbox{width:100%;min-width:0}
  footer{padding:0 16px;flex-direction:column}
}
@media (max-width: 600px){
  header h1{font-size:17px}
  .stats{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
  .stat{padding:9px 11px}
  .stat b{font-size:19px}
  .hdr-actions{width:100%}
  .navlink,.btn-print{flex:1 1 auto;text-align:center}
  .step{flex-direction:column;gap:12px;padding:12px}
  .step .shotwrap{flex:none;width:100%;display:flex;justify-content:center;background:#f8fafc;border-radius:6px;padding:6px}
  .step img.shot{width:auto;max-width:min(100%,240px);max-height:360px}
  #btn-top{bottom:16px;right:16px;padding:9px 12px}
}
@media print{
  header{background:#fff;color:#000;border-bottom:2px solid #000;padding:12px 0}
  .hdr-actions,.toolbar,.filmstrip,#btn-top{display:none!important}
  body{background:#fff}
  .step{break-inside:avoid;box-shadow:none;border:1px solid #ccc}
  .step.is-dup,.step.is-noise{display:none!important}
}
"""


def _format_inline_tokens(text):
    """Escapa texto y envuelve keys técnicas, etiquetas HTML y atributos ARIA en <code class='inl-code'>."""
    esc = html.escape(text or "")
    esc = re.sub(
        r"(?:'((?:a11y|mb_mc)_[a-zA-Z0-9_.*-]+)'|&lt;[^&]+&gt;|\{[A-Za-z0-9_.\s]+\})",
        lambda m: '<code class="inl-code">%s</code>' % (m.group(1) or m.group(0)),
        esc,
    )
    return esc


def _clean_and_pretty_html(raw_html):
    """Limpia clases hash de styled-components, spans decorativos vacíos y formatea el HTML con sangría."""
    s = (raw_html or "").strip()
    if not s:
        return ""
    # Eliminar spans vacíos de ripple/styled-components (<span class="sc-..."></span>)
    s = re.sub(r'<span\s+class="sc-[^"]*">\s*</span>', "", s)
    # Limpiar clases sc-* puramente autogeneradas (manteniendo clases semánticas como node-path-focus-border)
    def _clean_cls(m):
        classes = [
            c
            for c in m.group(1).split()
            if not c.startswith("sc-") and not re.match(r"^[a-zA-Z]{5,7}$", c)
        ]
        return (' class="%s"' % " ".join(classes)) if classes else ""

    s = re.sub(r'\s+class="([^"]*)"', _clean_cls, s)
    s = re.sub(r'\s+component="[^"]*"', "", s)
    # Acortar URLs largas de assets estáticos dejando '.../archivo.svg'
    s = re.sub(r'src="https?://[^"]*/([^/"]+)"', r'src=".../\1"', s)
    # Formatear etiquetas anidadas en líneas con sangría de 2 espacios
    tokens = re.split(r"(<[^>]+>)", s)
    lines = []
    indent = 0
    void_tags = {"img", "input", "br", "hr", "meta", "link", "circle", "path"}
    for tok in tokens:
        t = tok.strip()
        if not t:
            continue
        if t.startswith("</"):
            indent = max(0, indent - 1)
            lines.append("  " * indent + t)
        elif t.startswith("<") and not t.startswith("<!"):
            m_tag = re.match(r"<\s*([a-zA-Z0-9_-]+)", t)
            tname = m_tag.group(1).lower() if m_tag else ""
            is_self = t.endswith("/>") or tname in void_tags
            lines.append("  " * indent + t)
            if not is_self:
                indent += 1
        else:
            if lines and lines[-1].lstrip().startswith("<") and not lines[-1].lstrip().startswith("</"):
                lines[-1] = lines[-1] + t
            else:
                lines.append("  " * indent + t)
    # Colapsar elementos cortos de una sola línea (<p ...>texto</p> o <svg ...></svg>)
    merged = []
    i = 0
    while i < len(lines):
        cur = lines[i]
        if i + 1 < len(lines):
            nxt = lines[i + 1].strip()
            m_open = re.match(r"^(\s*)<([a-zA-Z0-9_-]+)\b[^>]*>([^<]*)$", cur)
            if m_open and nxt == "</%s>" % m_open.group(2) and len(cur + nxt) <= 105:
                merged.append(cur + nxt)
                i += 2
                continue
        merged.append(cur)
        i += 1
    return "\n".join(merged)


def _highlight_code(code_str):
    """Aplica resaltado de sintaxis HTML/JS seguro sobre un snippet de código."""
    if not code_str:
        return ""
    out_lines = []
    for line in code_str.splitlines():
        if line.strip().startswith("//") or line.strip().startswith("#"):
            out_lines.append('<span class="hl-cm">%s</span>' % html.escape(line))
            continue
        esc = html.escape(line)
        # Resaltar atributos nombre="valor"
        esc = re.sub(
            r"(\b[a-zA-Z_:][a-zA-Z0-9_.:-]*)(=)(&quot;[^&]*&quot;)",
            r'<span class="hl-attr">\1</span>\2<span class="hl-val">\3</span>',
            esc,
        )
        # Resaltar apertura/cierre de etiquetas HTML
        esc = re.sub(
            r"(&lt;/?[a-zA-Z0-9_-]+|/??&gt;)",
            r'<span class="hl-tag">\1</span>',
            esc,
        )
        out_lines.append(esc)
    return "\n".join(out_lines)


def _resolve_view_info(steps, dom_snapshot, view_info=None):
    """Determina el título de la vista, etiqueta corta de pestaña, ruta y alcance funcional."""
    vi = dict(view_info or {})
    ds = dom_snapshot if isinstance(dom_snapshot, dict) else {}
    route = vi.get("route_hash") or ds.get("routeHash") or ""
    if not route and ds.get("url") and "#" in ds["url"]:
        route = "#" + ds["url"].split("#", 1)[1]
    h1_txt = ds.get("viewHeading") or ""
    if not h1_txt:
        for el in ds.get("elements") or []:
            if el.get("tag") == "h1" and el.get("label"):
                h1_txt = el["label"].strip()
                break
    if not h1_txt:
        for s in steps:
            u = (s.get("utterance") or "").strip()
            if "encabezado 1" in u.lower() or "heading 1" in u.lower():
                h1_txt = re.sub(r"[\s.·]*(encabezado\s*1|heading\s*1).*$", "", u, flags=re.I).strip()
                break
            if s.get("page_title"):
                h1_txt = s["page_title"].strip()
                break
    scope_tag = vi.get("scope_tag") or ""
    if not scope_tag:
        r_low = (route + " " + h1_txt).lower()
        if "/buy" in r_low or "compra" in r_low:
            scope_tag = "Buy Flow"
        elif "/product-page" in r_low or "btc" in r_low or "bitcoin" in r_low:
            scope_tag = "Product Page"
        elif "/landing" in r_low or "criptomonedas" in r_low:
            scope_tag = "Landing Page"
    title = vi.get("title") or ""
    if not title:
        if h1_txt and scope_tag:
            title = "%s (%s)" % (scope_tag, h1_txt)
        else:
            title = h1_txt or scope_tag or "Vista Android"
    short_title = vi.get("short_title") or title
    return {
        "title": title,
        "short_title": short_title,
        "scope_tag": scope_tag,
        "route_hash": route,
        "h1": h1_txt,
    }


def save_steps_json(steps, tree_nodes, visited, out_dir, meta, dom_snapshot=None, view_info=None):
    data = {
        "version": VERSION,
        "meta": meta,
        "view_info": view_info,
        "dom_snapshot": dom_snapshot,
        "steps": [
            {
                "i": s["i"],
                "png": os.path.relpath(s["png"], out_dir),
                "node": s.get("node"),
                "dom": s.get("dom"),
                "utterance": s.get("utterance") or "",
                "raw_caption": s.get("raw_caption") or "",
                "page_title": s.get("page_title") or "",
                "is_skeleton": bool(s.get("is_skeleton")),
                "box": s.get("box"),
                "in_overlay": bool(s.get("in_overlay")),
                "label": s.get("label") or "",
                "screen_change": bool(s.get("screen_change")),
            }
            for s in steps
        ],
        "tree_nodes": tree_nodes,
        "visited": [list(k) for k in visited],
    }
    p = os.path.join(out_dir, "steps.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return p


def build_report(steps, tree_nodes, visited, out_dir, meta, dom_snapshot=None, view_info=None, cfg=None):
    tree_nodes = [n for n in tree_nodes if is_a11y_relevant(n)]
    analyze_sequence_issues(steps)
    headings_outline, head_issues = analyze_heading_hierarchy(dom_snapshot, steps)
    unreachable_els, unreach_issues = analyze_unreachable_elements(dom_snapshot, steps)
    step_map = {s["i"]: s for s in steps}
    for st_num, msg in head_issues + unreach_issues:
        target_s = step_map.get(st_num) or (steps[0] if steps else None)
        if target_s is not None:
            target_s.setdefault("seq_issues", [])
            if msg not in target_s["seq_issues"]:
                target_s["seq_issues"].append(msg)
    for s in steps:
        if not s.get("dom") and dom_snapshot:
            s["dom"] = match_dom_element(s.get("utterance"), s.get("label"), dom_snapshot)
    resolved_view = _resolve_view_info(steps, dom_snapshot, view_info)
    save_steps_json(
        steps, tree_nodes, visited, out_dir, meta, dom_snapshot=dom_snapshot, view_info=resolved_view
    )
    cards, film_nodes, all_issues = [], [], []
    by_rule = {}
    scr_idx = 1
    for s in steps:
        if s.get("screen_change"):
            scr_idx += 1
        node = s.get("node") or {}
        label = (s.get("label") or node.get("desc") or node.get("text") or "").strip()
        utt = (s.get("utterance") or "").strip()
        raw_cap = (s.get("raw_caption") or "").strip()
        ptitle = (s.get("page_title") or "").strip()
        is_skel = bool(s.get("is_skeleton"))
        is_load_ann = bool(s.get("is_loading_ann")) or utt.lower().strip() == "status"
        issues = []
        exp_loc = "es"
        if isinstance(dom_snapshot, dict) and dom_snapshot.get("lang"):
            exp_loc = dom_snapshot["lang"]
        elif "locale en" in (meta or "").lower():
            exp_loc = "en"
        if node:
            for it in node_issues(node):
                if it not in issues:
                    issues.append(it)
        for txt in (label, utt):
            for it in text_a11y_issues(txt, expected_locale=exp_loc):
                if it not in issues:
                    issues.append(it)
        for it in s.get("seq_issues") or []:
            if it not in issues:
                issues.append(it)
        noise = bool(s.get("in_overlay"))
        is_dup = bool(s.get("is_duplicate"))
        is_modal = bool(s.get("is_modal"))
        if noise:
            issues.append("Foco en la barra de TalkBack (ruido de captura, no pertenece a la app)")
        elif not utt and not label and not is_skel:
            issues.append("Sin texto anunciado ni etiqueta en el paso capturado")
        real_issues = [it for it in issues if "ruido" not in it]
        has_crit = any(
            "Focus Return" in it
            or "Moneda" in it
            or "Nombre accesible" in it
            or "Skeleton" in it
            or "Gráfica sin salto" in it
            or "Tropicalización" in it
            or "Propósito de los enlaces" in it
            or "Contenido omitido" in it
            for it in real_issues
        )
        if not is_dup:
            for it in real_issues:
                all_issues.append((s["i"], it))
                rk = classify_issue_key(it)
                by_rule.setdefault(rk, []).append((s["i"], it))
        flag_html = "".join(
            '<div class="flag%s">%s</div>'
            % (
                " noise"
                if "ruido" in i
                else (
                    " crit"
                    if (
                        "Focus Return" in i
                        or "Moneda" in i
                        or "Skeleton" in i
                        or "Gráfica sin salto" in i
                        or "Tropicalización" in i
                        or "Propósito de los enlaces" in i
                        or "Contenido omitido" in i
                    )
                    else ""
                ),
                html.escape(i),
            )
            for i in issues
        )
        img = os.path.relpath(s["png"], out_dir)
        if utt:
            say = '<div class="say">«%s»</div>' % html.escape(utt)
        elif is_skel:
            spoken = raw_cap or "sin anuncio de la app"
            say = (
                '<div class="say none">Anuncio capturado: «%s» - '
                "<b>Esperado al mostrar skeleton: «Loading %s» / «Cargando %s»</b></div>"
                % (html.escape(spoken), html.escape(ptitle), html.escape(ptitle))
            )
        else:
            say = '<div class="say none">(sin utterance capturada)</div>'
        role = role_of(node.get("cls", ""))
        nodeline = ""
        if node or label or ptitle or s.get("dom"):
            dom_lbl = (s.get("dom") or {}).get("label", "").strip()
            disp_lbl = label or dom_lbl or (("Vista / Drawer: %s" % ptitle) if ptitle else "(contenedor WebView)")
            nodeline = (
                '<div class="nodeline"><b>%s</b><span class="rolebadge">%s</span>'
                '<span class="muted">%s</span></div>'
                % (
                    html.escape(disp_lbl[:160]),
                    html.escape(role if node else "Vista / WebView"),
                    (" · %s" % html.escape(node["rid"])) if node.get("rid") else "",
                )
            )
        dom_el = s.get("dom")
        if dom_el:
            sel_str = dom_el.get("selector", "")
            attr_pills = []
            if dom_el.get("role") and ("[role=" not in sel_str):
                attr_pills.append('role="%s"' % dom_el["role"])
            if dom_el.get("tabindex"):
                attr_pills.append('tabindex="%s"' % dom_el["tabindex"])
            if dom_el.get("ariaLabelledby"):
                attr_pills.append('aria-labelledby="%s"' % dom_el["ariaLabelledby"])
            if dom_el.get("ariaHidden"):
                attr_pills.append('aria-hidden="%s"' % dom_el["ariaHidden"])
            attr_pills_html = "".join(
                '<span class="dom-attr-pill">%s</span>' % html.escape(a) for a in attr_pills
            )
            po_bar = ""
            if dom_el.get("poeditorKey") or dom_el.get("poeditorOrigin"):
                raw_orig = dom_el.get("poeditorOrigin") or "Origen: POEditor / Código"
                # Evitar repetir el nombre de la key si ya está en poeditorKey
                clean_orig = re.sub(r"\s*\((?:a11y|mb_mc)_[^)]+\)", "", raw_orig).strip()
                is_warn = any(
                    w in raw_orig.lower()
                    for w in ("inexistente", "inglés", "vacía", "sin tilde", "párrafo", "duplica", "literales", "invoca")
                )
                po_bar = (
                    '<div class="dom-po-bar">'
                    '<span class="po-pill">POEditor Key</span>'
                    '<code class="po-key-txt">%s</code>'
                    '<span class="po-origin-pill%s">%s</span>'
                    "</div>"
                    % (
                        html.escape(dom_el.get("poeditorKey") or "n/d"),
                        " warn" if is_warn else "",
                        html.escape(clean_orig),
                    )
                )
            pretty_html = _clean_and_pretty_html(dom_el.get("html", ""))
            nodeline += (
                '<div class="dombox">'
                '<div class="dom-hdr">'
                '<div class="dom-hdr-left">'
                '<span class="dom-badge">DOM WebView</span>'
                '<code class="dom-sel-txt">%s</code>%s'
                "</div>"
                '<button class="dom-copy" type="button" onclick="copyDomCode(this)">Copiar HTML</button>'
                "</div>"
                "%s"
                '<pre class="dom-pre" data-raw="%s"><code>%s</code></pre>'
                "</div>"
                % (
                    html.escape(sel_str),
                    attr_pills_html,
                    po_bar,
                    html.escape(pretty_html),
                    _highlight_code(pretty_html),
                )
            )
        brk = (
            '<div class="screenbreak">cambio de pantalla - Pantalla %d</div>' % scr_idx
            if s.get("screen_change")
            else ""
        )
        pills = ['<span class="pill scr">Pantalla %d</span>' % scr_idx]
        if s.get("is_loading_ann"):
            pills.append('<span class="pill loadok">anuncio carga detectado</span>')
        if is_skel:
            pills.append('<span class="pill skel">skeleton · %s</span>' % html.escape(ptitle[:36]))
        if is_modal:
            pills.append('<span class="pill modal">modal / tooltip</span>')
        if is_dup:
            pills.append('<span class="pill dup">anuncio repetido</span>')
        if noise:
            pills.append('<span class="pill noise">foco en overlay</span>')
        if s.get("box"):
            bx = s["box"]
            pills.append(
                '<span class="pill coords">foco [%d,%d - %d,%d]</span>'
                % (bx[0], bx[1], bx[2], bx[3])
            )
        cls_extra = (" is-dup" if is_dup else "") + (" is-noise" if noise else "")
        search_txt = html.escape(
            (utt + " " + raw_cap + " " + ptitle + " " + label + " " + " ".join(real_issues)).lower()
        )
        cap_txt = html.escape(
            "Paso %d - %s"
            % (
                s["i"],
                (utt or ("Skeleton: " + ptitle if is_skel else "") or label or "(sin anuncio)")[:120],
            )
        )
        cards.append(
            '%s<div id="step-%d" class="step%s" data-issues="%d" data-dup="%d" data-noise="%d" '
            'data-modal="%d" data-skel="%d" data-search="%s">'
            '<div class="shotwrap">'
            '<img class="shot" src="%s" data-full="%s" data-cap="%s" alt="paso %d"></div>'
            '<div class="body"><div class="n"><span>PASO %d</span>%s</div>%s%s%s</div></div>'
            % (
                brk,
                s["i"],
                cls_extra,
                1 if real_issues else 0,
                1 if is_dup else 0,
                1 if noise else 0,
                1 if is_modal else 0,
                1 if (is_skel or is_load_ann) else 0,
                search_txt,
                img,
                img,
                cap_txt,
                s["i"],
                s["i"],
                "".join(pills),
                say,
                nodeline,
                flag_html,
            )
        )
        if not is_dup and not noise:
            fcls = "crit" if has_crit else ("warn" if real_issues else ("modal" if is_modal else ""))
            short_txt = html.escape(
                (("Skeleton: " + ptitle) if (is_skel and not utt) else (utt or label or "(sin anuncio)"))[:42]
            )
            film_nodes.append(
                '<a class="fnode %s" href="#step-%d" title="%s">'
                '<div class="fn-top"><span>PASO %d</span><span class="dot"></span></div>'
                '<div class="fn-txt">%s</div></a>'
                % (fcls, s["i"], cap_txt, s["i"], short_txt)
            )

    cfg = cfg or load_config()
    jira_bugs = cfg.get("jira_bugs") or []
    jira_base = (cfg.get("jira_base_url") or "https://your-org.atlassian.net").rstrip("/")
    rule_to_jkeys = {}
    for jb in jira_bugs:
        for rid in (jb.get("rule_id") or "").split("/"):
            rid = rid.strip()
            if rid:
                rule_to_jkeys.setdefault(rid, []).append(jb["key"])

    exec_cards = []
    for rk in WCAG_ORDER:
        items = by_rule.get(rk)
        if not items:
            continue
        cat = WCAG_CATALOG[rk]
        wmeta = resolve_wcag_meta(cat["criterion"])
        sev_cls, sev_lbl = cat["sev"]
        card_cls = "crit" if sev_cls == "crit" else ("info" if sev_cls == "low" else "")
        step_nums = sorted({i for i, _ in items})
        chips = "".join('<a class="step-chip" href="#step-%d">Paso %d</a>' % (n, n) for n in step_nums)
        jkeys = rule_to_jkeys.get(cat["rule_id"], [])
        jira_badges = "".join(
            '<a class="jira-chip" href="%s/browse/%s" target="_blank" rel="noopener">%s</a>'
            % (html.escape(jira_base), html.escape(jk), html.escape(jk))
            for jk in jkeys
        )
        rem_html = ""
        if cat.get("opt_a") or cat.get("opt_b"):
            code_a_html = (
                '<pre class="code-snip"><code>%s</code></pre>' % _highlight_code(cat["code_a"])
                if cat.get("code_a")
                else ""
            )
            code_b_html = (
                '<pre class="code-snip"><code>%s</code></pre>' % _highlight_code(cat["code_b"])
                if cat.get("code_b")
                else ""
            )
            rem_html = (
                '<div class="rem-cmp">'
                '<div class="rem-box opta"><b>Opción A (POEditor / Config / UI)</b>%s%s</div>'
                '<div class="rem-box optb"><b>Opción B (Código React / ARIA)</b>%s%s</div>'
                "</div>"
                % (
                    _format_inline_tokens(cat.get("opt_a", "")),
                    code_a_html,
                    _format_inline_tokens(cat.get("opt_b", "")),
                    code_b_html,
                )
            )
        title_str = "%s - WCAG %s %s (%s)" % (
            cat["rule_id"], wmeta["criterion"], wmeta["name_es"], rk
        )
        exec_cards.append(
            '<div class="rule-card %s">'
            '<div class="rule-hdr"><span class="rule-title">%s</span>'
            '<span class="sev %s">Severidad %s · %d paso(s)</span></div>'
            '<div class="rule-tax">'
            '<span class="tax-lvl">Nivel %s</span>'
            '<span class="tax-badge">%s</span>'
            '<span class="tax-badge">%s</span>'
            '<span class="tax-badge">Técnicas: %s</span>'
            '%s'
            '<a class="tax-link" href="%s" target="_blank" rel="noopener">W3C Understanding %s</a>'
            "</div>"
            '<div class="rule-desc">%s</div>'
            '<div class="rule-impact"><b>Personas afectadas:</b> %s · <b>Caso de prueba:</b> %s</div>'
            '<div class="sr-cmp">'
            '<div class="sr-box bad"><b>Experiencia actual (TalkBack)</b>%s</div>'
            '<div class="sr-box good"><b>Comportamiento esperado (WCAG 2.2)</b>%s</div>'
            "</div>"
            '<div class="rule-rec"><b>Recomendación técnica:</b> %s</div>'
            '%s'
            '<div class="step-links">%s</div></div>'
            % (
                card_cls,
                html.escape(title_str),
                sev_cls,
                sev_lbl,
                len(step_nums),
                html.escape(wmeta["level"]),
                html.escape(wmeta["principle"]),
                html.escape(wmeta["guideline"]),
                html.escape(cat["techniques"]),
                jira_badges,
                html.escape(wmeta["w3c_url"]),
                html.escape(wmeta["criterion"]),
                _format_inline_tokens(cat["desc"]),
                html.escape(wmeta["user_impact"]),
                html.escape(cat["test_case"]),
                _format_inline_tokens(cat["sr_current"]),
                _format_inline_tokens(cat["sr_expected"]),
                _format_inline_tokens(cat["rec"]),
                rem_html,
                chips,
            )
        )
    exec_html = "\n".join(exec_cards) or '<div class="rule-card info">Sin hallazgos registrados en esta corrida.</div>'

    # Construir sección opcional de regresión contra bugs Jira (cuando jira_bugs está configurado)
    jira_section_html = ""
    n_jira_active = 0
    n_jira_applicable = 0
    cur_scope = (resolved_view.get("scope_tag") or "").lower()
    if jira_bugs:
        jira_rows = []
        for jb in jira_bugs:
            jkey = jb["key"]
            jb_views = jb.get("views", "n/d")
            is_applicable = not cur_scope or (cur_scope in jb_views.lower())
            if is_applicable:
                n_jira_applicable += 1
            rids = [r.strip() for r in (jb.get("rule_id") or "").split("/") if r.strip()]
            mpat = jb.get("match_pattern") or ""
            matched_steps = []
            for s in steps:
                if s.get("is_duplicate") or s.get("in_overlay"):
                    continue
                u_low = ((s.get("utterance") or "") + " " + (s.get("label") or "")).lower()
                if mpat == "__focus_return__":
                    if any("Focus Return" in x for x in (s.get("seq_issues") or [])):
                        matched_steps.append(s["i"])
                elif mpat == "__skeleton_or_empty_status__":
                    if s.get("is_skeleton") or (s.get("utterance") or "").strip().lower() in ("status", "estado"):
                        matched_steps.append(s["i"])
                elif mpat:
                    if re.search(mpat, u_low, re.I):
                        matched_steps.append(s["i"])
                elif any(
                    cat_v["rule_id"] in rids
                    and any(i_num == s["i"] for i_num, _ in by_rule.get(cat_k, []))
                    for cat_k, cat_v in WCAG_CATALOG.items()
                ):
                    matched_steps.append(s["i"])
            if matched_steps:
                n_jira_active += 1
                st_html = '<span class="state-pill warn">Reproducido (%d paso%s)</span>' % (
                    len(matched_steps),
                    "s" if len(matched_steps) != 1 else "",
                )
                step_chips = " ".join(
                    '<a class="step-chip" href="#step-%d">Paso %d</a>' % (n, n) for n in matched_steps[:8]
                )
                if len(matched_steps) > 8:
                    step_chips += ' <span class="muted">(+%d más)</span>' % (len(matched_steps) - 8)
            elif is_applicable:
                st_html = '<span class="state-pill ok">No reproducido en esta corrida</span>'
                step_chips = '<span class="muted">Aplica a: %s (requiere interacción modal/transición si es dinámico)</span>' % html.escape(jb_views)
            else:
                st_html = '<span class="state-pill muted">Otra vista (%s)</span>' % html.escape(jb_views)
                step_chips = '<span class="muted">Alcance del ticket: %s</span>' % html.escape(jb_views)
            jira_rows.append(
                "<tr>"
                "<td><a class='jira-chip' href='%s/browse/%s' target='_blank' rel='noopener'>%s</a>"
                " <span class='muted'>(%s)</span><br><b>%s</b></td>"
                "<td class='td-role'><span class='rolebadge' style='margin:0'>%s</span><br><span class='muted'>%s</span></td>"
                "<td class='td-state'>%s</td>"
                "<td>%s</td>"
                "</tr>"
                % (
                    html.escape(jira_base),
                    html.escape(jkey),
                    html.escape(jkey),
                    html.escape(jb.get("epic", "")),
                    html.escape(jb.get("summary", "")),
                    html.escape(jb.get("fix_type", "")),
                    html.escape(jb.get("rule_id", "")),
                    st_html,
                    step_chips,
                )
            )
        jira_section_html = (
            '<h2 id="sec-jira"><span>2. Estado de Regresión - Bugs Jira configurados</span>'
            "<span>%d reproducidos en esta vista (de %d aplicables / %d totales)</span></h2>"
            '<div class="table-wrap"><table>'
            '<colgroup><col class="c-lbl"><col class="c-role"><col class="c-state"><col class="c-find"></colgroup>'
            "<thead><tr><th>Ticket Jira / Épica</th><th>Origen del Fix / Regla</th><th>Estado en esta corrida</th><th>Pasos / Evidencia</th></tr></thead>"
            "<tbody>%s</tbody></table></div>"
            % (n_jira_active, n_jira_applicable or len(jira_bugs), len(jira_bugs), "\n".join(jira_rows))
        )

    # Construir sección de Auditoría estática de Diccionario i18n (IndexedDB)
    po_section_html = ""
    po_data = (dom_snapshot or {}).get("poeditor") if isinstance(dom_snapshot, dict) else None
    if po_data:
        db_name_lbl = str(po_data.get("dbName") or "i18n")
        po_rows = []
        for item in po_data.get("englishKeys", []):
            po_rows.append((
                item["key"],
                "En inglés (es-AR)",
                "warn",
                item["value"],
                item["note"],
            ))
        for item in po_data.get("uninterpolatedKeys", []):
            po_rows.append((
                item["key"],
                "Placeholder sin interpolar",
                "warn",
                item["value"],
                item["note"],
            ))
        for item in po_data.get("emptyKeys", []):
            po_rows.append((
                item["key"],
                "Key vacía",
                "muted",
                "(vacío)",
                item["note"],
            ))
        for item in po_data.get("styleOrTypoKeys", []):
            po_rows.append((
                item["key"],
                "Tilde / Voseo / Duplicada",
                "warn",
                item["value"],
                item["note"],
            ))
        po_tr = "\n".join(
            "<tr><td><code>%s</code></td>"
            "<td class='td-state'><span class='state-pill %s'>%s</span></td>"
            "<td>%s</td><td>%s</td></tr>"
            % (
                html.escape(k),
                cls,
                html.escape(kind),
                html.escape(val),
                html.escape(note),
            )
            for k, kind, cls, val, note in po_rows
        ) or "<tr><td colspan='4' class='muted'>Sin observaciones en IndexedDB.</td></tr>"
        po_section_html = (
            '<h2 id="sec-poeditor"><span>3. Auditoría de Diccionario i18n en Memoria (IndexedDB %s v%s · %s · %d keys)</span>'
            "<span>%d keys con observación</span></h2>"
            '<div class="table-wrap"><table>'
            '<colgroup><col class="c-lbl"><col class="c-state"><col class="c-find"><col class="c-role"></colgroup>'
            "<thead><tr><th>Key i18n (%s)</th><th>Diagnóstico</th><th>Valor actual en IndexedDB</th><th>Impacto / Detalle</th></tr></thead>"
            "<tbody>%s</tbody></table></div>"
            % (
                html.escape(db_name_lbl),
                html.escape(str(po_data.get("version", "?"))),
                html.escape(str(po_data.get("language", "?"))),
                int(po_data.get("totalKeys", 0)),
                len(po_rows),
                html.escape(db_name_lbl),
                po_tr,
            )
        )

    # Construir Mapa de Jerarquía de Encabezados (Outline H1-H6) y tabla de Elementos Omitidos (TB-UNREACH-001)
    headings_section_html = ""
    if headings_outline:
        h_rows = []
        for h in headings_outline:
            indent_px = (h["level"] - 1) * 18
            sr_badge = ' <span class="pill modal">SR-only</span>' if h.get("is_sr_only") else ""
            step_link = (
                '<a class="step-chip" href="#step-%d">Paso %d</a>' % (h["step"], h["step"])
                if h.get("step")
                else '<span class="state-pill warn">No alcanzado</span>'
            )
            h_warn = (
                "".join('<div class="flag">%s</div>' % html.escape(w) for w in h.get("issues", []))
                if h.get("issues")
                else '<span class="state-pill ok">Orden OK</span>'
            )
            h_rows.append(
                "<tr>"
                "<td style='padding-left:%dpx'><span class='tax-lvl'>%s</span>%s <b>%s</b></td>"
                "<td><code class='inl-code'>%s</code></td>"
                "<td class='td-state'>%s</td>"
                "<td>%s</td>"
                "</tr>"
                % (
                    12 + indent_px,
                    html.escape(h["tag"]),
                    sr_badge,
                    html.escape(h["label"][:130]),
                    html.escape(h["selector"]),
                    step_link,
                    h_warn,
                )
            )
        headings_section_html = (
            '<h2 id="sec-headings"><span>Mapa de Jerarquía de Encabezados (Outline H1-H6)</span>'
            "<span>%d encabezado(s) detectados</span></h2>"
            '<div class="table-wrap"><table>'
            '<colgroup><col class="c-lbl"><col class="c-role"><col class="c-state"><col class="c-find"></colgroup>'
            "<thead><tr><th>Nivel y Texto del Encabezado</th><th>Selector DOM</th><th>Paso TalkBack</th><th>Validación Jerárquica</th></tr></thead>"
            "<tbody>%s</tbody></table></div>"
            % (len(headings_outline), "\n".join(h_rows))
        )

    unreach_section_html = ""
    if unreachable_els:
        u_rows = []
        for u in unreachable_els:
            st_chip = (
                '<a class="step-chip" href="#step-%d">Paso %d</a>' % (u["step"], u["step"])
                if u.get("step")
                else '<span class="state-pill warn">Omitido en barrido</span>'
            )
            u_rows.append(
                "<tr>"
                "<td><b>%s</b></td>"
                "<td><code class='inl-code'>%s</code></td>"
                "<td class='td-state'>%s</td>"
                "<td>%s</td>"
                "</tr>"
                % (
                    html.escape(u["label"]),
                    html.escape(u["selector"]),
                    st_chip,
                    html.escape(u["reason"]),
                )
            )
        unreach_section_html = (
            '<h2 id="sec-unreach"><span>Contenido / Controles del DOM Omitidos por TalkBack (TB-UNREACH-001)</span>'
            "<span>%d elemento(s) con observación</span></h2>"
            '<div class="table-wrap"><table>'
            '<colgroup><col class="c-lbl"><col class="c-role"><col class="c-state"><col class="c-find"></colgroup>'
            "<thead><tr><th>Etiqueta / Contenido en DOM</th><th>Selector DOM</th><th>Estado</th><th>Diagnóstico</th></tr></thead>"
            "<tbody>%s</tbody></table></div>"
            % (len(unreachable_els), "\n".join(u_rows))
        )

    tree_rows = []
    for n in tree_nodes:
        if not is_a11y_relevant(n):
            continue
        label = (n.get("desc") or n.get("text") or "").strip() or "(control sin etiqueta)"
        reached = node_key(n) in visited
        its = node_issues(n)
        if reached:
            st_cls, st_txt = "ok", "visitado"
        elif n.get("focusable") or n.get("clickable"):
            st_cls, st_txt = "warn", "no alcanzado"
        else:
            st_cls, st_txt = "muted", "solo gesto TalkBack"
        findings_cell = (
            "".join('<div class="flag">%s</div>' % html.escape(t) for t in its)
            if its
            else '<span class="muted">-</span>'
        )
        tree_rows.append(
            "<tr><td>%s</td>"
            "<td class='td-role'><span class='rolebadge' style='margin:0'>%s</span></td>"
            "<td class='td-state'><span class='state-pill %s'>%s</span></td>"
            "<td>%s</td></tr>"
            % (
                html.escape(label[:140]),
                html.escape(role_of(n.get("cls", ""))),
                st_cls,
                st_txt,
                findings_cell,
            )
        )
    if not tree_rows:
        tree_rows.append(
            "<tr><td colspan='4' class='muted'>Sin nodos nativos individuales expuestos (vista renderizada dentro de contenedor WebView).</td></tr>"
        )

    meta_chips = "".join(
        '<span class="meta-chip">%s</span>' % html.escape(part.strip())
        for part in meta.split("·")
        if part.strip()
    )
    n_noise = sum(1 for s in steps if s.get("in_overlay"))
    n_dups = sum(1 for s in steps if s.get("is_duplicate"))
    n_unique = len(steps) - n_dups - n_noise
    n_screens = 1 + sum(1 for s in steps if s.get("screen_change"))
    n_crit = sum(
        len(by_rule.get(rk, []))
        for rk in WCAG_ORDER
        if WCAG_CATALOG[rk]["sev"][0] == "crit"
    )
    v_title = resolved_view.get("title", "Vista Android")
    v_short = resolved_view.get("short_title", v_title)
    v_route = resolved_view.get("route_hash", "")
    v_h1 = resolved_view.get("h1", "")
    route_chip = ('<code>%s</code>' % html.escape(v_route)) if v_route else ""
    h1_chip = ('<span>Encabezado H1: <b>«%s»</b></span>' % html.escape(v_h1)) if v_h1 else ""
    view_banner_html = (
        '<div class="view-banner">'
        '<span>Vista auditada: <b>%s</b></span>%s%s'
        "</div>"
        % (html.escape(v_title), route_chip, h1_chip)
    )
    stat6_html = (
        '<div class="stat"><b>%d <span class="stat-sep">/</span> %d</b><span class="stat-lbl">bugs Jira reproducidos (vista)</span></div>'
        % (n_jira_active, n_jira_applicable or len(jira_bugs))
        if jira_bugs
        else '<div class="stat"><b>%d <span class="stat-sep">/</span> %d</b><span class="stat-lbl">repetidos / overlay</span></div>'
        % (n_dups, n_noise)
    )
    doc = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(tab_title)s - TalkBack Audit v%(ver)s</title><style>%(css)s</style></head><body id="top">
<header>
  <div class="hdr-inner">
    <div class="hdr-top">
      <h1>Auditoría TalkBack - %(view_title)s <span class="verbadge">v%(ver)s</span></h1>
      <div class="hdr-actions">
        <a class="navlink" href="#sec-resumen">Resumen WCAG</a>
        <a class="navlink" href="#sec-headings">Encabezados</a>
        <a class="navlink" href="#sec-jira">Bugs Jira</a>
        <a class="navlink" href="#sec-poeditor">Diccionario i18n</a>
        <a class="navlink" href="#sec-flujo">Mapa de secuencia</a>
        <a class="navlink" href="#sec-pasos">Pasos</a>
        <button class="btn-print" onclick="window.print()">Imprimir / PDF</button>
      </div>
    </div>
    %(view_banner_html)s
    <div class="meta-bar">%(meta_chips)s</div>
    <div class="stats">
      <div class="stat"><b>%(n_steps)d</b><span class="stat-lbl">pasos capturados</span></div>
      <div class="stat"><b>%(n_unique)d</b><span class="stat-lbl">pasos únicos efectivos</span></div>
      <div class="stat"><b>%(n_screens)d</b><span class="stat-lbl">pantallas detectadas</span></div>
      <div class="stat crit"><b>%(n_crit)d</b><span class="stat-lbl">hallazgos severidad alta</span></div>
      <div class="stat warn"><b>%(n_issues)d</b><span class="stat-lbl">hallazgos totales</span></div>
      %(stat6_html)s
    </div>
  </div>
</header>
<main>
<h2 id="sec-resumen"><span>1. Resumen ejecutivo por criterio WCAG (con opciones de remediación)</span><span>%(n_rules)d criterios afectados</span></h2>
<div class="exec-grid">%(exec_html)s</div>

%(jira_section_html)s

%(headings_section_html)s

%(unreach_section_html)s

%(po_section_html)s

<h2 id="sec-flujo"><span>Mapa de secuencia lineal (pasos únicos)</span><span>clic para saltar al paso</span></h2>
<div class="filmstrip">%(film)s</div>

<h2 id="sec-pasos"><span>Evidencia paso a paso (foco, DOM, key i18n y anuncio real de TalkBack)</span></h2>
<div class="toolbar">
  <div class="flt-group">
    <button class="flt active" data-mode="all">Todos (%(n_steps)d)</button>
    <button class="flt" data-mode="clean">Sin repetidos ni ruido (%(n_unique)d)</button>
    <button class="flt" data-mode="issues">Solo con hallazgos</button>
    <button class="flt" data-mode="skel">Solo skeletons / carga</button>
    <button class="flt" data-mode="modal">Solo modales / tooltips</button>
  </div>
  <input id="qbox" class="searchbox" type="search" placeholder="Filtrar por anuncio, etiqueta o regla WCAG...">
</div>
%(cards)s

<h2 id="sec-arbol"><span>Árbol accesible de la pantalla inicial (orden de lectura TalkBack)</span></h2>
<div class="table-wrap"><table>
<colgroup><col class="c-lbl"><col class="c-role"><col class="c-state"><col class="c-find"></colgroup>
<thead><tr><th>Etiqueta</th><th>Rol</th><th>Estado</th><th>Hallazgos</th></tr></thead>
<tbody>%(tree_rows)s</tbody>
</table></div>
</main>
<footer>
  <span>TalkBack Audit v%(ver)s - Auditoría lineal asistida sobre emulador Android</span>
  <span>%(meta)s</span>
</footer>
<button id="btn-top" type="button" aria-label="Volver al inicio del reporte" onclick="window.scrollTo({top:0,behavior:'smooth'})">Arriba</button>
<div id="lb"><img id="lbimg"><div id="lbcap"></div></div>
<script>
function copyDomCode(btn){
 var box=btn.closest('.dombox');
 var pre=box?box.querySelector('.dom-pre'):null;
 var txt=pre?(pre.getAttribute('data-raw')||pre.textContent):'';
 if(navigator.clipboard&&txt){
  navigator.clipboard.writeText(txt);
  var orig=btn.textContent;
  btn.textContent='Copiado';
  setTimeout(function(){btn.textContent=orig;},1400);
 }
}
var btop=document.getElementById('btn-top');
window.addEventListener('scroll',function(){
 if(window.scrollY>260)btop.classList.add('vis');
 else btop.classList.remove('vis');
},{passive:true});
var lb=document.getElementById('lb'),li=document.getElementById('lbimg'),lc=document.getElementById('lbcap');
var shots=Array.from(document.querySelectorAll('img.shot')),curIdx=-1;
function openLb(idx){
 if(idx<0||idx>=shots.length)return;
 curIdx=idx;
 li.src=shots[idx].dataset.full;
 lc.textContent=(shots[idx].dataset.cap||'')+' (usa flechas ←/→ para navegar, Esc para salir)';
 lb.style.display='flex';
}
shots.forEach(function(im,idx){im.onclick=function(){openLb(idx);};});
lb.onclick=function(){lb.style.display='none';};
document.addEventListener('keydown',function(e){
 if(lb.style.display!=='flex')return;
 if(e.key==='Escape')lb.style.display='none';
 else if(e.key==='ArrowRight')openLb((curIdx+1)%%shots.length);
 else if(e.key==='ArrowLeft')openLb((curIdx-1+shots.length)%%shots.length);
});
var curMode='all',qInput=document.getElementById('qbox');
function applyFilter(){
 var q=(qInput.value||'').toLowerCase().trim();
 document.querySelectorAll('.step').forEach(function(st){
  var show=true;
  if(curMode==='clean') show=(st.dataset.dup==='0' && st.dataset.noise==='0');
  else if(curMode==='issues') show=(st.dataset.issues==='1' && st.dataset.dup==='0');
  else if(curMode==='skel') show=(st.dataset.skel==='1');
  else if(curMode==='modal') show=(st.dataset.modal==='1');
  if(show && q) show=(st.dataset.search||'').indexOf(q)!==-1;
  st.style.display=show?'flex':'none';
 });
}
document.querySelectorAll('.flt').forEach(function(btn){
 btn.onclick=function(){
  document.querySelectorAll('.flt').forEach(function(b){b.classList.remove('active');});
  btn.classList.add('active');
  curMode=btn.dataset.mode;
  applyFilter();
 };
});
qInput.addEventListener('input',applyFilter);
</script>
</body></html>""" % {
        "ver": VERSION,
        "tab_title": html.escape(v_short),
        "view_title": html.escape(v_title),
        "view_banner_html": view_banner_html,
        "stat6_html": stat6_html,
        "css": CSS,
        "meta": html.escape(meta),
        "meta_chips": meta_chips,
        "n_steps": len(steps),
        "n_unique": max(0, n_unique),
        "n_screens": n_screens,
        "n_crit": n_crit,
        "n_issues": len(all_issues),
        "n_rules": len(by_rule),
        "n_dups": n_dups,
        "n_noise": n_noise,
        "n_jira_active": n_jira_active,
        "exec_html": exec_html,
        "jira_section_html": jira_section_html,
        "headings_section_html": headings_section_html,
        "unreach_section_html": unreach_section_html,
        "po_section_html": po_section_html,
        "film": "\n".join(film_nodes),
        "cards": "\n".join(cards),
        "tree_rows": "\n".join(tree_rows),
    }
    path = os.path.join(out_dir, "report.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
    return path


def rebuild_report(ocr_bin, out_dir, view_info=None, cfg=None):
    """Regenera report.html de una corrida previa: usa steps.json si existe y re-ejecuta OCR + heurísticas."""
    json_path = os.path.join(out_dir, "steps.json")
    saved_by_i = {}
    tree_nodes, visited, orig_meta, dom_snapshot, saved_view_info = [], set(), "", None, None
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            orig_meta = saved.get("meta", "")
            saved_view_info = saved.get("view_info")
            dom_snapshot = saved.get("dom_snapshot")
            tree_nodes = saved.get("tree_nodes", [])
            visited = {
                (k[0], k[1], k[2], tuple(k[3]) if k[3] else None)
                for k in saved.get("visited", [])
            }
            for s in saved.get("steps", []):
                saved_by_i[s["i"]] = s
        except Exception:
            pass
    if not view_info:
        view_info = saved_view_info
        if not view_info:
            cfg = cfg or load_config()
            for vspec in (cfg.get("views") or {}).values():
                if vspec.get("out") and os.path.abspath(vspec["out"]) == os.path.abspath(out_dir):
                    view_info = {
                        "title": vspec.get("title"),
                        "short_title": vspec.get("short_title"),
                        "scope_tag": vspec.get("scope_tag"),
                    }
                    break
    imgs = sorted(glob.glob(os.path.join(out_dir, "img", "step_*.png")))
    steps = []
    for i, p in enumerate(imgs, 1):
        prev = saved_by_i.get(i, {})
        info = (
            ocr_step_info(ocr_bin, p, None)
            if ocr_bin
            else {
                "utterance": prev.get("utterance", ""),
                "raw_caption": prev.get("raw_caption", ""),
                "page_title": prev.get("page_title", ""),
                "is_skeleton": bool(prev.get("is_skeleton", False)),
            }
        )
        utt = info["utterance"]
        box = prev.get("box")
        node = match_node(box, tree_nodes, utterance=utt) if tree_nodes else prev.get("node")
        if node:
            visited.add(node_key(node))
        lbl = effective_label(node, tree_nodes) if node else ""
        steps.append({
            "i": i,
            "png": p,
            "node": node,
            "dom": match_dom_element(utt, lbl, dom_snapshot) if dom_snapshot else prev.get("dom"),
            "utterance": utt,
            "raw_caption": info["raw_caption"],
            "page_title": info["page_title"],
            "is_skeleton": info["is_skeleton"],
            "box": box,
            "in_overlay": bool(prev.get("in_overlay", False)),
            "label": lbl,
            "screen_change": bool(prev.get("screen_change", False)),
        })
        tag = " [SKELETON: %s]" % info["page_title"] if info["is_skeleton"] else ""
        print("      %3d. %s%s" % (i, (utt or info["raw_caption"] or "")[:55], tag))
    meta = orig_meta or (
        "rebuild · dispositivo=n/d · pasos=%d · %s"
        % (len(steps), datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
    )
    return build_report(
        steps, tree_nodes, visited, out_dir, meta, dom_snapshot=dom_snapshot, view_info=view_info, cfg=cfg
    )


def build_suite_index(out_dirs, suite_dir=None, zip_path=None, suite_title=None):
    """Genera una portada maestra index.html enlazando múltiples reportes de una suite
    y opcionalmente empaqueta un archivo .zip autocontenido."""
    valid_dirs = [d for d in out_dirs if d and os.path.exists(os.path.join(d, "report.html"))]
    if not valid_dirs:
        return None, None
    if not suite_dir:
        suite_dir = os.path.commonpath([os.path.abspath(d) for d in valid_dirs])
        if os.path.isfile(suite_dir) or any(
            os.path.abspath(d) == suite_dir for d in valid_dirs
        ):
            suite_dir = os.path.dirname(suite_dir)
    os.makedirs(suite_dir, exist_ok=True)

    cards_html = []
    meta_summary = ""
    for idx, d in enumerate(valid_dirs, 1):
        sjson = os.path.join(d, "steps.json")
        vtitle = os.path.basename(os.path.abspath(d))
        vroute = ""
        n_steps = 0
        b_ver = ""
        po_ver = ""
        if os.path.exists(sjson):
            try:
                data = json.load(open(sjson, encoding="utf-8"))
                vi = data.get("view_info") or {}
                vtitle = vi.get("title") or vtitle
                vroute = vi.get("route_hash") or ""
                n_steps = len(data.get("steps") or [])
                ds = data.get("dom_snapshot") or {}
                b_ver = ds.get("bundleVersion") or ""
                po = ds.get("poeditor") or {}
                if po.get("version"):
                    po_ver = "%s v%s (%s, %d keys)" % (
                        po.get("dbName") or "i18n",
                        po["version"],
                        po.get("language", ""),
                        po.get("totalKeys", 0),
                    )
                if not meta_summary and data.get("meta"):
                    meta_summary = data["meta"]
            except Exception:
                pass
        rel_rep = os.path.relpath(os.path.join(d, "report.html"), suite_dir)
        route_line = ("<code>%s</code> · " % html.escape(vroute)) if vroute else ""
        ver_line = ("Bundle v%s" % html.escape(b_ver)) if b_ver else ""
        if po_ver:
            ver_line = (ver_line + " · " + html.escape(po_ver)).strip(" ·")
        cards_html.append(
            '<div class="card">'
            "<div>"
            "<h2>%d. %s</h2>"
            "<p>%s<b>%d pasos capturados</b>%s</p>"
            "</div>"
            '<a class="btn" href="%s">Abrir Reporte</a>'
            "</div>"
            % (
                idx,
                html.escape(vtitle),
                route_line,
                n_steps,
                (" · " + ver_line) if ver_line else "",
                html.escape(rel_rep),
            )
        )

    title_hdr = suite_title or ("Suite de Auditoría TalkBack v%s (%d vistas)" % (VERSION, len(valid_dirs)))
    idx_doc = """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>%(title)s</title>
  <style>
    * { box-sizing: border-box; }
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 0; background: #f2f4f7; color: #1d2433; line-height: 1.5; }
    header { background: #0f172a; color: #fff; padding: 24px; border-bottom: 3px solid #0284c7; }
    .inner { max-width: 1020px; margin: 0 auto; }
    h1 { margin: 0 0 6px; font-size: 21px; }
    .sub { color: #cbd5e1; font-size: 12.5px; margin: 0; }
    main { max-width: 1020px; margin: 0 auto; padding: 24px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(290px, 1fr)); gap: 16px; margin-bottom: 24px; }
    .card { background: #fff; border: 1px solid #e2e8f0; border-top: 4px solid #0284c7; border-radius: 10px; padding: 18px 20px; box-shadow: 0 1px 3px rgba(15,23,42,.06); display: flex; flex-direction: column; justify-content: space-between; gap: 12px; }
    .card h2 { margin: 0; font-size: 15.5px; color: #0f172a; }
    .card p { margin: 6px 0 0; font-size: 12.5px; color: #475569; overflow-wrap: anywhere; }
    .card code { background: #f1f5f9; padding: 1px 5px; border-radius: 4px; font-size: 11px; color: #0f172a; }
    .btn { display: inline-block; background: #0f172a; color: #fff; text-decoration: none; font-size: 12.5px; font-weight: 600; padding: 8px 14px; border-radius: 6px; text-align: center; }
    .btn:hover { background: #0284c7; }
  </style>
</head>
<body>
  <header>
    <div class="inner">
      <h1>%(title)s</h1>
      <p class="sub">%(meta)s</p>
    </div>
  </header>
  <main>
    <div class="grid">
      %(cards)s
    </div>
  </main>
</body>
</html>
""" % {
        "title": html.escape(title_hdr),
        "meta": html.escape(meta_summary or ("Generado con TalkBack Audit v%s" % VERSION)),
        "cards": "\n      ".join(cards_html),
    }

    index_path = os.path.join(suite_dir, "index.html")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(idx_doc)

    built_zip = None
    if zip_path:
        built_zip = os.path.abspath(zip_path)
        stage_root = os.path.join(suite_dir, "_stage_pack_tmp")
        if os.path.exists(stage_root):
            shutil.rmtree(stage_root)
        os.makedirs(stage_root, exist_ok=True)
        try:
            stage_cards = []
            for idx, d in enumerate(valid_dirs, 1):
                sub_name = "%02d_%s" % (idx, os.path.basename(os.path.abspath(d)))
                dst_d = os.path.join(stage_root, sub_name)
                os.makedirs(os.path.join(dst_d, "img"), exist_ok=True)
                shutil.copy2(os.path.join(d, "report.html"), os.path.join(dst_d, "report.html"))
                if os.path.exists(os.path.join(d, "steps.json")):
                    shutil.copy2(os.path.join(d, "steps.json"), os.path.join(dst_d, "steps.json"))
                img_src = os.path.join(d, "img")
                if os.path.isdir(img_src):
                    for fn in sorted(os.listdir(img_src)):
                        if fn.startswith("step_") and fn.endswith(".png"):
                            shutil.copy2(os.path.join(img_src, fn), os.path.join(dst_d, "img", fn))
                old_rel = os.path.relpath(os.path.join(d, "report.html"), suite_dir)
                new_rel = "%s/report.html" % sub_name
                idx_doc = idx_doc.replace('href="%s"' % html.escape(old_rel), 'href="%s"' % html.escape(new_rel))
            with open(os.path.join(stage_root, "index.html"), "w", encoding="utf-8") as f:
                f.write(idx_doc)
            if os.path.exists(built_zip):
                os.remove(built_zip)
            arc_prefix = os.path.splitext(os.path.basename(built_zip))[0]
            with zipfile.ZipFile(built_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, _, files in os.walk(stage_root):
                    for fn in sorted(files):
                        full = os.path.join(root, fn)
                        rel = os.path.join(arc_prefix, os.path.relpath(full, stage_root))
                        zf.write(full, rel)
        finally:
            shutil.rmtree(stage_root, ignore_errors=True)

    return index_path, built_zip
