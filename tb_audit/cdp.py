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
    chosen = pages[0]
    for p in pages:
        u = (p.get("url") or "").lower()
        if ("hybrid/" in u or "file://" in u) and not any(t in u for t in ("utag/", "analytics", "about:blank")):
            chosen = p
            break
        if u and not any(t in u for t in ("utag/", "analytics", "about:blank")):
            chosen = p
    ws_url = chosen.get("webSocketDebuggerUrl", "")
    if not ws_url:
        return None
    return "/" + ws_url.split("/", 3)[3]


def run_cdp_steps(adb_client, cdp_steps, port=9222):
    """Ejecuta una lista declarativa de acciones en el WebView vía CDP (`click`, `click_text`, `hash`, `eval`)."""
    import time

    if not cdp_steps:
        return
    ws_path = _connect_cdp_ws(adb_client, port=port)
    if not ws_path:
        return
    _ws_eval(
        port,
        ws_path,
        "(() => { try { if (document.activeElement) document.activeElement.blur(); window.scrollTo(0, 0); } catch(e){} return 'ok'; })()",
    )
    for st in cdp_steps:
        if st.get("hash"):
            js = (
                "(() => { try { if (document.activeElement) document.activeElement.blur(); } catch(e){} location.hash = %s; return 'ok'; })()"
                % json.dumps(st["hash"])
            )
            _ws_eval(port, ws_path, js)
        elif st.get("click"):
            sel = json.dumps(st["click"])
            js = (
                "(() => { const el = document.querySelector(%s); if (el) { el.click(); return 'clicked'; } return 'not-found'; })()"
                % sel
            )
            _ws_eval(port, ws_path, js)
        elif st.get("click_text"):
            txt = json.dumps(st["click_text"])
            tag = json.dumps(st.get("tag", "button,a"))
            js = (
                "(() => { const t = %s.toLowerCase(); const el = Array.from(document.querySelectorAll(%s)).find(e => (e.innerText || e.textContent || e.getAttribute('aria-label') || '').toLowerCase().includes(t)); if (el) { el.click(); return 'clicked'; } return 'not-found'; })()"
                % (txt, tag)
            )
            _ws_eval(port, ws_path, js)
        elif st.get("eval"):
            _ws_eval(port, ws_path, st["eval"])
        wait_s = float(st.get("wait_sec", 2.0))
        if wait_s > 0:
            time.sleep(wait_s)
    _ws_eval(
        port,
        ws_path,
        "(() => { try { window.scrollTo(0, 0); document.documentElement.scrollTop = 0; document.body.scrollTop = 0; } catch(e){} return 'ok'; })()",
    )


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
