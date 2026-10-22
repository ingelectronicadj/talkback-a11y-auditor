#!/usr/bin/env python3
"""
talkback_audit.py - CLI principal de auditoría lineal de accesibilidad con TalkBack.

Arquitectura modular en `tb_audit/`:
  - `tb_audit.config`       : configuración centralizada (env vars / JSON opcional)
  - `tb_audit.adb_client`   : cliente ADB con timeouts, preflight de emulador y control TalkBack
  - `tb_audit.sso`          : autenticación SSO opcional y keep-alive en segundo plano
  - `tb_audit.vision`       : análisis de framebuffer RGBA y OCR Vision (`tb_ocr.swift`)
  - `tb_audit.wcag_catalog` : taxonomía oficial WCAG 2.2 (86 criterios) y catálogo `TB-*`
  - `tb_audit.rules`        : motor de heurísticas sobre nodos, textos, skeletons y secuencia
  - `tb_audit.report`       : persistencia `steps.json` y generador de `report.html`
"""

import argparse
import datetime
import os
import re
import select
import sys
import tempfile
import time

from tb_audit import VERSION
from tb_audit.adb_client import AdbClient
from tb_audit.cdp import capture_webview_dom, match_dom_element, run_cdp_steps
from tb_audit.config import LOCAL_CONFIG_PATH, load_config
from tb_audit.report import build_report, build_suite_index, rebuild_report
from tb_audit.rules import (
    analyze_sequence_issues,
    is_a11y_relevant,
    node_issues,
    node_key,
    text_a11y_issues,
)
from tb_audit.sso import login_flow, refresh_session as _refresh_session, start_keep_alive
from tb_audit.vision import (
    effective_label,
    ensure_ocr_binary,
    find_caption_bar,
    find_focus_box,
    match_node,
    ocr_step_info,
    screen_sig,
    sig_diff,
)
from tb_audit.wcag_catalog import WCAG_CATALOG, WCAG_CRITERIA, WCAG_ORDER, resolve_wcag_meta


def refresh_session(cfg=None, quiet=False, user_id=None, core_user_id=None):
    """Compatibilidad directa para invocaciones rápidas por CLI (`import talkback_audit as t; t.refresh_session()`)."""
    return _refresh_session(
        cfg or load_config(user_id=user_id, core_user_id=core_user_id),
        quiet=quiet,
    )


def _handle_terminal_key(adb_client, cmd):
    """Permite enviar atajos de teclado directos por adb desde la consola en modo --manual
    (evita que la ventana Qt del emulador en macOS intercepte Shift+Tab o Alt)."""
    c = cmd.strip()
    if not c:
        return False
    if c in ("q", "quit", "exit"):
        return True
    if c == "t":
        adb_client.nav("tab", backward=False)
    elif c in ("T", "st", "shift+tab"):
        adb_client.nav("tab", backward=True)
    elif c == "n":
        adb_client.nav("swipe", backward=False)
    elif c == "p":
        adb_client.nav("swipe", backward=True)
    elif c == "d":
        adb_client.nav("dpad", backward=False)
    elif c == "u":
        adb_client.nav("dpad", backward=True)
    elif c == "e":
        adb_client.emu_double_tap()
    elif c == "b":
        adb_client.run(["shell", "input", "keyevent", "4"], check=False)
    return False


