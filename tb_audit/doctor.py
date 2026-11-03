"""Preflight del entorno (--doctor) y diagnóstico de red para SSO/CDN."""

import os
import re
import socket
import subprocess
import sys
from urllib.parse import urlparse

from . import VERSION
from .adb_client import find_sdk_root, sdk_bin
from .vision import ensure_ocr_binary


def probe_host(url, timeout=5):
    """TCP probe al host:puerto de `url`. Devuelve (ok, detalle)."""
    p = urlparse(url if "://" in url else "https://" + url)
    host = p.hostname or url
    port = p.port or (443 if p.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, "conecta"
    except socket.gaierror:
        return False, "%s no resuelve DNS" % host
    except (socket.timeout, TimeoutError):
        return False, "%s:%d timeout" % (host, port)
    except ConnectionRefusedError:
        return False, "%s:%d conexión rechazada" % (host, port)
    except OSError as e:
        return False, "%s: %s" % (host, e)


def net_hint(url):
    """Pista accionable según el dominio que falló."""
    host = urlparse(url if "://" in url else "https://" + url).hostname or ""
    if ".corp" in host or ".sar." in host or host.endswith(".internal"):
        return "dominio interno -> requiere VPN corporativa activa"
    return "revisa conectividad de red / VPN"


def check_sso_endpoints(cfg, timeout=5):
    """Sondea los endpoints del perfil y devuelve los inalcanzables como
    lista de (key, url, detalle_fallo)."""
    bad = []
    for key in ("login_url", "sso_url", "hybrid_cdn_url"):
        url = (cfg or {}).get(key, "")
        if not url:
            continue
        ok, det = probe_host(url, timeout=timeout)
        if not ok:
            bad.append((key, url, det))
    return bad


def friendly_net_error(e, url):
    """Traduce errores urllib/socket a una causa accionable."""
    import urllib.error

    host = urlparse(url).hostname or url
    reason = getattr(e, "reason", e)
    if isinstance(reason, socket.gaierror):
        return "%s no resuelve DNS -> %s" % (host, net_hint(url))
    if isinstance(reason, (socket.timeout, TimeoutError)) or "timed out" in str(reason):
        return "timeout conectando a %s -> %s" % (host, net_hint(url))
    if isinstance(reason, ConnectionRefusedError):
        return "%s rechazó la conexión -> ¿servicio caído o puerto erróneo?" % host
    if isinstance(e, urllib.error.HTTPError):
        return "HTTP %s de %s -> revisa credenciales/token SSO" % (e.code, host)
    return str(e)


def run_doctor(cfg, adb_client=None):
    """Preflight completo del entorno. Imprime [OK]/[WARN]/[FAIL] y devuelve
    el número de fallos (0 = entorno listo)."""
    fails = [0]
    warns = [0]

    def ok(m):
        print("  [OK]   %s" % m)

    def warn(m):
        warns[0] += 1
        print("  [WARN] %s" % m)

    def fail(m):
        fails[0] += 1
        print("  [FAIL] %s" % m)

    print("=== Doctor TalkBack Audit v%s ===\n" % VERSION)

    print("Anfitrión")
    vi = sys.version_info
    if vi >= (3, 9):
        ok("Python %d.%d.%d" % vi[:3])
    else:
        fail("Python %d.%d -> requiere >= 3.9" % vi[:2])

    sdk = find_sdk_root()
    if os.path.isdir(sdk):
        ok("Android SDK: %s" % sdk)
    else:
        warn("Android SDK no encontrado en %s -> fija ANDROID_HOME" % sdk)

    adb = adb_client.adb_bin if adb_client else sdk_bin(sdk, "platform-tools", "adb")
    adb_ok = False
    try:
        v = subprocess.run(
            [adb, "version"], capture_output=True, text=True, timeout=10
        )
        line = (v.stdout.splitlines() or ["adb"])[0].strip()
        ok("adb: %s (%s)" % (line, adb))
        adb_ok = True
    except Exception as e:
        fail("adb no ejecutable (%s): %s" % (adb, e))

    ocr_cmd = ensure_ocr_binary()
    if ocr_cmd:
        engine = "Windows.Media.Ocr (tb_ocr.ps1)" if sys.platform == "win32" else "Vision (tb_ocr)"
        ok("OCR: %s" % engine)
    else:
        warn("OCR no disponible -> el reporte caerá a modo degradado (solo árbol uiautomator)")

    print("\nEmulador Android")
    online = []
    if adb_ok:
        try:
            out = subprocess.run(
                [adb, "devices"], capture_output=True, timeout=10
            ).stdout.decode("utf-8", "replace")
            online = [
                ln.split("\t")[0]
                for ln in out.splitlines()
                if "\tdevice" in ln and not ln.startswith("List")
            ]
        except Exception:
            pass
    if not online:
        warn("ningún dispositivo online en 'adb devices' -> arranca el AVD o pasa --avd")
    else:
        dev = (
            adb_client.device
            if adb_client and adb_client.device in online
            else online[0]
        )
        ok("dispositivo online: %s" % dev)

        def sh(args):
            return subprocess.run(
                [adb, "-s", dev, "shell"] + args,
                capture_output=True,
                timeout=15,
            ).stdout.decode("utf-8", "replace")

        size = sh(["wm", "size"])
        m = re.search(r"(\d+)x(\d+)", size)
        if m:
            w, h = int(m.group(1)), int(m.group(2))
            bad_taps = [
                (vid, t)
                for vid, v in (cfg.get("views") or {}).items()
                for t in [v.get("entry_tap")]
                if t and (t[0] > w or t[1] > h)
            ]
            if bad_taps:
                warn(
                    "resolución %dx%d incompatible con entry_tap de %s -> ajusta coords en el perfil"
                    % (w, h, ", ".join(v for v, _ in bad_taps))
                )
            else:
                ok("resolución %dx%d compatible con entry_tap del perfil" % (w, h))

        app_pkg = (cfg.get("app_pkg") or "").strip()
        if app_pkg:
            pkgs = sh(["pm", "list", "packages"])
            if app_pkg in pkgs:
                ok("app instalada: %s" % app_pkg)
            else:
                fail(
                    "app %s NO instalada -> instala con: talkback_audit.py --apk <archivo>.apk"
                    % app_pkg
                )
        else:
            warn("sin 'app_pkg' en el perfil -> el doctor no puede verificar la app")

        acc = sh(["dumpsys", "accessibility"])
        if "talkback" in acc.lower():
            ok("TalkBack instalado en el dispositivo")
        else:
            warn(
                "TalkBack no aparece en 'dumpsys accessibility' -> instala Android Accessibility Suite"
            )

    print("\nRed / endpoints del perfil")
    eps = [
        (k, cfg.get(k))
        for k in ("login_url", "sso_url", "hybrid_cdn_url")
        if cfg.get(k)
    ]
    if not eps:
        warn("el perfil no define login_url/sso_url/hybrid_cdn_url (sin SSO/CDN)")
    for key, url in eps:
        okp, det = probe_host(url)
        host = urlparse(url).hostname or url
        if okp:
            ok("%s (%s): conecta" % (host, key))
        else:
            fail("%s (%s): %s -> %s" % (host, key, det, net_hint(url)))

    sso_ready = bool(cfg.get("login_url") and cfg.get("sso_url") and cfg.get("sso_body"))
    if cfg.get("login_url") and not sso_ready:
        warn("login_url definido pero falta sso_url/sso_body -> --login fallará")

    print(
        "\nResultado: %d fallo(s), %d aviso(s)"
        % (fails[0], warns[0])
    )
    return fails[0]
