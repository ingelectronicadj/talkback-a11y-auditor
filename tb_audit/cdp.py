"""Inspector DOM / AXTree y auditoría POEditor (IndexedDB) vía Chrome DevTools Protocol (CDP)."""

import base64
import json
import os
import re
import socket
import struct
import urllib.request
from .rules import norm_utt


def _ws_eval(port, ws_path, js_expr, await_promise=False):
    import time

    for attempt in range(2):
        s = socket.create_connection(("127.0.0.1", port), timeout=10)
        try:
            key = base64.b64encode(os.urandom(16)).decode()
            req = (
                "GET %s HTTP/1.1\r\n"
                "Host: 127.0.0.1:%d\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                "Sec-WebSocket-Key: %s\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n" % (ws_path, port, key)
            )
            s.sendall(req.encode())
            buf = b""
            while b"\r\n\r\n" not in buf:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
            payload = json.dumps({
                "id": 1,
                "method": "Runtime.evaluate",
                "params": {
                    "expression": js_expr,
                    "returnByValue": True,
                    "awaitPromise": bool(await_promise),
                },
            }).encode("utf-8")
            mask = os.urandom(4)
            masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            n = len(payload)
            if n < 126:
                hdr = struct.pack("!BB", 0x81, 0x80 | n)
            elif n < 65536:
                hdr = struct.pack("!BBH", 0x81, 0x80 | 126, n)
            else:
                hdr = struct.pack("!BBQ", 0x81, 0x80 | 127, n)
            s.sendall(hdr + mask + masked)

            def read_exact(k):
                b = b""
                while len(b) < k:
                    c = s.recv(k - len(b))
                    if not c:
                        raise EOFError()
                    b += c
                return b

            while True:
                _, b2 = struct.unpack("!BB", read_exact(2))
                length = b2 & 0x7F
                if length == 126:
                    length = struct.unpack("!H", read_exact(2))[0]
                elif length == 127:
                    length = struct.unpack("!Q", read_exact(8))[0]
                if b2 & 0x80:
                    rmask = read_exact(4)
                    data = bytes(b ^ rmask[i % 4] for i, b in enumerate(read_exact(length)))
                else:
                    data = read_exact(length)
                resp = json.loads(data.decode("utf-8", "replace"))
                if resp.get("id") == 1:
                    val = resp.get("result", {}).get("result", {}).get("value", "")
                    if isinstance(val, str) and val.startswith(("{", "[")):
                        return json.loads(val)
                    return val
        except (EOFError, OSError):
            if attempt == 0:
                time.sleep(0.5)
                continue
            return None
        finally:
            s.close()