def run_manual(adb_client, ocr_bin, out_dir, args):
    """Modo manual: el evaluador navega con gestos reales de TalkBack o comandos
    de consola; el script captura cada cambio de caption/foco."""
    print("      Navega en el emulador o escribe comando + Enter aquí:")
    print("        n=siguiente (Alt+→) | p=anterior (Alt+←) | t=Tab | T=Shift+Tab | d=↓ | u=↑ | e=Activar | q=Fin")
    print("      Capturo cada anuncio; paro tras %ds sin cambios o Ctrl+C." % args.idle)
    last_nodes = adb_client.dump_nodes()
    steps, last_sig, quiet, i, visited = [], None, 0, 0, set()
    prev_screen = None
    try:
        while True:
            if sys.platform != "win32":
                rlist, _, _ = select.select([sys.stdin], [], [], 0.0)
                if rlist:
                    line = sys.stdin.readline()
                    if _handle_terminal_key(adb_client, line):
                        print("      finalizado por comando 'q'")
                        break
                    time.sleep(0.6)
            try:
                w, h, px = adb_client.screencap_raw()
            except Exception:
                time.sleep(0.5)
                continue
            box = find_focus_box(w, h, px)
            bar_y = find_caption_bar(w, h, px)
            tmp = os.path.join(out_dir, "img", "_poll.png")
            adb_client.screencap_png(tmp)
            info = (
                ocr_step_info(ocr_bin, tmp, bar_y)
                if ocr_bin
                else {"utterance": "", "raw_caption": "", "page_title": "", "is_skeleton": False}
            )
            utt = info["utterance"]
            sig = (box, utt, info["is_skeleton"], info["page_title"])
            if sig == last_sig:
                quiet += 1
            else:
                quiet = 0
                i += 1
                png = os.path.join(out_dir, "img", "step_%03d.png" % i)
                os.replace(tmp, png)
                node = match_node(box, last_nodes)
                lbl = effective_label(node, last_nodes) if node else ""
                in_overlay = bool(box and bar_y and (box[1] + box[3]) / 2 / h > bar_y[0])
                cur_screen = screen_sig(w, h, px)
                change = bool(prev_screen and sig_diff(prev_screen, cur_screen) > 35)
                prev_screen = cur_screen
                steps.append({
                    "i": i,
                    "png": png,
                    "node": node,
                    "utterance": utt,
                    "raw_caption": info["raw_caption"],
                    "page_title": info["page_title"],
                    "is_skeleton": info["is_skeleton"],
                    "box": box,
                    "in_overlay": in_overlay,
                    "label": lbl,
                    "screen_change": change,
                })
                if node:
                    visited.add(node_key(node))
                print("      %3d. %-52s | dice: %s" % (i, lbl[:50] or "?", (utt or "")[:60]))
            last_sig = sig
            if quiet >= max(1, int(args.idle / args.delay)):
                print("      sin cambios; fin")
                break
            time.sleep(args.delay)
    except KeyboardInterrupt:
        print("      interrumpido por el usuario")
    return steps, last_nodes, visited


def _is_chart_point_utt(utt):
    return bool(re.search(r"(fecha:.*valor|date:.*value)", (utt or "").lower()))


