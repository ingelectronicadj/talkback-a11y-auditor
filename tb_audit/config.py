"""Configuración centralizada y agnóstica de aplicación (env vars / config.local.json / --config)."""

import json
import os

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILES_DIR = os.path.join(SCRIPT_DIR, "profiles")
LOCAL_CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.local.json")

TALKBACK_SVC = "com.google.android.marvin.talkback/com.google.android.marvin.talkback.TalkBackService"
TB_PREFS_ACTIVITY = "com.google.android.marvin.talkback/com.android.talkback.TalkBackPreferencesActivity"

ROLE_MAP = {
    "Button": "Botón",
    "ImageButton": "Botón de imagen",
    "EditText": "Campo de edición",
    "TextView": "Texto",
    "ImageView": "Imagen",
    "Switch": "Interruptor",
    "CheckBox": "Casilla de verificación",
    "RadioButton": "Botón de opción",
    "SeekBar": "Control deslizante",
    "Spinner": "Selector",
    "Tab": "Pestaña",
    "RecyclerView": "Lista",
    "ListView": "Lista",
    "View": "Elemento",
    "ComposeView": "Contenedor Compose",
}

INTERESTING_CLS = (
    "EditText", "Switch", "CheckBox", "RadioButton", "SeekBar",
    "ImageView", "ImageButton", "Spinner", "Button", "ProgressBar",
)
SKIP_CLS = (
    "LinearLayout", "FrameLayout", "ViewGroup", "RelativeLayout",
    "ScrollView", "RecyclerView", "ConstraintLayout", "ComposeView",
    "ViewFactoryHolder", "WebView",
)

CURRENCY_NOTES = {
    "$": "el símbolo $ sin desambiguar se anuncia como 'dólares' en síntesis TTS en español aunque represente pesos u otra moneda local",
    "€": "el símbolo € se anuncia como 'euros'",
    "£": "el símbolo £ se anuncia como 'libras'",
}

DEFAULT_CONFIG = {
    "device": os.environ.get("ANDROID_SERIAL", "emulator-5554"),
    "locale": os.environ.get("TB_LOCALE", ""),
    "app_pkg": os.environ.get("TB_APP_PKG", ""),
    "login_url": os.environ.get("TB_LOGIN_URL", ""),
    "sso_url": os.environ.get("TB_SSO_URL", ""),
    "sso_token": os.environ.get("TB_SSO_TOKEN", ""),
    "login_body": {
        "documentType": "service",
        "password": os.environ.get("TB_LOGIN_PASSWORD", ""),
        "passwordPosition": ["*"],
        "userIP": "string",
        "username": os.environ.get("TB_LOGIN_USER", ""),
        "deviceInformation": {
            "deviceUUID": os.environ.get("TB_DEVICE_UUID", "00000000-0000-0000-0000-000000000000"),
            "webDeviceInfo": {
                "version": "Mozilla/5.0"
            },
        },
    },
    "sso_body": {
        "token": os.environ.get("TB_SSO_TOKEN", ""),
        "username": os.environ.get("TB_SSO_USER", ""),
        "coreUserId": os.environ.get("TB_SSO_USER", ""),
        "sessionId": os.environ.get("TB_SSO_SESSION_ID", ""),
        "roles": ["CLIENT"],
        "channel": "MB",
        "tokenTtl": 119,
        "country": os.environ.get("TB_COUNTRY", "AR"),
    },
    "i18n_db_name": os.environ.get("TB_I18N_DB", ""),
    "jira_base_url": os.environ.get("TB_JIRA_BASE_URL", ""),
    "jira_bugs": [],
    "views": {},
    "modal_patterns": [],
    "adb_timeout": int(os.environ.get("TB_ADB_TIMEOUT", "25")),
    "keep_alive_sec": float(os.environ.get("TB_KEEP_ALIVE_SEC", "0")),
}


def _deep_merge(base, override):
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def resolve_profile_path(profile_or_path=None):
    """Resuelve un nombre de perfil (ej. 'app_staging' -> 'profiles/app_staging.local.json')
    o ruta de configuración explícita."""
    if profile_or_path:
        if os.path.exists(profile_or_path):
            return profile_or_path
        cand1 = os.path.join(PROFILES_DIR, "%s.local.json" % profile_or_path)
        if os.path.exists(cand1):
            return cand1
        cand2 = os.path.join(PROFILES_DIR, "%s.json" % profile_or_path)
        if os.path.exists(cand2):
            return cand2
        return profile_or_path
    if os.path.exists(LOCAL_CONFIG_PATH):
        return LOCAL_CONFIG_PATH
    if os.path.isdir(PROFILES_DIR):
        locals_found = sorted(
            os.path.join(PROFILES_DIR, fn)
            for fn in os.listdir(PROFILES_DIR)
            if fn.endswith(".local.json")
        )
        if locals_found:
            return locals_found[0]
    return None


def load_config(config_path=None, user_id=None, core_user_id=None, sso_token=None, app_pkg=None, profile=None):
    """Carga configuración combinando defaults agnósticos, `profiles/<name>.local.json` o `config.local.json`,
    archivo `--config` / `--profile` opcional y argumentos de línea de comandos."""
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    target_cfg = resolve_profile_path(profile or config_path)
    if target_cfg and os.path.exists(target_cfg):
        try:
            with open(target_cfg, "r", encoding="utf-8") as f:
                _deep_merge(cfg, json.load(f))
        except Exception:
            pass
    if app_pkg:
        cfg["app_pkg"] = str(app_pkg).strip()
    if user_id:
        uid = str(user_id).strip()
        cfg["sso_body"]["username"] = uid
        cfg["sso_body"]["coreUserId"] = str(core_user_id or uid).strip()
    elif core_user_id:
        cfg["sso_body"]["coreUserId"] = str(core_user_id).strip()
    if sso_token:
        tok = str(sso_token).strip()
        cfg["sso_token"] = tok
        cfg["sso_body"]["token"] = tok
    return cfg


def role_of(cls):
    short = (cls or "").split(".")[-1]
    for k, v in ROLE_MAP.items():
        if k in short:
            return v
    return short or "?"
