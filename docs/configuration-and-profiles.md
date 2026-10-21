# Configuración y Perfiles de Aplicación

**TalkBack Audit** está diseñado para funcionar sin configuración previa sobre cualquier aplicación Android, pero permite personalizar el paquete objetivo, la autenticación pre-prueba, la auditoría de diccionarios de internacionalización (`IndexedDB`) y el seguimiento de regresión contra Jira mediante `config.local.json` o variables de entorno.

---

## 1. Orden de Precedencia de Configuración

`tb_audit/config.py` resuelve la configuración en el siguiente orden (de menor a mayor prioridad):

1. **Defaults agnósticos** (`DEFAULT_CONFIG` en `tb_audit/config.py`).
2. **Variables de entorno** (`ANDROID_SERIAL`, `TB_APP_PKG`, `TB_LOGIN_URL`, `TB_SSO_URL`, `TB_SSO_TOKEN`, `TB_SSO_USER`, `TB_JIRA_BASE_URL`, `TB_KEEP_ALIVE_SEC`).
3. **`config.local.json`** en la raíz del proyecto (ignorado por `.gitignore` para que nunca se suban URLs internas, tokens ni IDs de proyectos privados).
4. **Archivo pasado por `--config <ruta.json>`** en la línea de comandos.
5. **Flags explícitos de CLI** (`--pkg`, `--device`, `--user`, `--core-user-id`, `--keep-alive`).

---

## 2. Escenarios de Uso

### Escenario A: Aplicación Android estándar o nuevo `.apk` (sin configuración previa)

No necesitas conocer de memoria el `packageName` ni crear archivos de configuración:

```bash
# 1. Si tienes un archivo .apk nuevo: lo instala, detecta el paquete, lo abre y ejecuta la auditoría
python3 talkback_audit.py --apk ~/Downloads/nueva_app.apk --out reportes/home

# 2. Si la app ya está instalada en el emulador y quieres ver su nombre o cuál está abierta:
python3 talkback_audit.py --list-apps

# 3. Si ya tienes la app abierta en la pantalla que deseas auditar (auto-detecta el paquete en pantalla):
python3 talkback_audit.py --no-setup --view-title "Transferencias - Paso 1" --out reportes/transferencias

# 4. O usa el asistente interactivo para guardar la app elegida en config.local.json:
python3 talkback_audit.py --init
```

### Escenario B: Aplicación con WebView Híbrido e Internacionalización en `IndexedDB`

Si la aplicación renderiza vistas en un `WebView` con `WebView.setWebContentsDebuggingEnabled(true)`:

- `tb_audit/cdp.py` detecta automáticamente el socket `webview_devtools_remote_<pid>` sin configuración adicional.
- Recorre todas las bases de datos `IndexedDB` del WebView buscando almacenes con entradas de traducción (`translations.entries`), audita las keys cargadas en memoria y cruza cada nodo DOM con la key que lo produjo.

### Escenario C: Aplicación con Login SSO / Keep-Alive y Seguimiento de Bugs en Jira

Copia `config.example.json` a `config.local.json` (que está incluido en `.gitignore`) y define los campos de tu entorno:

```json
{
  "device": "emulator-5554",
  "app_pkg": "com.miempresa.app.pre",
  "keep_alive_sec": 85,
  "adb_timeout": 25,
  "login_url": "https://auth.internal.example/auth/login",
  "sso_url": "https://sso.internal.example/v1/sso",
  "sso_token": "dev-sso-token",
  "login_body": {
    "documentType": "service",
    "username": "qa-service-user",
    "password": "<TU_PASSWORD_LOCAL>"
  },
  "sso_body": {
    "token": "dev-sso-token",
    "username": "10020030",
    "coreUserId": "10020030",
    "channel": "MB",
    "tokenTtl": 119,
    "country": "AR"
  },
  "jira_base_url": "https://mi-organizacion.atlassian.net",
  "jira_bugs": [
    {
      "key": "PROJ-101",
      "epic": "EPIC-10",
      "rule_id": "TB-CHART-001 / TB-IMG-001",
      "fix_type": "Código React (LineChart)",
      "summary": "Gráfica expone puntos individuales al barrido lineal",
      "views": "Home & Detalle"
    }
  ]
}
```

Con `config.local.json` presente:
- `--login` ejecuta automáticamente el flujo de autenticación y carga el token en la pantalla de login de desarrollo.
- `--refresh` y `--keep-alive` renuevan la sesión en segundo plano para evitar que caduque el token durante pruebas largas.
- El reporte HTML incluye automáticamente la sección **"Estado de Regresión - Bugs Jira configurados"** y muestra las insignias de cada ticket en las tarjetas del resumen ejecutivo WCAG.