def run_automated(adb_client, ocr_bin, out_dir, nodes0, args, dom_snapshot=None):
    """Modo automático lineal (swipe = gesto nativo TalkBack vía QEMU event mouse, alt, tab, dpad)."""
    print("      navegando en modo '%s' (máx. %d pasos)..." % (args.mode, args.steps))
    if args.mode == "swipe" and not args.backward:
        # Inicializar foco determinista tocando el título estático central (672, 225)
        # (nunca el botón Atrás para no activarlo si ya tenía el foco) y retrocediendo 1 swipe a Atrás.
        adb_client.emu_explore_touch(672, 225)
        time.sleep(0.9)
        adb_client.emu_swipe(backward=True)
        time.sleep(0.7)
    steps, prev_sig, repeats, visited, seen_utts = [], None, 0, set(), set()
    prev_screen = None
    chart_streak = 0
    tested_modals = set()
    step_num = 0
    for _ in range(1, args.steps + 1):
        step_num += 1
        i = step_num
        adb_client.nav(args.mode, args.backward)
        time.sleep(args.delay)
        adb_client.close_keyboard()
        png = os.path.join(out_dir, "img", "step_%03d.png" % i)
        try:
            w, h, px = adb_client.screencap_raw()
        except Exception:
            time.sleep(0.5)
            try:
                w, h, px = adb_client.screencap_raw()
            except Exception:
                w = h = 0
                px = b""
        adb_client.screencap_png(png)
        box = find_focus_box(w, h, px) if px else None
        bar_y = find_caption_bar(w, h, px) if px else None
        in_overlay = bool(box and bar_y and (box[1] + box[3]) / 2 / h > bar_y[0])
        info = (
            ocr_step_info(ocr_bin, png, bar_y)
            if ocr_bin
            else {"utterance": "", "raw_caption": "", "page_title": "", "is_skeleton": False}
        )
        utt = info["utterance"]
        # Si TalkBack quedó leyendo el hint secundario "Tocar dos veces para activar" o "Mostrando Teclado",
        # enviamos un pulso adicional para desatascar el foco de campos <input>.
        if re.search(
            r"^(tocar dos veces para activar|toc[aá] dos veces para activar|mostrando teclado|teclado .* oculto|press action \+ space)",
            (utt or "").strip().lower(),
        ):
            adb_client.nav(args.mode, args.backward)
            time.sleep(0.65)
            adb_client.close_keyboard()
            adb_client.screencap_png(png)
            info = ocr_step_info(ocr_bin, png, bar_y) if ocr_bin else info
            utt = info["utterance"]
        if i > 5 and re.search(
            r"no next focusable item|no hay m[aá]s elemento enfocable|no hay ning[uú]n elemento siguiente|no hay elementos siguientes",
            (utt or "").lower(),
        ):
            try:
                os.remove(png)
            except OSError:
                pass
            print("      fin de la vista alcanzado (%r) en paso %d" % (utt, i - 1))
            break
        node = match_node(box, nodes0, utterance=utt)
        if node:
            visited.add(node_key(node))
        dom_el = match_dom_element(utt, "", dom_snapshot) if dom_snapshot else None
        lbl = (effective_label(node, nodes0) if node else "") or (dom_el.get("label", "") if dom_el else "")
        sig = (box, utt or info["raw_caption"] or None, info["is_skeleton"])
        if sig and sig == prev_sig:
            repeats += 1
            if repeats >= 3:
                print("      foco estancado; fin en paso %d" % i)
                break
        elif utt and len(utt) > 8 and not _is_chart_point_utt(utt) and utt in seen_utts and i > 10:
            # Si volvemos a anunciar exactamente el primer elemento tras recorrer la vista
            if len(steps) >= 6 and utt == steps[0].get("utterance"):
                print("      ciclo completo en paso %d (regresó al inicio)" % i)
                break
            repeats = 0
        else:
            repeats = 0
        prev_sig = sig
        if utt:
            seen_utts.add(utt)
        change = False
        if px:
            cur_screen = screen_sig(w, h, px)
            change = bool(prev_screen and sig_diff(prev_screen, cur_screen) > 35)
            prev_screen = cur_screen
        steps.append({
            "i": i,
            "png": png,
            "node": node,
            "utterance": utt,
            "raw_caption": info["raw_caption"],
            "page_title": info["page_title"],
            "is_skeleton": info["is_skeleton"],
            "box": box,
            "in_overlay": in_overlay,
            "label": lbl,
            "screen_change": change,
        })
        print("      %3d. %-52s | dice: %s" % (i, lbl[:50] or "?", (utt or "")[:60]))

        # Prueba automática de Retorno de Foco en modales/drawers (--test-modals):
        # Si enfocamos un botón disparador de modal/drawer informativo o selector y aún no se probó,
        # lo activamos con doble tap, capturamos la modal abierta, la cerramos y registramos dónde cae el foco.
        if (
            getattr(args, "test_modals", False)
            and utt
            and utt not in tested_modals
            and re.search(
                r"(m[aá]s informaci[oó]n sobre|more information on|select your linked account|eleg[ií] qu[eé] cripto|choose a cryptocurrency|order type|tipo de orden)",
                utt.lower(),
            )
        ):
            tested_modals.add(utt)
            print("      [test-modals] abriendo modal/drawer desde '%s' para validar Focus Return..." % utt[:45])
            adb_client.emu_double_tap()
            time.sleep(2.0)
            step_num += 1
            m_png = os.path.join(out_dir, "img", "step_%03d.png" % step_num)
            adb_client.screencap_png(m_png)
            m_info = (
                ocr_step_info(ocr_bin, m_png, bar_y)
                if ocr_bin
                else {"utterance": "", "raw_caption": "", "page_title": "", "is_skeleton": False}
            )
            m_utt = m_info["utterance"] or m_info["page_title"] or "Modal / Drawer"
            steps.append({
                "i": step_num,
                "png": m_png,
                "node": None,
                "utterance": m_utt,
                "raw_caption": m_info["raw_caption"],
                "page_title": m_info["page_title"],
                "is_skeleton": m_info["is_skeleton"],
                "box": None,
                "in_overlay": False,
                "label": m_info["page_title"] or "Modal / Drawer",
                "screen_change": True,
                "is_modal": True,
            })
            print("      %3d. %-52s | dice: %s [MODAL]" % (step_num, (m_info["page_title"] or "Modal")[:50], m_utt[:55]))
            # Cerrar modal por botón Cerrar/Close en CDP o tecla Back
            try:
                run_cdp_steps(
                    adb_client,
                    [
                        {
                            "click": 'button[aria-label="Cerrar"],button[aria-label="Close"],button[data-testid*="close"]',
                            "wait_sec": 1.4,
                        }
                    ],
                )
            except Exception:
                adb_client.run(["shell", "input", "keyevent", "4"], check=False)
                time.sleep(1.4)

        # Si enfocamos el botón "Siguiente consejo" / "Next tip" de un carrusel y no está inhabilitado,
        # lo activamos con doble tap y retrocedemos 5 elementos por swipe para leer la nueva tarjeta.
        if re.search(r"siguiente consejo|next tip", (utt or "").lower()) and not re.search(
            r"disabled|inhabilitado|deshabilitado|no disponible", (utt or "").lower()
        ):
            adb_client.emu_double_tap()
            time.sleep(1.4)
            for _ in range(5):
                adb_client.emu_swipe(backward=True)
                time.sleep(0.55)
            print("      [auto-carrusel] 'Siguiente consejo' activado para recorrer la siguiente tarjeta")

        # Si acumulamos 5 puntos seguidos de la gráfica (suficientes para activar TB-CHART-001),
        # ocultamos por CDP los <circle> restantes del árbol AX para que el siguiente swipe
        # continúe inmediatamente en el control posterior a la gráfica (sea de 30 o 289 puntos).
        if _is_chart_point_utt(utt):
            chart_streak += 1
            if chart_streak == 5:
                try:
                    run_cdp_steps(
                        adb_client,
                        [
                            {
                                "eval": (
                                    "(() => { document.querySelectorAll('circle[data-testid=\"node-circle\"], circle.node-path-focus-border')"
                                    ".forEach(c => { c.setAttribute('aria-hidden', 'true'); c.setAttribute('tabindex', '-1'); "
                                    "c.removeAttribute('role'); c.removeAttribute('aria-label'); }); return 'ok'; })()"
                                ),
                                "wait_sec": 0.6,
                            }
                        ],
                    )
                except Exception:
                    pass
                print("      [auto-skip gráfica] saltados los puntos restantes del gráfico para auditar el resto de la vista")
        else:
            chart_streak = 0
    return steps, visited


