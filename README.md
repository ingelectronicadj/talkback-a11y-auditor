# TalkBack Audit (`v0.3.0`)

Herramienta de auditoría lineal de accesibilidad para **Android TalkBack** sobre emuladores Android - equivalente a **NVDA Speech Viewer / Accessibility Insights** para aplicaciones **nativas (Android Views), Jetpack Compose e híbridas (WebView)**.

Automatiza o asiste el recorrido lineal con TalkBack, captura la imagen y el anuncio hablado real de cada paso desde la barra oficial de subtítulos de TalkBack (`Display speech output`), inspecciona en vivo el árbol DOM / ARIA e `IndexedDB` de WebViews mediante **Chrome DevTools Protocol (CDP)**, evalúa **16 reglas de accesibilidad (`TB-*`) mapeadas a los 86 criterios oficiales de WCAG 2.2 (A / AA / AAA)** y genera un reporte ejecutivo interactivo (`report.html` + `steps.json` + portada maestra `index.html`).

---

## Características principales

- **Agnóstico de aplicación y tecnología UI**: funciona con cualquier aplicación Android (`Views`, `Jetpack Compose` o `WebView` híbrida) sin requerir instrumentación en el código fuente de la app.
- **Navegación lineal 100% automática (`--mode swipe`) o manual asistida (`--manual`)**:
  - Inyecta gestos táctiles reales de TalkBack a través del socket de consola QEMU del emulador (`event mouse`), evitando la limitación de Android donde `adb shell input swipe` es ignorado por el servicio de accesibilidad.
  - Detecta el final de la pantalla (`No hay más elemento enfocable` / `No next focusable item`), cierra automáticamente teclados virtuales (`Gboard`) cuando un `<input>` atrapa el foco, avanza carruseles y salta series largas de puntos en gráficas tras registrar el hallazgo.
- **Captura fiel de la voz de TalkBack (macOS `Vision.framework`)**:
  - Compila automáticamente `tb_ocr.swift` y filtra a nivel de píxel la barra inferior de subtítulos de TalkBack para extraer exactamente lo que el lector verbaliza.
- **Inspector técnico de WebView por Chrome DevTools Protocol (`tb_audit/cdp.py`)**:
  - Si la pantalla contiene un WebView debuggable (`webview_devtools_remote_<pid>`), extrae automáticamente los selectores HTML, atributos ARIA (`role`, `aria-label`, `aria-labelledby`, `aria-hidden`, `tabindex`), el snippet HTML limpio con resaltado de sintaxis y el diccionario de internacionalización (`IndexedDB`) para distinguir si un defecto proviene del diccionario de traducciones o del componente UI.
- **Catálogo taxonómico completo WCAG 2.2 (`tb_audit/wcag_catalog.py`)**:
  - Incluye los **86 criterios oficiales WCAG 2.2** y **14 reglas especializadas `TB-*`** con severidad, principio, pauta, nivel, técnicas W3C, comparativa *Experiencia actual vs Comportamiento esperado* y **Opciones de remediación A / B con ejemplos de código**.

---

## Requisitos

- **macOS** (con Command Line Tools de Xcode para `swiftc` y `Vision.framework`; si no está disponible, funciona en modo degradado usando las etiquetas del árbol de `uiautomator`).
- **Python 3.9+** (usa únicamente la biblioteca estándar de Python; cero dependencias `pip` externas).
- **Android SDK Platform-Tools (`adb`)** y **Android Emulator** con Google TalkBack instalado (Android Automotive / Google Play / System Image con Android Accessibility Suite).

---

## Instalación y Uso Rápido

```bash
# 1. Clonar el repositorio y entrar al directorio
git clone https://github.com/ingelectronicadj/talkback-a11y-auditor.git
cd talkback-a11y-auditor

# 2. Verificar versión y ejecutar el autodiagnóstico interno (no requiere emulador)
python3 talkback_audit.py --version
python3 talkback_audit.py --self-test

# 3. (Opcional) Crear configuración local a partir de la plantilla
cp config.example.json config.local.json
```