DOM_EXTRACT_JS = r"""
(async () => {
  let poeditor = null;
  let entries = {};
  let dbUsed = '';
  try {
    const dbs = (await indexedDB.databases?.()) || [];
    const dbNames = dbs.map(d => d.name).filter(Boolean);
    // Priorizar bases de datos de dominio/microfrontend (con guión bajo) sobre CONFIG o WEB genérico
    dbNames.sort((a, b) => (a === 'CONFIG' ? 1 : b === 'CONFIG' ? -1 : a.includes('_') && !b.includes('_') ? -1 : 0));
    for (const dbName of dbNames) {
      const db = await new Promise((res, rej) => {
        const req = indexedDB.open(dbName);
        req.onsuccess = () => res(req.result);
        req.onerror = () => rej(req.error);
      });
      for (const stName of Array.from(db.objectStoreNames)) {
        const tx = db.transaction(stName, 'readonly');
        const val = await new Promise(r => {
          const q = tx.objectStore(stName).get('translations');
          q.onsuccess = () => r(q.result);
          q.onerror = () => r(null);
        });
        if (val && val.entries && Object.keys(val.entries).length > 30) {
          entries = val.entries;
          dbUsed = dbName;
          const langLow = (val.language || '').toLowerCase();
          const englishKeys = [];
          const uninterpolatedKeys = [];
          const emptyKeys = [];
          const styleOrTypoKeys = [];
          for (const [k, rawV] of Object.entries(entries)) {
            const v = String(rawV || '');
            if (!v.trim()) {
              emptyKeys.push({ key: k, value: '', note: 'Key vacía en diccionario i18n (provoca enlaces/textos sin etiqueta)' });
              continue;
            }
            if (/\{([A-Z][A-Z0-9_\s]{2,25}|\d{2,}\.\d{2,})\}|\{[A-Za-z0-9_]+\]|\[[A-Za-z0-9_]+\}/.test(v)) {
              uninterpolatedKeys.push({ key: k, value: v, note: 'Placeholder literal sin interpolar o delimitador mal cerrado' });
            }
            if (langLow.startsWith('es') && /\b(select your|select a|select the|choose one|change frequency|you can only select|prices are volatile|this will be the account)\b/i.test(v)) {
              englishKeys.push({ key: k, value: v, note: 'Texto en inglés dentro de paquete localizado (' + (val.language || 'es') + ')' });
            } else if (langLow.startsWith('en') && /\b(en el complejo ecosistema|en el actual ecosistema|descripci[oó]n corta|pendiente del equipo)\b/i.test(v)) {
              englishKeys.push({ key: k, value: v, note: 'Texto en español sin traducir dentro del paquete en inglés (' + (val.language || 'en-us') + ')' });
            }
            if (/\b[uú]ltimas\s+ordenes\b/i.test(v)) {
              styleOrTypoKeys.push({ key: k, value: v, note: 'Falta tilde en "Últimas órdenes"' });
            } else if (k.startsWith('a11y_') && v.length > 140) {
              styleOrTypoKeys.push({ key: k, value: v.slice(0, 110) + '...', note: 'Key de encabezado oculto (h2) contiene párrafo largo completo (duplica anuncio)' });
            } else if (langLow === 'es-ar' && /\b(puedes|quieres|tienes|selecciona|ingresa)\b/i.test(v)) {
              styleOrTypoKeys.push({ key: k, value: v, note: 'Tuteo (es-ES) en lugar de voseo argentino (es-AR: podés/querés/tenés)' });
            }
          }
          poeditor = {
            dbName: dbUsed,
            version: val.version || '',
            language: val.language || '',
            totalKeys: Object.keys(entries).length,
            englishKeys,
            uninterpolatedKeys,
            emptyKeys,
            styleOrTypoKeys
          };
          break;
        }
      }
      if (poeditor) break;
    }
  } catch (e) {}

  const valToKeys = {};
  for (const [k, rawV] of Object.entries(entries)) {
    const v = String(rawV || '').trim();
    if (!v) continue;
    if (!valToKeys[v]) valToKeys[v] = [];
    valToKeys[v].push(k);
  }

  function resolveKeyMeta(label, ariaLabel, testId) {
    const cand = (ariaLabel || label || '').trim();
    if (!cand) {
      return null;
    }
    if (/^(a11y_|i18n_|msg_)[a-z0-9_]+$/i.test(cand) || /^[a-z0-9]{2,8}(_[a-z0-9]+){3,}$/i.test(cand)) {
      const inDict = Object.prototype.hasOwnProperty.call(entries, cand);
      return {
        key: cand,
        status: inDict ? 'RAW_KEY' : 'MISSING_IN_I18N',
        origin: inDict ? 'Origen: Diccionario i18n / Bundle' : 'Origen: Código Front-End (referencia a key inexistente en el diccionario i18n)'
      };
    }
    if (valToKeys[cand]) {
      const keys = valToKeys[cand];
      const k0 = keys[0];
      let origin = 'Origen: Diccionario i18n';
      if (/\b(select your|choose one|select a)\b/i.test(cand)) {
        origin = 'Origen: Código Front-End (referencia a key en inglés fuera de alcance) / Diccionario i18n';
      }
      return { key: keys.join(', '), status: 'MATCHED', origin };
    }
    if (cand.includes('(Abrir una nueva ventana)') && /^(\S+\s+\S+)\s+\1/i.test(cand)) {
      return {
        key: 'aria-labelledby compuesto',
        status: 'COMPOSITE_ARIA',
        origin: 'Origen: Código Front-End (aria-labelledby autorreferencia el <a> y duplica el texto visible)'
      };
    }
    if (cand === '(Abrir una nueva ventana)') {
      return {
        key: 'enlace con etiqueta vacía',
        status: 'EMPTY_IN_I18N',
        origin: 'Origen: Código Front-End (renderiza <a> aunque la key de texto del enlace venga vacía)'
      };
    }
    return null;
  }

  const out = [];
  const els = document.querySelectorAll(
    'h1,h2,h3,h4,button,a,input,p,span[id],li[data-testid],svg,img,circle[data-testid="node-circle"],dt,dd,[role],[aria-label],[aria-labelledby],[aria-live],[data-testid]'
  );
  for (const el of els) {
    const tag = el.tagName.toLowerCase();
    const testId = el.getAttribute('data-testid') || '';
    const id = el.getAttribute('id') || '';
    const role = el.getAttribute('role') || '';
    const ariaLabel = el.getAttribute('aria-label') || '';
    const ariaLabelledby = el.getAttribute('aria-labelledby') || '';
    const ariaHidden = el.getAttribute('aria-hidden') || '';
    const ariaLive = el.getAttribute('aria-live') || '';
    const tabindex = el.getAttribute('tabindex') || '';
    const nestedSpanAria = (!ariaLabel && (tag === 'button' || tag === 'a'))
      ? (el.querySelector('span[aria-label]:not([role]), div[aria-label]:not([role])')?.getAttribute('aria-label') || '').trim()
      : '';
    const hasUiLibAttr = Array.from(el.attributes || []).some(a => /^data-[a-z]{2,6}-id$/i.test(a.name))
      || !!el.querySelector('[data-pill-content], [data-background-tab]');
    const hasForLabel = !!(id && document.querySelector('label[for="' + id + '"]')) || !!el.closest('label');
    const placeholder = (el.getAttribute('placeholder') || '').trim();
    const inputPlaceholderOnly = (tag === 'input' && (el.type || 'text') !== 'hidden' && (el.type || '') !== 'radio' && (el.type || '') !== 'checkbox' && !ariaLabel && !ariaLabelledby && !hasForLabel && placeholder)
      ? placeholder
      : '';
    const visibleInner = (el.innerText || el.textContent || '').trim().replace(/\s+/g, ' ');
    const comboboxMissingValue = (role === 'combobox' && visibleInner && ariaLabelledby)
      ? (() => {
          const lblByTxt = ariaLabelledby.split(/\s+/).map(rid => document.getElementById(rid)?.textContent?.trim() || '').join(' ').trim();
          return (lblByTxt && !lblByTxt.toLowerCase().includes(visibleInner.toLowerCase())) ? (lblByTxt + ' (omite valor seleccionado «' + visibleInner + '»)') : '';
        })()
      : '';
    let label = ariaLabel;
    if (!label && ariaLabelledby) {
      label = ariaLabelledby.split(/\s+/).map(rid => document.getElementById(rid)?.textContent?.trim() || '').join(' ').trim();
    }
    if (!label) {
      label = (el.innerText || el.textContent || '').trim().replace(/\s+/g, ' ');
    }
    if (!label && tag !== 'svg' && tag !== 'img' && tag !== 'input' && !ariaLive && !nestedSpanAria) continue;
    let sel = tag;
    if (id) sel += '#' + id;
    if (testId) sel += `[data-testid="${testId}"]`;
    if (role) sel += `[role="${role}"]`;
    if (testId === 'text' || (!id && !testId)) {
      const pEl = el.parentElement?.closest('[data-testid]');
      const pTid = pEl ? pEl.getAttribute('data-testid') : '';
      if (pTid && pTid !== 'text' && pTid !== 'layout') {
        sel = `${pEl.tagName.toLowerCase()}[data-testid="${pTid}"] > ${sel}`;
      }
    }
    const keyMeta = resolveKeyMeta(label, ariaLabel, testId);
    const r = el.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const rect = (r && r.width > 0 && r.height > 0)
      ? [Math.round(r.left * dpr), Math.round(r.top * dpr), Math.round(r.right * dpr), Math.round(r.bottom * dpr)]
      : null;
    out.push({
      tag,
      selector: sel,
      testId,
      id,
      role,
      ariaLabel,
      ariaLabelledby,
      ariaHidden,
      ariaLive,
      tabindex,
      rect,
      label: label.slice(0, 220),
      poeditorKey: keyMeta ? keyMeta.key : '',
      poeditorOrigin: keyMeta ? keyMeta.origin : (hasUiLibAttr ? 'Origen: Componente de Librería UI (Design System)' : 'Origen: Código Front-End de la Vista'),
      nestedSpanAria,
      inputPlaceholderOnly,
      comboboxMissingValue,
      html: el.outerHTML.replace(/\s+/g, ' ').slice(0, 300)
    });
  }
  const bMatch = location.href.match(/\/hybrid\/(?:packages\/)?[^/]+\/([^/]+)\//);
  const h1Text = (document.querySelector('h1')?.innerText || document.querySelector('h1')?.textContent || '').trim().replace(/\s+/g, ' ');
  return JSON.stringify({
    url: location.href,
    routeHash: location.hash || location.pathname || '',
    viewHeading: h1Text,
    bundleVersion: bMatch ? bMatch[1] : '',
    lang: document.documentElement.getAttribute('lang') || '',
    circleCount: document.querySelectorAll('circle[data-testid="node-circle"]').length,
    poeditor,
    elements: out
  });
})()
"""