def run_self_test():
    """Autocomprobación rápida sin emulador: valida catálogo WCAG 2.2, reglas y generador HTML."""
    assert len(WCAG_CRITERIA) == 86, "Se esperaban 86 criterios WCAG 2.2"
    for rk in WCAG_ORDER:
        cat = WCAG_CATALOG[rk]
        meta = resolve_wcag_meta(cat["criterion"])
        assert meta["level"] in ("A", "AA", "AAA")
        assert meta["w3c_url"].startswith("https://www.w3.org/WAI/WCAG22/Understanding/")
    assert any("Moneda" in x for x in text_a11y_issues("$ 11.415.305,40"))
    assert not any("Moneda" in x for x in text_a11y_issues("US$ 82.119,30"))
    sample_steps = [
        {
            "i": 1, "png": "img/step_001.png", "node": None,
            "utterance": "Siguiente", "raw_caption": "Siguiente",
            "page_title": "Compra de criptomonedas", "is_skeleton": False,
            "box": (100, 200, 300, 260), "in_overlay": False, "label": "Siguiente",
            "screen_change": False,
        },
        {
            "i": 2, "png": "img/step_002.png", "node": None,
            "utterance": "", "raw_caption": "TalkBack menu. Button",
            "page_title": "Elegí con qué cuenta querés comprar tus criptos",
            "is_skeleton": True, "box": None, "in_overlay": True, "label": "",
            "screen_change": True,
        },
        {
            "i": 3, "png": "img/step_003.png", "node": None,
            "utterance": "1 replaced 0 · Siguiente", "raw_caption": "1 replaced 0 · Siguiente",
            "page_title": "Compra de criptomonedas", "is_skeleton": False,
            "box": None, "in_overlay": False, "label": "", "screen_change": True,
        },
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, "img"), exist_ok=True)
        out_html = build_report(sample_steps, [], set(), tmpdir, "self-test")
        content = open(out_html, encoding="utf-8").read()
        assert "TB-SKEL-001" in content, "Falta detección TB-SKEL-001 en self-test"
        assert "TB-FOCUS-001" in content, "Falta detección TB-FOCUS-001 en self-test"
    print("Self-test OK (v%s): 86 criterios WCAG 2.2, %d reglas TB-* y generador HTML verificados." % (
        VERSION, len(WCAG_CATALOG)
    ))