### Auditar cualquier aplicación Android

```bash
# Opción A: Instalar un archivo .apk nuevo y auditarlo directamente (detecta su packageName solo)
python3 talkback_audit.py --apk ~/Downloads/mi_app.apk --out reportes/mi_vista

# Opción B: Ver qué apps están instaladas en el emulador (marca cuál está activa en pantalla)
python3 talkback_audit.py --list-apps

# Opción C: Asistente interactivo para elegir app o instalar .apk y crear config.local.json
python3 talkback_audit.py --init

# 1. Levantar emulador (si está apagado), activar TalkBack + subtítulos y enfocar la app
python3 talkback_audit.py --pkg com.example.myapp --setup-only

# 2. Ejecutar barrido lineal automático sobre la app que ya tienes abierta en pantalla
python3 talkback_audit.py --no-setup --view-title "Home - Mi App" --out reportes/mi_vista

# 3. Ejecutar auditoría en modo manual asistido (el evaluador navega y el script graba cada foco)
python3 talkback_audit.py --no-setup --manual --idle 120 --out reportes/flujo_manual

# 4. Regenerar el reporte HTML de una corrida previa (re-aplicando reglas y formato sin re-ejecutar el emulador)
python3 talkback_audit.py --rebuild reportes/mi_vista

# 5. Desactivar TalkBack al finalizar
python3 talkback_audit.py --stop-talkback --setup-only
```

---

## Opciones de Línea de Comandos (CLI)

| Opción | Descripción | Valor por defecto |
|---|---|---|
| `--version` | Muestra la versión instalada y termina | - |
| `--self-test` | Valida sin emulador los 86 criterios WCAG 2.2, las 14 reglas `TB-*` y el generador HTML | - |
| `--list-apps` | Lista todas las apps de usuario instaladas en el emulador y marca cuál está activa en pantalla | - |
| `--apk APK_FILE` | Instala un archivo `.apk` en el emulador, extrae su `packageName` y lo abre para auditarlo | - |
| `--init` | Asistente interactivo para elegir una app instalada o instalar un `.apk` y guardar `config.local.json` | - |
| `--pkg PACKAGE` | Paquete Android de la aplicación bajo prueba (si se omite, detecta la app en primer plano) | Auto / Config |
| `--locale BCP47` | Cambia automáticamente el idioma del emulador y reinicia TalkBack antes de auditar (ej. `es-AR`, `en-US`) | Según perfil |
| `--view VIEW_ID` | Ejecuta el perfil declarativo de una vista (`config['views'][VIEW_ID]`) o `all` para correr todas en secuencia | - |
| `--view-title TITLE` | Título descriptivo de la vista para el `<title>` de pestaña y el banner de cabecera del reporte | Auto (`<h1>`) |
| `--device SERIAL` | Serial ADB del dispositivo o emulador (`ANDROID_SERIAL`) | `emulator-5554` |
| `--avd NAME` | Nombre del AVD a iniciar automáticamente si no hay emulador activo | Primer AVD detectado |
| `--config FILE` | Archivo JSON de configuración personalizada | `config.local.json` |
| `--mode {swipe,alt,tab,dpad}` | Modo de avance: `swipe` (gesto nativo TalkBack vía QEMU), `alt` (`Alt+→`), `tab` (`Tab`), `dpad` (`↓`) | `swipe` |
| `--steps N` | Número máximo de pasos en barrido automático | `80` |
| `--delay SECS` | Espera entre pasos para permitir que TalkBack actualice foco y subtítulo | `1.4` |
| `--manual` | Modo manual asistido (captura cada cambio de foco o acepta comandos en consola `n/p/t/T/e/q`) | `False` |
| `--idle SECS` | Segundos sin cambios para finalizar automáticamente en modo `--manual` | `10` |
| `--net-delay MS` | Simula latencia de red (`adb emu network delay`) para auditar estados de carga y skeletons | `0` |
| `--login` / `--refresh` | Ejecuta flujo de autenticación pre-auditoría si está configurado en `config.local.json` | `False` |
| `--keep-alive SECS` | Intervalo de renovación de sesión en segundo plano (`0` para desactivar) | Segun config |
| `--setup-only` | Configura TalkBack y subtítulos y termina sin iniciar barrido | `False` |
| `--no-setup` | Omite el reinicio de TalkBack cuando ya está activo en la pantalla objetivo | `False` |
| `--stop-talkback` | Desactiva TalkBack al terminar | `False` |
| `--test-modals` | En modo automático, abre y cierra modales/drawers detectados para validar `Focus Return` (`TB-FOCUS-001`) | `False` |
| `--pack [ZIP_FILE]` | Genera portada maestra `index.html` y empaqueta la suite de reportes en un archivo `.zip` autocontenido | - |
| `--rebuild DIR` | Reconstruye `report.html` a partir de `steps.json` y las capturas de `DIR/img/` | - |