def _connect_cdp_ws(adb_client, port=9222):
    fg_pkg, _ = adb_client.get_foreground_package()
    fg_pid = ""
    if fg_pkg:
        fg_pid = adb_client.run(["shell", "pidof", fg_pkg], check=False).strip().split()[0] if adb_client.run(["shell", "pidof", fg_pkg], check=False).strip() else ""
    unix_out = adb_client.run(
        ["shell", "cat /proc/net/unix | grep -o 'webview_devtools_remote_[0-9]*' | sort -u"],
        check=False,
    ).strip()
    if not unix_out:
        return None
    socks = [s.strip() for s in unix_out.splitlines() if s.strip()]
    sock_name = socks[-1]
    if fg_pid:
        target = "webview_devtools_remote_%s" % fg_pid
        if target in socks:
            sock_name = target
    adb_client.run(["forward", "tcp:%d" % port, "localabstract:%s" % sock_name], check=False)
    pages = json.loads(
        urllib.request.urlopen("http://127.0.0.1:%d/json" % port, timeout=4).read()
    )
    if not pages:
        return None
    chosen = None
    for p in pages:
        u = (p.get("url") or "").lower()
        if any(t in u for t in ("utag/", "tiqcdn", "analytics", "about:blank")):
            continue
        if "hybrid/" in u or "file://" in u:
            chosen = p
            break
        if u and not chosen:
            chosen = p
    if not chosen:
        return None
    ws_url = chosen.get("webSocketDebuggerUrl", "")
    if not ws_url:
        return None
    return "/" + ws_url.split("/", 3)[3]


