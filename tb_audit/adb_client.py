"""Cliente ADB tipado con timeouts, preflight de emulador y control de TalkBack."""

import os
import re
import socket
import subprocess
import time
import xml.etree.ElementTree as ET
from .config import TALKBACK_SVC, TB_PREFS_ACTIVITY


class AdbClient:
    """Encapsula todas las operaciones sobre adb y el emulador Android."""

    def __init__(self, device="emulator-5554", timeout=25):
        self.device = device
        self.timeout = timeout
        sdk_root = os.environ.get("ANDROID_HOME", os.path.expanduser("~/Library/Android/sdk"))
        self.adb_bin = os.path.join(sdk_root, "platform-tools", "adb")
        self.emulator_bin = os.path.join(sdk_root, "emulator", "emulator")

    def ensure_emulator_running(self, avd_name=None, boot_timeout=120):
        """Si no hay emulador activo en `adb devices`, arranca el AVD automáticamente
        y espera a `sys.boot_completed=1`."""
        out = subprocess.run(
            [self.adb_bin, "devices"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
        ).stdout.decode("utf-8", "replace")
        online = [
            ln.split("\t")[0]
            for ln in out.splitlines()
            if "\tdevice" in ln and not ln.startswith("List")
        ]
        if self.device in online:
            return self.device
        if online and not avd_name:
            self.device = online[0]
            return self.device
        if not avd_name:
            avds = (
                subprocess.run(
                    [self.emulator_bin, "-list-avds"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                    timeout=10,
                )
                .stdout.decode("utf-8", "replace")
                .splitlines()
            )
            avds = [a.strip() for a in avds if a.strip() and not a.startswith("INFO")]
            if not avds:
                raise RuntimeError("No se encontraron AVDs configurados en Android SDK.")
            avd_name = avds[0]
        print("      [emulador] iniciando AVD '%s'..." % avd_name)
        subprocess.Popen(
            [self.emulator_bin, "-avd", avd_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run([self.adb_bin, "wait-for-device"], check=False, timeout=boot_timeout)
        deadline = time.time() + boot_timeout
        while time.time() < deadline:
            b = self.run(["shell", "getprop", "sys.boot_completed"], check=False).strip()
            if b == "1":
                print("      [emulador] listo (%s)" % self.device)
                return self.device
            time.sleep(2)
        raise RuntimeError("Timeout esperando el arranque del emulador '%s'." % avd_name)

    def run(self, args, raw=False, check=True, timeout=None):
        cmd = [self.adb_bin, "-s", self.device] + list(args)
        r = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=check,
            timeout=timeout or self.timeout,
        )
        return r.stdout if raw else r.stdout.decode("utf-8", "replace")

    def preflight_check(self):
        """Verifica conectividad del emulador y devuelve metadatos del entorno (locale, API)."""
        out = subprocess.run(
            [self.adb_bin, "devices"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
        ).stdout.decode("utf-8", "replace")
        online = any(
            ln.startswith(self.device + "\tdevice") for ln in out.splitlines()
        )
        if not online:
            raise RuntimeError(
                "El dispositivo '%s' no aparece online en 'adb devices'." % self.device
            )
        locale = (
            self.run(["shell", "getprop", "persist.sys.locale"], check=False).strip()
            or self.run(["shell", "getprop", "ro.product.locale"], check=False).strip()
            or "desconocido"
        )
        sdk = self.run(["shell", "getprop", "ro.build.version.sdk"], check=False).strip()
        return {"device": self.device, "locale": locale, "sdk": sdk}

    def talkback_on(self):
        self.run(["shell", "settings", "put", "secure", "enabled_accessibility_services", TALKBACK_SVC])
        self.run(["shell", "settings", "put", "secure", "accessibility_enabled", "1"])

    def talkback_off(self):
        self.run(["shell", "settings", "delete", "secure", "enabled_accessibility_services"], check=False)
        self.run(["shell", "settings", "put", "secure", "accessibility_enabled", "0"], check=False)

    def tap(self, x, y):
        self.run(["shell", "input", "tap", str(x), str(y)])

    def dump_nodes(self):
        """Devuelve lista de nodos accesibles en pantalla (dicts con atributos)."""
        self.run(["shell", "uiautomator", "dump", "/sdcard/_tb_audit.xml"], check=False)
        xml = self.run(["shell", "cat", "/sdcard/_tb_audit.xml"], check=False)
        nodes = []
        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            m = re.search(r"<\?xml.*", xml, re.S)
            if m:
                root = ET.fromstring(m.group(0))
            else:
                return nodes
        for el in root.iter("node"):
            b = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", el.get("bounds", ""))
            nodes.append({
                "text": el.get("text", ""),
                "desc": el.get("content-desc", ""),
                "cls": el.get("class", ""),
                "rid": el.get("resource-id", ""),
                "clickable": el.get("clickable") == "true",
                "focusable": el.get("focusable") == "true",
                "checked": el.get("checked", ""),
                "bounds": tuple(map(int, b.groups())) if b else None,
                "pkg": el.get("package", ""),
            })
        return nodes

    def ensure_speech_display(self):
        """Activa 'Display speech output' en TalkBack (captions en pantalla)."""
        cur_svc = self.run(
            ["shell", "settings", "get", "secure", "enabled_accessibility_services"],
            check=False,
        )
        was_on = TALKBACK_SVC in cur_svc
        if was_on:
            self.talkback_off()
            time.sleep(1)
        self.run(["shell", "am", "start", "-n", TB_PREFS_ACTIVITY], check=False)
        ok = False
        for _ in range(3):
            time.sleep(2)
            nodes = self.dump_nodes()
            sw = [n for n in nodes if n["cls"].endswith("Switch") and n["bounds"]]
            target = [n for n in nodes if "speech output" in n["text"].lower()]
            if not (target and sw):
                continue
            ty = (target[0]["bounds"][1] + target[0]["bounds"][3]) // 2
            cand = [
                s for s in sw if abs((s["bounds"][1] + s["bounds"][3]) // 2 - ty) < 120
            ]
            if not cand:
                continue
            s = cand[0]
            if s["checked"] == "true":
                ok = True
                break
            cx, cy = (s["bounds"][0] + s["bounds"][2]) // 2, ty
            self.run(
                ["shell", "input", "swipe", str(cx), str(cy), str(cx + 5), str(cy), "100"]
            )
            time.sleep(1.5)
            nodes = self.dump_nodes()
            sw2 = [
                n for n in nodes if n["cls"].endswith("Switch") and n["bounds"] == s["bounds"]
            ]
            if sw2 and sw2[0]["checked"] == "true":
                ok = True
                break
        if was_on:
            self.talkback_on()
            time.sleep(1.5)
        return ok

    def screencap_png(self, path):
        data = self.run(["exec-out", "screencap", "-p"], raw=True)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def screencap_raw(self):
        """Devuelve (w, h, bytes RGBA) del framebuffer crudo."""
        data = self.run(["exec-out", "screencap"], raw=True)
        for hdr in (16, 12):
            w = int.from_bytes(data[0:4], "little")
            h = int.from_bytes(data[4:8], "little")
            if len(data) - hdr == w * h * 4:
                return w, h, data[hdr:]
        raise RuntimeError("screencap raw: formato inesperado (%d bytes)" % len(data))

    def _emu_port(self):
        m = re.search(r"emulator-(\d+)", self.device or "")
        return int(m.group(1)) if m else 5554

    def emu_swipe(self, backward=False, y=1400, steps=12, dur=0.10):
        """Inyecta un gesto de swipe horizontal real por la consola QEMU del emulador
        (`event mouse <x> <y> 0 1`), que TalkBack procesa como gesto nativo de
        navegación lineal (swipe derecha = siguiente, swipe izquierda = anterior)."""
        x1, x2 = (1100, 250) if backward else (250, 1100)
        token_path = os.path.expanduser("~/.emulator_console_auth_token")
        token = open(token_path).read().strip() if os.path.exists(token_path) else ""
        s = socket.create_connection(("127.0.0.1", self._emu_port()), timeout=5)
        try:
            s.recv(1024)
            if token:
                s.sendall(("auth %s\n" % token).encode())
                s.recv(1024)
            for i in range(steps + 1):
                x = int(x1 + (x2 - x1) * i / steps)
                s.sendall(("event mouse %d %d 0 1\n" % (x, y)).encode())
                s.recv(256)
                time.sleep(dur / steps)
            s.sendall(("event mouse %d %d 0 0\n" % (x2, y)).encode())
            s.recv(256)
        finally:
            s.close()

    def emu_explore_touch(self, x, y):
        """Inyecta un gesto 'Explore by touch' (tocar y deslizar 24px durante ~320ms)
        por la consola QEMU del emulador, moviendo el foco de TalkBack al elemento en
        (x, y) SIN activarlo."""
        token_path = os.path.expanduser("~/.emulator_console_auth_token")
        token = open(token_path).read().strip() if os.path.exists(token_path) else ""
        s = socket.create_connection(("127.0.0.1", self._emu_port()), timeout=5)
        try:
            s.recv(1024)
            if token:
                s.sendall(("auth %s\n" % token).encode())
                s.recv(1024)
            for dx in range(0, 24, 3):
                s.sendall(("event mouse %d %d 0 1\n" % (int(x) + dx, int(y))).encode())
                s.recv(256)
                time.sleep(0.04)
            s.sendall(("event mouse %d %d 0 0\n" % (int(x) + 24, int(y))).encode())
            s.recv(256)
        finally:
            s.close()

    def emu_double_tap(self, x=672, y=1400):
        """Inyecta un doble tap real por la consola QEMU del emulador (activar elemento enfocado en TalkBack)."""
        token_path = os.path.expanduser("~/.emulator_console_auth_token")
        token = open(token_path).read().strip() if os.path.exists(token_path) else ""
        s = socket.create_connection(("127.0.0.1", self._emu_port()), timeout=5)
        try:
            s.recv(1024)
            if token:
                s.sendall(("auth %s\n" % token).encode())
                s.recv(1024)
            for _ in range(2):
                s.sendall(("event mouse %d %d 0 1\n" % (x, y)).encode())
                s.recv(256)
                time.sleep(0.04)
                s.sendall(("event mouse %d %d 0 0\n" % (x, y)).encode())
                s.recv(256)
                time.sleep(0.08)
        finally:
            s.close()

    def nav(self, mode="swipe", backward=False):
        if mode == "swipe":
            self.emu_swipe(backward=backward)
        elif mode == "alt":
            self.run(["shell", "input", "keycombination", "57", "21" if backward else "22"])
        elif mode == "tab":
            if backward:
                self.run(["shell", "input", "keycombination", "59", "61"], check=False)
            else:
                self.run(["shell", "input", "keyevent", "61"])
        else:
            self.run(["shell", "input", "keyevent", "19" if backward else "20"])

    def close_keyboard(self):
        out = self.run(["shell", "dumpsys", "input_method"], check=False)
        if "mInputShown=true" in out:
            self.run(["shell", "input", "keyevent", "111"], check=False)
            time.sleep(0.6)
            out = self.run(["shell", "dumpsys", "input_method"], check=False)
            if "mInputShown=true" in out:
                self.run(["shell", "input", "keyevent", "4"], check=False)
                time.sleep(0.6)

    def set_network_delay(self, delay_ms=0):
        """Aplica latencia de red en el emulador (ms) para poder observar skeletons
        y anuncios 'Cargando {título}' cuando la carga normal es muy rápida."""
        self.run(["emu", "network", "delay", str(int(delay_ms))], check=False)

    def get_foreground_package(self):
        """Devuelve (package_name, activity_name) de la app actualmente visible en primer plano."""
        cur = self.run(["shell", "dumpsys", "activity", "activities"], check=False)
        for pat in (
            r"topResumedActivity=ActivityRecord\{[^}]*\s+([a-zA-Z0-9_.]+)/([a-zA-Z0-9_.$]+)",
            r"mResumedActivity:\s*ActivityRecord\{[^}]*\s+([a-zA-Z0-9_.]+)/([a-zA-Z0-9_.$]+)",
        ):
            m = re.search(pat, cur)
            if m:
                return m.group(1), m.group(2)
        return "", ""

    def list_installed_apps(self):
        """Lista todos los paquetes de usuario (terceros) instalados en el emulador."""
        out = self.run(["shell", "pm", "list", "packages", "-3"], check=False)
        pkgs = []
        for ln in out.splitlines():
            ln = ln.strip()
            if ln.startswith("package:"):
                pkgs.append(ln.split("package:", 1)[1].strip())
        return sorted(pkgs)

    def _extract_apk_package_host(self, apk_path):
        """Intenta extraer el packageName de un archivo .apk usando aapt2/aapt del Android SDK."""
        import glob

        sdk_root = os.environ.get("ANDROID_HOME") or os.path.expanduser("~/Library/Android/sdk")
        for tool in ("aapt2", "aapt"):
            matches = sorted(glob.glob(os.path.join(sdk_root, "build-tools", "*", tool)), reverse=True)
            if matches:
                try:
                    res = subprocess.run(
                        [matches[0], "dump", "badging", apk_path],
                        capture_output=True,
                        text=True,
                        timeout=15,
                    )
                    m = re.search(r"package:\s+name='([^']+)'", res.stdout)
                    if m:
                        return m.group(1)
                except Exception:
                    pass
        return ""

    def install_apk(self, apk_path):
        """Instala un archivo .apk en el emulador y devuelve su packageName detectado."""
        apk_abs = os.path.abspath(os.path.expanduser(apk_path))
        if not os.path.isfile(apk_abs):
            raise RuntimeError("No se encontró el archivo APK: %s" % apk_abs)
        before = set(self.list_installed_apps())
        pkg_hint = self._extract_apk_package_host(apk_abs)
        print("      [apk] instalando %s ..." % os.path.basename(apk_abs))
        subprocess.run(
            [self.adb, "-s", self.device, "install", "-r", apk_abs],
            check=True,
            timeout=180,
        )
        after = set(self.list_installed_apps())
        added = sorted(after - before)
        pkg = pkg_hint or (added[0] if added else "")
        if pkg:
            print("      [apk] instalado correctamente -> paquete: %s" % pkg)
        else:
            print("      [apk] APK instalado (usa --list-apps para ver el paquete)")
        return pkg

    def ensure_app_foreground(self, app_pkg):
        if not app_pkg:
            return
        fg_pkg, _ = self.get_foreground_package()
        if fg_pkg != app_pkg:
            self.run(
                ["shell", "monkey", "-p", app_pkg, "-c", "android.intent.category.LAUNCHER", "1"],
                check=False,
            )
            time.sleep(2)