def navigate_to_view(adb_client, cfg, view_spec):
    """Navega declarativamente a una vista configurada en `cfg['views'][view_id]`."""
    print("      [view] preparando vista '%s'..." % view_spec.get("title", "?"))
    if cfg.get("sso_url") and cfg.get("login_url"):
        try:
            _refresh_session(cfg)
        except Exception as e:
            print("      [view] aviso refresh SSO: %s" % e)
    pkg = cfg.get("app_pkg") or ""
    act = view_spec.get("start_activity") or ""
    tap_xy = view_spec.get("entry_tap")
    needs_native_entry = bool((pkg and act) or (tap_xy and len(tap_xy) == 2))
    if needs_native_entry:
        adb_client.talkback_off()
        time.sleep(0.8)
    if pkg and act:
        comp = ("%s/%s" % (pkg, act)) if "/" not in act else act
        adb_client.run(["shell", "am", "start", "-n", comp], check=False)
        time.sleep(2.0)
    if tap_xy and len(tap_xy) == 2:
        if cfg.get("sso_url") and cfg.get("login_url"):
            try:
                _refresh_session(cfg, quiet=True)
            except Exception:
                pass
        adb_client.tap(int(tap_xy[0]), int(tap_xy[1]))
        time.sleep(float(view_spec.get("entry_wait_sec", 10.0)))
    if view_spec.get("cdp_steps"):
        run_cdp_steps(adb_client, view_spec["cdp_steps"])
    return needs_native_entry


def _print_installed_apps(adb_client):
    fg_pkg, fg_act = adb_client.get_foreground_package()
    apps = adb_client.list_installed_apps()
    print("Apps de usuario instaladas en %s (%d):" % (adb_client.device, len(apps)))
    for idx, p in enumerate(apps, 1):
        tag = ("  [ACTIVA EN PANTALLA: %s]" % fg_act) if p == fg_pkg else ""
        print("  %2d. %s%s" % (idx, p, tag))
    if fg_pkg and fg_pkg not in apps:
        print("  --  %s  [ACTIVA EN PANTALLA: %s]" % (fg_pkg, fg_act))
    return apps, fg_pkg