def run_cdp_steps(adb_client, cdp_steps, port=9222, out_dir=None):
    """Ejecuta una lista declarativa de acciones en el WebView vía CDP (`hash`, `spa_path`, `click`/`click_selector`,
    `click_text`, `type_selector`, `eval`, `wait_for_*`, `loading_probe`, `probe_control`) y devuelve la lista de probes."""
    import time

    probes = []
    if not cdp_steps:
        return probes
    ws_path = _connect_cdp_ws(adb_client, port=port)
    if not ws_path:
        return probes
    _ws_eval(
        port,
        ws_path,
        "(() => { try { if (document.activeElement) document.activeElement.blur(); window.scrollTo(0, 0); } catch(e){} return 'ok'; })()",
    )
    for st in cdp_steps:
        if st.get("wait_for_text") or st.get("wait_for_selector") or "wait_for_skeleton" in st:
            timeout_s = float(st.get("timeout_sec", 30))
            t0 = time.time()
            met = False
            w_cfg = json.dumps({
                "txt": st.get("wait_for_text"),
                "sel": st.get("wait_for_selector"),
                "skel": st.get("wait_for_skeleton"),
            })
            while time.time() - t0 < timeout_s:
                js_w = (
                    "(() => { const w = %s; if (w.sel) return !!document.querySelector(w.sel); "
                    "if (w.txt) return (document.body?.innerText || '').toLowerCase().includes(w.txt.toLowerCase()); "
                    "const sc = Array.from(document.querySelectorAll('[class*=\"skeleton\" i], [data-testid*=\"skeleton\" i], [aria-busy=\"true\"]')).filter(e => { const r = e.getBoundingClientRect(); return r.height > 2 && r.width > 2; }).length; "
                    "return w.skel ? sc > 0 : sc === 0; })()" % w_cfg
                )
                if _ws_eval(port, ws_path, js_w):
                    met = True
                    break
                time.sleep(0.45)
            if not met:
                print("      [WARN] wait_for timeout (%ss): %s" % (int(timeout_s), w_cfg))
        lp_cfg = st.get("loading_probe") if isinstance(st.get("loading_probe"), dict) else ({} if st.get("loading_probe") else None)
        if lp_cfg is not None and hasattr(adb_client, "set_network_delay"):
            try:
                adb_client.set_network_delay(int(lp_cfg.get("delay_ms", 1200)))
            except Exception:
                pass
        if st.get("hash"):
            js = (
                "(() => { try { if (document.activeElement) document.activeElement.blur(); } catch(e){} location.hash = %s; return 'ok'; })()"
                % json.dumps(st["hash"])
            )
            _ws_eval(port, ws_path, js)
        elif st.get("spa_path"):
            p = json.dumps(st["spa_path"])
            js = (
                "(async () => { const prev = (document.querySelector('main h1, h1')?.innerText || '').trim(); "
                "const cb = document.querySelector('[role=\"dialog\"] button[aria-label=\"Close\"], [role=\"dialog\"] button[data-testid=\"close-button\"]'); if (cb) cb.click(); "
                "window.history.pushState({}, '', %s); window.dispatchEvent(new PopStateEvent('popstate')); "
                "for (let w = 0; w < 10; w++) { await new Promise(r => setTimeout(r, 700)); const h = (document.querySelector('main h1, h1')?.innerText || '').trim(); if (h && h !== prev) break; } return 'ok'; })()" % p
            )
            _ws_eval(port, ws_path, js, await_promise=True)
        elif st.get("click") or st.get("click_selector"):
            raw_sel = st.get("click") or st.get("click_selector")
            sel = json.dumps(raw_sel)
            js = (
                "(() => { const el = document.querySelector(%s); if (el) { el.click(); return 'clicked'; } return 'not-found'; })()"
                % sel
            )
            if _ws_eval(port, ws_path, js) == "not-found":
                print('      [WARN] click_selector no encontrado: "%s"' % raw_sel)
        elif st.get("click_text"):
            raw_txt = st["click_text"]
            txt = json.dumps(raw_txt)
            js = (
                "(() => { const needle = %s.toLowerCase(); "
                "const openDlg = Array.from(document.querySelectorAll('[role=\"dialog\"]')).find(d => d.getBoundingClientRect().width > 50); "
                "const root = openDlg || document.querySelector('main') || document.body; "
                "const cands = Array.from(root.querySelectorAll('a, button, [role=\"tab\"], [role=\"button\"], label, [data-testid=\"selector-row\"], p, span')); "
                "for (const el of cands) { const t = ((el.innerText || '') + ' ' + (el.getAttribute('aria-label') || '')).trim().toLowerCase(); "
                "if (t === needle || t.includes(needle)) { let target = el.closest('a, button, [role=\"button\"], [role=\"tab\"], [role=\"combobox\"], [data-testid=\"selector-row\"]'); "
                "if (!target && el.tagName === 'LABEL') target = (el.htmlFor && document.getElementById(el.htmlFor)) || (el.id && root.querySelector('[aria-labelledby~=\"' + el.id + '\"]')); "
                "(target || el).click(); return 'clicked'; } } return 'not-found'; })()" % txt
            )
            if _ws_eval(port, ws_path, js) == "not-found":
                print('      [WARN] click_text no encontrado: "%s"' % raw_txt)
        elif st.get("type_selector"):
            sel = json.dumps(st["type_selector"])
            val = json.dumps(str(st.get("text") or ""))
            js = (
                "(() => { const el = document.querySelector(%s); if (!el) return 'not-found'; el.focus(); "
                "const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set; "
                "if (setter) setter.call(el, %s); else el.value = %s; "
                "el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); return 'ok'; })()" % (sel, val, val)
            )
            _ws_eval(port, ws_path, js)
        elif st.get("eval"):
            _ws_eval(port, ws_path, st["eval"])
        wait_s = float(st.get("wait_sec", 2.0))
        if wait_s > 0:
            time.sleep(wait_s)
        if lp_cfg is not None:
            watch_s = float(lp_cfg.get("watch_ms", 25000)) / 1000.0
            png_name = lp_cfg.get("png_name") or "loading"
            probe = {
                "type": "loading_probe",
                "network": lp_cfg.get("network") or "Slow 3G",
                "announcements": [],
                "skeleton_detected": False,
                "screenshots": [],
                "loading_announced": False,
            }
            seen = set()
            captured = False
            ann_png = False
            t0 = time.time()
            while time.time() - t0 < watch_s:
                stt = _ws_eval(
                    port,
                    ws_path,
                    "(() => { const out = { announcers: [], skeletonCount: 0 }; "
                    "document.querySelectorAll('[role=\"status\"], [aria-live]').forEach(el => { "
                    "const txt = el.textContent || ''; out.announcers.push({ selector: el.getAttribute('data-testid') || el.getAttribute('role') || el.tagName, text: txt, codepoints: Array.from(txt).map(c => 'U+' + c.codePointAt(0).toString(16).toUpperCase()) }); }); "
                    "out.skeletonCount = Array.from(document.querySelectorAll('[class*=\"skeleton\" i], [data-testid*=\"skeleton\" i], [aria-busy=\"true\"]')).filter(e => { const r = e.getBoundingClientRect(); return r.height > 2 && r.width > 2; }).length; "
                    "return JSON.stringify(out); })()",
                )
                if isinstance(stt, dict):
                    for a in stt.get("announcers") or []:
                        k = "%s|%s" % (a.get("selector"), a.get("text"))
                        if k not in seen:
                            seen.add(k)
                            probe["announcements"].append(a)
                        cl = (a.get("text") or "").replace("\u200b", "").strip()
                        if len(cl) > 1 and re.search(r"load|carg|esper|wait", cl, re.I):
                            probe["loading_announced"] = True
                    if (stt.get("skeletonCount") or 0) > 0:
                        probe["skeleton_detected"] = True
                        if not captured and out_dir and hasattr(adb_client, "screencap_png"):
                            fn = "%s_skeleton.png" % png_name
                            adb_client.screencap_png(os.path.join(out_dir, "img", fn))
                            probe["screenshots"].append(fn)
                            captured = True
                        if not ann_png and lp_cfg.get("make_announcer_visible") and probe["loading_announced"] and out_dir and hasattr(adb_client, "screencap_png"):
                            _ws_eval(
                                port,
                                ws_path,
                                "(() => { const el = document.querySelector('span[data-testid=\"screen-reader\"], [role=\"status\"], [aria-live]'); "
                                "if (el) el.style.cssText = 'position:fixed;left:16px;bottom:16px;z-index:999999;background:#111;color:#0f0;font:16px monospace;padding:10px 14px;border:2px solid #0f0;border-radius:6px;clip:auto!important;width:auto!important;height:auto!important;overflow:visible!important;'; return 'ok'; })()",
                            )
                            time.sleep(0.4)
                            fn_a = "%s_announcer.png" % png_name
                            adb_client.screencap_png(os.path.join(out_dir, "img", fn_a))
                            probe["screenshots"].append(fn_a)
                            ann_png = True
                    if captured and (stt.get("skeletonCount") or 0) == 0:
                        break
                time.sleep(0.4)
            if hasattr(adb_client, "set_network_delay"):
                try:
                    adb_client.set_network_delay(0)
                except Exception:
                    pass
            probes.append(probe)
        if st.get("probe_control"):
            lbl = st["probe_control"]
            png_name = st.get("png_name") or "control_probe"
            _ws_eval(
                port,
                ws_path,
                "(() => { const needle = %s.toLowerCase(); const openDlg = Array.from(document.querySelectorAll('[role=\"dialog\"]')).find(d => d.getBoundingClientRect().width > 50); "
                "const root = openDlg || document.querySelector('main') || document.body; "
                "const cands = Array.from(root.querySelectorAll('a, button, [role=\"tab\"], [role=\"button\"], label, [data-testid=\"selector-row\"], p, span')); "
                "for (const el of cands) { const t = ((el.innerText || '') + ' ' + (el.getAttribute('aria-label') || '')).trim().toLowerCase(); "
                "if (t === needle || t.includes(needle)) { let target = el.closest('a, button, [role=\"button\"], [role=\"tab\"], [role=\"combobox\"], [data-testid=\"selector-row\"]'); "
                "if (!target && el.tagName === 'LABEL') target = (el.htmlFor && document.getElementById(el.htmlFor)) || (el.id && root.querySelector('[aria-labelledby~=\"' + el.id + '\"]')); "
                "(target || el).click(); return 'clicked'; } } return 'not-found'; })()" % json.dumps(lbl),
            )
            time.sleep(float(st.get("wait_sec", 2.0)))
            shots = []
            if out_dir and hasattr(adb_client, "screencap_png"):
                fn = "%s.png" % png_name
                adb_client.screencap_png(os.path.join(out_dir, "img", fn))
                shots.append(fn)
            dump = _ws_eval(
                port,
                ws_path,
                "(() => { const dlg = document.querySelector('[role=\"dialog\"]'); let root = dlg || document; "
                "let listbox = root.querySelector('[role=\"listbox\"], [role=\"radiogroup\"], [role=\"menu\"], [role=\"grid\"], [role=\"tree\"]'); "
                "if (!listbox && dlg) { root = document; listbox = document.querySelector('[role=\"listbox\"], [role=\"radiogroup\"], [role=\"menu\"], [role=\"grid\"], [role=\"tree\"]'); } "
                "const trig = Array.from(root.querySelectorAll('button, [role=\"button\"], [role=\"combobox\"]')).find(e => e.getAttribute('aria-expanded') === 'true'); "
                "const opts = Array.from(root.querySelectorAll('[role=\"option\"], [role=\"radio\"], [role=\"menuitemradio\"], [role=\"menuitemcheckbox\"], [role=\"gridcell\"], [role=\"row\"] > *')).slice(0, 60).map(o => ({ role: o.getAttribute('role') || o.tagName.toLowerCase(), text: (o.innerText || '').trim().slice(0, 60), ariaLabel: o.getAttribute('aria-label') || '', selected: o.getAttribute('aria-selected') ?? o.getAttribute('aria-checked'), disabled: o.getAttribute('aria-disabled') })); "
                "const emptyDayCells = opts.filter(o => /empty day/i.test(o.ariaLabel || '')).length; "
                "return JSON.stringify({ trigger_expanded: trig ? (trig.getAttribute('aria-label') || (trig.innerText || '').trim().slice(0, 50)) : null, trigger_haspopup: trig ? trig.getAttribute('aria-haspopup') : null, container_role: listbox ? listbox.getAttribute('role') : null, container_label: listbox ? (listbox.getAttribute('aria-label') || listbox.getAttribute('aria-labelledby') || '') : null, option_count: opts.length, options: opts, empty_day_cells: emptyDayCells }); })()",
            ) or {}
            pr = {"type": "probe_control", "control": lbl, "screenshots": shots, "structure": dump if isinstance(dump, dict) else {}}
            if isinstance(dump, dict) and (dump.get("empty_day_cells") or 0) > 0:
                pr["potential_issue"] = 'Grid padding cells announce "%dx empty day" via aria-label (WCAG 4.1.2: decorative cells should be empty or aria-hidden)' % dump["empty_day_cells"]
            probes.append(pr)
    _ws_eval(
        port,
        ws_path,
        "(() => { try { window.scrollTo(0, 0); document.documentElement.scrollTop = 0; document.body.scrollTop = 0; } catch(e){} return 'ok'; })()",
    )
    return probes


