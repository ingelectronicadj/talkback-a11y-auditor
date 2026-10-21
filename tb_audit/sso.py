"""Autenticación SSO opcional pre-prueba y renovación automática en background."""

import json
import re
import threading
import time
import urllib.request


def _post(url, body, headers=None):
    h = {"content-type": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers=h, method="POST"
    )
    return urllib.request.urlopen(req, timeout=20).read()


def refresh_session(cfg, quiet=False):
    """Ejecuta los 2 POSTs de autenticación (login + SSO) para refrescar la sesión en backend."""
    access = json.loads(_post(cfg["login_url"], cfg["login_body"]))["accessToken"]
    _post(cfg["sso_url"], cfg["sso_body"], {"accesstoken": access})
    if not quiet:
        u = cfg["sso_body"].get("username", "?")
        c = cfg["sso_body"].get("coreUserId", "?")
        print("      sesión SSO refrescada (username=%s, coreUserId=%s)" % (u, c))


def start_keep_alive(cfg, interval_sec):
    """Hilo daemon que renueva la sesión SSO cada `interval_sec` segundos."""
    stop_evt = threading.Event()

    def _worker():
        while not stop_evt.wait(interval_sec):
            try:
                refresh_session(cfg, quiet=True)
                print("      [keep-alive] sesión SSO renovada en background")
            except Exception as e:
                print("      [keep-alive] aviso: falló refresh (%s)" % e)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return stop_evt


def login_flow(adb_client, cfg):
    """Registra la sesión SSO en backend e introduce el token en la actividad de login de desarrollo."""
    app_pkg = cfg["app_pkg"]
    sso_token = cfg["sso_token"]
    adb_client.talkback_off()
    refresh_session(cfg, quiet=True)
    print("      sesión SSO registrada; lanzando app...")
    adb_client.run(["shell", "am", "force-stop", app_pkg], check=False)
    adb_client.run(
        ["shell", "monkey", "-p", app_pkg, "-c", "android.intent.category.LAUNCHER", "1"],
        check=False,
    )
    edit = []
    for _ in range(15):
        time.sleep(1)
        nodes = adb_client.dump_nodes()
        edit = [n for n in nodes if n["cls"].endswith("EditText") and n["bounds"]]
        if edit:
            break
    if not edit:
        print("      AVISO: no se encontró el campo de token")
        return
    b = edit[0]["bounds"]
    adb_client.tap((b[0] + b[2]) // 2, (b[1] + b[3]) // 2)
    time.sleep(1)
    for _ in range(2):
        adb_client.run(["shell", "input", "text", sso_token])
        time.sleep(0.5)
        nodes = adb_client.dump_nodes()
        filled = [n for n in nodes if n["cls"].endswith("EditText")]
        if filled and filled[0]["text"].strip() == sso_token:
            break
        adb_client.run(["shell", "input", "keycombination", "113", "29"], check=False)
        time.sleep(0.3)
        adb_client.run(["shell", "input", "keyevent", "67"], check=False)
        time.sleep(0.3)
    adb_client.close_keyboard()
    time.sleep(0.8)
    nodes = adb_client.dump_nodes()
    login = [n for n in nodes if n["bounds"] and n["text"].strip().lower() == "login"]
    if login:
        b = login[0]["bounds"]
        adb_client.tap((b[0] + b[2]) // 2, (b[1] + b[3]) // 2)
        time.sleep(4)
    else:
        print("      AVISO: botón Login no encontrado")
    cur = adb_client.run(["shell", "dumpsys", "activity", "activities"], check=False)
    m = re.search(r"topResumedActivity=.*?([\w.]+Activity)", cur)
    print("      tras login -> %s" % (m.group(1) if m else "?"))