def _run_init_wizard(adb_client, cfg):
    import json

    print("\n=== Asistente de Configuración TalkBack Audit (v%s) ===" % VERSION)
    apps, fg_pkg = _print_installed_apps(adb_client)
    print("\nOpciones:")
    print("  [Enter] Usar la app activa en pantalla (%s)" % (fg_pkg or "ninguna"))
    print("  [1..%d] Elegir una app instalada por número" % len(apps))
    print("  [ruta]  Escribir ruta a un archivo .apk para instalarlo ahora")
    choice = input("\nSelección: ").strip()
    selected_pkg = ""
    if not choice:
        selected_pkg = fg_pkg
    elif choice.isdigit() and 1 <= int(choice) <= len(apps):
        selected_pkg = apps[int(choice) - 1]
    elif choice.endswith(".apk") or os.path.isfile(os.path.expanduser(choice)):
        selected_pkg = adb_client.install_apk(choice)
    else:
        selected_pkg = choice
    existing = {}
    if os.path.exists(LOCAL_CONFIG_PATH):
        try:
            with open(LOCAL_CONFIG_PATH, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = {}
    existing["device"] = adb_client.device
    if selected_pkg:
        existing["app_pkg"] = selected_pkg
    with open(LOCAL_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    print("\nGuardado en %s (app_pkg=%s)" % (LOCAL_CONFIG_PATH, selected_pkg or "auto"))
    if selected_pkg:
        adb_client.ensure_app_foreground(selected_pkg)


def main():
    ap = argparse.ArgumentParser(description="Auditoría TalkBack con reporte visual (v%s)" % VERSION)
    ap.add_argument("--version", action="version", version="talkback_audit %s" % VERSION)
    ap.add_argument("--config", metavar="FILE", help="archivo JSON de configuración opcional")
    ap.add_argument("--self-test", action="store_true", help="ejecuta autovalidación interna sin emulador y sale")
    ap.add_argument("--list-apps", action="store_true", help="lista las apps instaladas en el emulador (marcando la activa en pantalla) y sale")
    ap.add_argument("--apk", metavar="APK_FILE", help="instala un archivo .apk en el emulador, detecta su packageName y lo usa como app objetivo")
    ap.add_argument("--init", action="store_true", help="asistente interactivo para elegir/instalar la app objetivo y guardar config.local.json")
    ap.add_argument(
        "--view",
        metavar="VIEW_ID",
        help="ID de vista declarada en config['views'] (ej. landing, product_bitcoin, buy_bitcoin_step1, o 'all' para ejecutar todas)",
    )
    ap.add_argument("--view-title", metavar="TITLE", help="título descriptivo de la vista para la cabecera y pestaña del reporte")
    ap.add_argument("--steps", type=int, default=None, help="máx. de avances de foco (default 80 o según --view)")
    ap.add_argument(
        "--mode",
        choices=["swipe", "alt", "tab", "dpad"],
        default="swipe",
        help="swipe=gesto nativo TalkBack vía consola QEMU (default, recorre todos los elementos linealmente); "
        "alt=Alt+flecha; tab=orden de foco; dpad=flechas espacial",
    )
    ap.add_argument("--backward", action="store_true", help="navegar hacia atrás")
    ap.add_argument(
        "--manual",
        action="store_true",
        help="modo manual: tú navegas con gestos reales de TalkBack; el script captura cada anuncio",
    )
    ap.add_argument("--idle", type=float, default=10, help="segundos sin cambios para terminar en modo manual")
    ap.add_argument("--out", default=None, help="directorio del reporte")
    ap.add_argument("--pkg", default=None, metavar="PACKAGE", help="paquete Android de la app bajo prueba (o TB_APP_PKG / config.local.json)")
    ap.add_argument("--locale", default=None, metavar="BCP47", help="idioma objetivo para TalkBack y el emulador (ej. es-AR, en-US)")
    ap.add_argument("--device", default=None, help="serial del emulador (default: emulator-5554 o ANDROID_SERIAL)")
    ap.add_argument("--avd", default=None, help="nombre del AVD a levantar si no hay emulador corriendo")
    ap.add_argument("--delay", type=float, default=1.4, help="espera tras cada gesto (s)")
    ap.add_argument("--no-ocr", action="store_true")
    ap.add_argument(
        "--user",
        "-u",
        default=None,
        metavar="USER_ID",
        help="username y coreUserId para autenticación SSO opcional (TB_SSO_USER / config.local.json)",
    )
    ap.add_argument(
        "--core-user-id",
        default=None,
        metavar="CORE_ID",
        help="coreUserId para autenticación SSO opcional si difiere de --user",
    )
    ap.add_argument("--login", action="store_true", help="ejecuta el login SSO opcional antes de auditar")
    ap.add_argument(
        "--refresh",
        action="store_true",
        help="solo refresca la sesión SSO (2 POSTs) sin relanzar la app, antes de auditar",
    )
    ap.add_argument(
        "--keep-alive",
        type=float,
        default=None,
        metavar="SECS",
        help="renueva la sesión SSO en background cada N segundos (en --manual: 85s por defecto; 0 desactiva)",
    )
    ap.add_argument(
        "--net-delay",
        type=int,
        default=0,
        metavar="MS",
        help="añade latencia de red en el emulador (ej. 1200 ms) durante la prueba para apreciar todos los skeletons y anuncios 'Cargando {título}'",
    )
    ap.add_argument("--setup-only", action="store_true", help="solo configura TalkBack y sale")
    ap.add_argument("--no-setup", action="store_true", help="no tocar TalkBack ni reenfocar la app")
    ap.add_argument("--stop-talkback", action="store_true", help="apaga TalkBack al terminar")
    ap.add_argument(
        "--test-modals",
        action="store_true",
        help="en modo automático, abre y cierra modales/drawers detectados para validar Focus Return (TB-FOCUS-001)",
    )
    ap.add_argument(
        "--pack",
        nargs="?",
        const="auto",
        default=None,
        metavar="ZIP_FILE",
        help="genera index.html maestro y empaqueta los reportes de la suite en un archivo .zip autocontenido",
    )
    ap.add_argument("--rebuild", metavar="DIR", help="regenera report.html de una corrida previa (re-OCR capturas)")
    args = ap.parse_args()

    if args.self_test:
        run_self_test()
        return

    cfg = load_config(
        args.config, user_id=args.user, core_user_id=args.core_user_id, app_pkg=args.pkg
    )
    if args.device:
        cfg["device"] = args.device

    if args.rebuild:
        print("Regenerando reporte desde %s ..." % args.rebuild)
        ocr_bin = None if args.no_ocr else ensure_ocr_binary()
        v_info = {"title": args.view_title} if args.view_title else None
        print("Reporte: %s" % rebuild_report(ocr_bin, args.rebuild, view_info=v_info, cfg=cfg))
        return

    adb_client = AdbClient(device=cfg["device"], timeout=cfg["adb_timeout"])
    adb_client.ensure_emulator_running(avd_name=args.avd)
    target_loc = args.locale or cfg.get("locale") or ""
    if target_loc:
        adb_client.ensure_locale(target_loc)
    env_info = adb_client.preflight_check()
    if not target_loc and env_info["locale"].startswith("en"):
        print(
            "      [preflight] AVISO: emulador en locale '%s' (usa --locale es-AR si auditas una app en español)"
            % env_info["locale"]
        )

    if args.list_apps:
        _print_installed_apps(adb_client)
        return

    if args.init:
        _run_init_wizard(adb_client, cfg)
        return

    if args.apk:
        installed_pkg = adb_client.install_apk(args.apk)
        if installed_pkg:
            cfg["app_pkg"] = installed_pkg
            adb_client.ensure_app_foreground(installed_pkg)

    if not cfg.get("app_pkg"):
        fg_pkg, _ = adb_client.get_foreground_package()
        if fg_pkg:
            cfg["app_pkg"] = fg_pkg
            print("      [auto-pkg] detectada app en primer plano: %s" % fg_pkg)

    views_cfg = cfg.get("views") or {}
    if args.view and args.view.lower() == "all":
        view_queue = list(views_cfg.keys())
    elif args.view:
        if args.view not in views_cfg:
            raise SystemExit(
                "Vista '%s' no encontrada en config['views'] (disponibles: %s)"
                % (args.view, ", ".join(views_cfg.keys()) or "ninguna")
            )
        view_queue = [args.view]
    else:
        view_queue = [None]

    if args.refresh and not args.view:
        print("[0/4] Refrescando sesión SSO...")
        try:
            _refresh_session(cfg)
        except Exception as e:
            print("      ERROR refresh: %s" % e)

    if args.login:
        print("[0/4] Login SSO...")
        try:
            login_flow(adb_client, cfg)
        except Exception as e:
            print("      ERROR en login: %s" % e)

    if not args.view:
        if args.no_setup:
            print("[1/4] Omitiendo setup (--no-setup): TalkBack debe estar activo")
            if cfg.get("app_pkg"):
                adb_client.ensure_app_foreground(cfg["app_pkg"])
        else:
            print("[1/4] Activando TalkBack...")
            adb_client.talkback_on()
            time.sleep(2)
            print("[2/4] Verificando 'Display speech output'...")
            ok = adb_client.ensure_speech_display()
            print("      -> %s" % ("activo" if ok else "no se pudo verificar"))
            if cfg.get("app_pkg"):
                adb_client.ensure_app_foreground(cfg["app_pkg"])
    if args.setup_only:
        if args.stop_talkback:
            adb_client.talkback_off()
            print("TalkBack desactivado.")
        return

    ocr_bin = None if args.no_ocr else ensure_ocr_binary()
    completed_dirs = []

    for v_id in view_queue:
        v_spec = views_cfg.get(v_id, {}) if v_id else {}
        cur_out = (
            args.out
            if (args.out and len(view_queue) == 1)
            else v_spec.get("out")
            or os.path.join(
                os.getcwd(),
                "talkback_report_%s" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S"),
            )
        )
        img_dir = os.path.join(cur_out, "img")
        os.makedirs(img_dir, exist_ok=True)
        for old_png in os.listdir(img_dir):
            if old_png.startswith("step_") and old_png.endswith(".png"):
                try:
                    os.remove(os.path.join(img_dir, old_png))
                except OSError:
                    pass
        orig_steps = args.steps
        args.steps = int(orig_steps or v_spec.get("steps") or 80)

        did_off = False
        if v_spec:
            did_off = navigate_to_view(adb_client, cfg, v_spec)

        if args.net_delay and args.net_delay > 0:
            print("      [net-delay] aplicando latencia de red de %d ms en el emulador..." % args.net_delay)
            adb_client.set_network_delay(args.net_delay)

        print("      capturando árbol accesible inicial...")
        nodes0 = adb_client.dump_nodes() if did_off else []
        last_nodes = nodes0
        dom_snapshot = capture_webview_dom(adb_client)
        if did_off or not v_spec:
            adb_client.talkback_on()
            time.sleep(2.5)
        if dom_snapshot:
            po_info = dom_snapshot.get("poeditor") or {}
            po_str = (
                ", POEditor=%s (%s, %d keys)"
                % (po_info.get("version", "?"), po_info.get("language", "?"), po_info.get("totalKeys", 0))
                if po_info
                else ""
            )
            print(
                "      [CDP WebView] DOM capturado (%d elementos, %d puntos SVG, bundle=%s%s, url=%s)"
                % (
                    len(dom_snapshot.get("elements", [])),
                    dom_snapshot.get("circleCount", 0),
                    dom_snapshot.get("bundleVersion") or "n/d",
                    po_str,
                    dom_snapshot.get("url", "").split("#")[-1],
                )
            )

        ka_interval = cfg["keep_alive_sec"] if args.keep_alive is None else args.keep_alive
        ka_stop = start_keep_alive(cfg, ka_interval) if ka_interval and ka_interval > 0 else None
        try:
            if args.manual:
                if ka_stop:
                    print("[3/4] Registro manual de navegación TalkBack (keep-alive SSO cada %ds)..." % int(ka_interval))
                else:
                    print("[3/4] Registro manual de navegación TalkBack...")
                steps, last_nodes, visited = run_manual(adb_client, ocr_bin, cur_out, args)
                visited = visited or set()
            else:
                steps, visited = run_automated(
                    adb_client, ocr_bin, cur_out, nodes0, args, dom_snapshot=dom_snapshot
                )
        finally:
            if ka_stop:
                ka_stop.set()
            if args.net_delay and args.net_delay > 0:
                adb_client.set_network_delay(0)
                print("      [net-delay] latencia de red restaurada a 0 ms")
            args.steps = orig_steps

        print("[4/4] Generando reporte...")
        pkg = next((s["node"]["pkg"] for s in steps if s.get("node") and s["node"].get("pkg")), cfg["app_pkg"] or "n/d")
        modo = "manual" if args.manual else args.mode
        sso_user = (cfg.get("sso_body") or {}).get("username") or "n/d"
        extra_ver = ""
        if dom_snapshot:
            if dom_snapshot.get("bundleVersion"):
                extra_ver += " · bundle=v%s" % dom_snapshot["bundleVersion"]
            po = dom_snapshot.get("poeditor") or {}
            if po.get("version"):
                db_lbl = po.get("dbName") or "i18n"
                extra_ver += " · POEditor=%s v%s (%s, %d keys)" % (
                    db_lbl,
                    po["version"],
                    po.get("language", ""),
                    po.get("totalKeys", 0),
                )
        meta = "dispositivo=%s (SDK %s, locale %s) · user=%s · paquete=%s%s · modo=%s%s · pasos=%d · %s" % (
            cfg["device"],
            env_info["sdk"],
            env_info["locale"],
            sso_user,
            pkg,
            extra_ver,
            modo,
            " atrás" if args.backward else "",
            len(steps),
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        )
        view_info = {
            "title": args.view_title or v_spec.get("title"),
            "short_title": v_spec.get("short_title") or args.view_title,
            "scope_tag": v_spec.get("scope_tag"),
        }
        tree = [n for n in (last_nodes or nodes0) if is_a11y_relevant(n)]
        path = build_report(
            steps, tree, visited, cur_out, meta, dom_snapshot=dom_snapshot, view_info=view_info, cfg=cfg
        )
        completed_dirs.append(cur_out)
        print("Reporte: %s" % path)

    if len(completed_dirs) > 1 or args.pack:
        suite_dirs = completed_dirs
        if len(suite_dirs) <= 1 and views_cfg:
            suite_dirs = [
                v.get("out")
                for v in views_cfg.values()
                if v.get("out") and os.path.exists(os.path.join(v["out"], "report.html"))
            ] or completed_dirs
        zip_target = None
        if args.pack:
            zip_target = (
                os.path.join("reportes", "reportes_talkback_suite_v%s.zip" % VERSION)
                if args.pack == "auto"
                else args.pack
            )
        idx_p, zip_p = build_suite_index(suite_dirs, zip_path=zip_target)
        if idx_p:
            print("Portada maestra: %s" % idx_p)
        if zip_p:
            print("Paquete ZIP:     %s" % zip_p)

    if args.stop_talkback:
        adb_client.talkback_off()
        print("TalkBack desactivado.")


if __name__ == "__main__":
    main()