---

## Arquitectura del Proyecto

```text
.
├── talkback_audit.py          # Entrypoint CLI, orquestador de barrido y modo --self-test
├── tb_ocr.swift               # OCR nativo sobre Vision.framework con filtro de píxeles para subtítulos
├── config.example.json        # Plantilla de configuración (copiar a config.local.json)
├── CHANGELOG.md               # Historial de cambios por versión
├── tb_audit/
│   ├── __init__.py            # Versión del paquete (VERSION = "0.2.0")
│   ├── config.py              # Carga de configuración jerárquica (defaults -> config.local.json -> CLI)
│   ├── adb_client.py          # Cliente ADB, arranque de AVD, preflight y gestos QEMU (emu_swipe)
│   ├── vision.py              # Detección de foco verde, barra de subtítulos, skeletons y OCR
│   ├── cdp.py                 # Inspector WebView DOM / ARIA e IndexedDB vía Chrome DevTools Protocol
│   ├── wcag_catalog.py        # Taxonomía oficial WCAG 2.2 (86 criterios) y catálogo de 14 reglas TB-*
│   ├── rules.py               # Motor de heurísticas por nodo, texto y secuencia (Focus Return, Charts)
│   ├── report.py              # Generador de steps.json y reporte HTML interactivo con snippets limpios
│   └── sso.py                 # Hook opcional de autenticación pre-prueba y keep-alive en background
└── docs/
    ├── architecture.md                # Arquitectura interna, gestos QEMU, OCR y conexión CDP
    ├── wcag-rules-catalog.md          # Catálogo detallado de las 14 reglas TB-* y criterios WCAG 2.2
    ├── configuration-and-profiles.md  # Configuración para cualquier app, WebViews, i18n y Jira
    └── troubleshooting-talkback-android.md # Guía de resolución de problemas con TalkBack en emuladores
```

---

## Documentación adicional (`docs/`)

1. **[Arquitectura y Funcionamiento Interno](docs/architecture.md)**: por qué `uiautomator dump` se ejecuta una sola vez, cómo se inyectan gestos nativos de TalkBack por el socket QEMU, cómo filtra `tb_ocr.swift` los subtítulos y cómo se conecta `cdp.py` al WebView.
2. **[Catálogo de Reglas `TB-*` y Taxonomía WCAG 2.2](docs/wcag-rules-catalog.md)**: detalle de las 14 reglas automatizadas (`TB-SKEL-001` a `TB-LANG-001`) y sus patrones de remediación en Android Views, Jetpack Compose y WebView/React.
3. **[Configuración y Perfiles de Aplicación](docs/configuration-and-profiles.md)**: cómo configurar `config.local.json` o variables de entorno para auditar apps nativas o híbridas, auditar diccionarios i18n en `IndexedDB` y activar la tabla opcional de regresión contra Jira.
4. **[Guía de Troubleshooting de TalkBack en Android Emulator](docs/troubleshooting-talkback-android.md)**: configuración de idioma (`es-AR` / `es-ES`), activación de `Display speech output`, manejo de teclado numérico y WebViews.