def capture_webview_dom(adb_client, port=9222):
    """Conecta al socket `webview_devtools_remote_<pid>` del emulador y devuelve
    el inventario DOM/ARIA y auditoría POEditor (IndexedDB) de la vista WebView actual."""
    try:
        ws_path = _connect_cdp_ws(adb_client, port=port)
        if not ws_path:
            return None
        return _ws_eval(port, ws_path, DOM_EXTRACT_JS, await_promise=True)
    except Exception:
        return None


def _strip_tb_role_suffix(text):
    """Elimina sufijos de rol/estado añadidos por TalkBack para correlacionar con el DOM."""
    s = (text or "").strip()
    s = re.sub(
        r"[\s.·,]*(bot[oó]n( de opci[oó]n)?|button|encabezado(\s*\d+)?|heading(\s*\d+)?|"
        r"v[ií]nculo|link|imagen|image|t[eé]rmino|inhabilitado|disabled|seleccionado|selected|"
        r"casilla de verificaci[oó]n|edici[oó]n casilla|edit box|fuera de la lista|en la lista.*|"
        r"\d+\s*de\s*\d+.*)$",
        "",
        s,
        flags=re.I,
    )
    return s.strip()


def match_dom_element(utterance, label, dom_snapshot, box=None):
    """Correlaciona el anuncio de TalkBack con el elemento DOM real del WebView (por texto y por geometría de foco)."""
    if not dom_snapshot or not dom_snapshot.get("elements"):
        return None
    elements = dom_snapshot["elements"]
    u_raw = (utterance or label or "").lower()
    if "sin etiquetar" in u_raw or "unlabelled" in u_raw:
        for el in elements:
            if el["tag"] == "svg" and el["testId"].startswith("line-chart"):
                return el
    if "signo de dólar" in u_raw or "dollar sign" in u_raw or u_raw.strip() == "euro":
        for el in elements:
            if el.get("id") == "inputCurrencyAffix" or el.get("label", "").strip() in ("$", "€"):
                return el
    if u_raw.strip() in ("o btc", "0 btc"):
        for el in elements:
            if "0 btc" in (el.get("label") or "").lower():
                return el
    if "detected: text" in u_raw or "etected: text" in u_raw or "texto detectado" in u_raw:
        for el in elements:
            if el["tag"] == "img" and el.get("testId") == "illustration":
                return el
    if u_raw.strip() in ("status", "estado"):
        for el in elements:
            if el["role"] == "status" or el["ariaLive"]:
                return el
    if re.search(r"^(double-tap to activate|tocar dos veces para activar|toc[aá] dos veces para activar)$", u_raw.strip()):
        if box and len(box) == 4:
            bx1, by1, bx2, by2 = box
            bcx, bcy = (bx1 + bx2) / 2.0, (by1 + by2) / 2.0
            best_geo = None
            for el in elements:
                r = el.get("rect")
                if r and len(r) == 4 and el.get("tag") in ("button", "a", "input"):
                    rcx, rcy = (r[0] + r[2]) / 2.0, (r[1] + r[3]) / 2.0
                    dist = abs(bcx - rcx) + abs(bcy - rcy)
                    if best_geo is None or dist < best_geo[0]:
                        best_geo = (dist, el)
            if best_geo and best_geo[0] < 380:
                return best_geo[1]
        for el in reversed(elements):
            if el.get("tag") == "button" and el.get("ariaLabel") and "order" in el["ariaLabel"].lower():
                return el
    has_interactive_role = bool(
        re.search(
            r"\b(bot[oó]n|button|v[ií]nculo|link|edici[oó]n|edit box|opci[oó]n|pestaña|tab|radio)\b",
            u_raw,
        )
    )
    cleaned = _strip_tb_role_suffix(utterance or label)
    utt_n = norm_utt(cleaned) or norm_utt(utterance or label)
    if not utt_n or len(utt_n) < 2:
        if box and len(box) == 4:
            bx1, by1, bx2, by2 = box
            bcx, bcy = (bx1 + bx2) / 2.0, (by1 + by2) / 2.0
            best_geo = None
            for el in elements:
                r = el.get("rect")
                if r and len(r) == 4 and el.get("tag") not in ("main", "div"):
                    rcx, rcy = (r[0] + r[2]) / 2.0, (r[1] + r[3]) / 2.0
                    dist = abs(bcx - rcx) + abs(bcy - rcy)
                    if best_geo is None or dist < best_geo[0]:
                        best_geo = (dist, el)
            if best_geo and best_geo[0] < 240:
                return best_geo[1]
        return None
    best = None
    for el in elements:
        tag = el.get("tag", "")
        if tag == "main" or el.get("testId") in ("layout", "header-operative-content"):
            continue
        ln = norm_utt(el.get("label", ""))
        if not ln:
            continue
        # No emparejar un anuncio de texto estático (sin rol 'Botón'/'vínculo') con un <button>/<a>
        # salvo que la etiqueta sea idéntica.
        if tag in ("button", "a", "input") and not has_interactive_role and ln != utt_n:
            continue
        if ln == utt_n or (len(ln) >= 3 and ln in utt_n) or (len(utt_n) >= 3 and utt_n in ln):
            exact_bonus = 50 if ln == utt_n else (20 if ln.startswith(utt_n) or utt_n.startswith(ln) else 0)
            len_penalty = max(0, len(ln) - len(utt_n))
            role_match_bonus = 15 if (has_interactive_role and tag in ("button", "a", "input")) else 0
            bonus = (
                exact_bonus
                + role_match_bonus
                + (4 if el.get("poeditorKey") else 0)
                + (3 if el.get("ariaLabel") or el.get("ariaLabelledby") else 0)
                + (2 if tag in ("h1", "h2", "h3", "button", "a", "input", "circle", "dt", "dd", "p") else 0)
                + (1 if el.get("testId") else 0)
                - len_penalty // 4
            )
            score = (exact_bonus, min(len(ln), len(utt_n)), bonus)
            if best is None or score > best[0]:
                best = (score, el)
    return best[1] if best else None
