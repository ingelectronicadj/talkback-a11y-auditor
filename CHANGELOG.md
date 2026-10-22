# Changelog - TalkBack Audit

Todas las mejoras relevantes de la herramienta de auditoría lineal de accesibilidad con TalkBack se registran en este archivo siguiendo [Keep a Changelog](https://keepachangelog.com/es-ES/1.0.0/) y [Semantic Versioning](https://semver.org/lang/es/).

## [0.3.1] - 2026-10-22

### Añadido
- **Organización multi-app por perfiles (`profiles/<nombre>.local.json`) y flag `--profile` / `-p`**:
  - `resolve_profile_path()` en `tb_audit/config.py` permite organizar múltiples aplicaciones o entornos en `profiles/<app>.local.json` e invocarlos con `--profile <app>` (manteniendo compatibilidad con `--config`).
  - Salida por defecto para corridas sin `--out` movida a `reportes/adhoc/talkback_report_<timestamp>` para mantener limpia la raíz del proyecto.

## [0.3.0] - 2026-10-22

### Añadido
- **Detección de contenido y controles del DOM omitidos por TalkBack (`TB-UNREACH-001` - WCAG 1.3.1 / 2.1.1)**:
  - `analyze_unreachable_elements()` en `tb_audit/rules.py` cruza los elementos semánticos visibles del DOM activo con los anuncios reales de TalkBack, identificando etiquetas omitidas en filas repetidas de listas (`2 de 3`, `3 de 3` sin par de activos) o controles no alcanzados en el barrido, y renderiza la sección **Contenido / Controles del DOM Omitidos por TalkBack** en `report.html`.
- **Mapa de Jerarquía de Encabezados (`Outline H1-H6`) y regla `TB-HEAD-002` (WCAG 1.3.1 / 2.4.6)**:
  - `analyze_heading_hierarchy()` extrae la estructura `H1..H6` del DOM o del barrido nativo, valida la presencia de `<h1>`, detecta saltos de nivel (`H1 -> H3` sin `H2`) y encabezados ocultos (`screen-reader`) con párrafos extensos (`> 120` caracteres), y añade la sección visual **Mapa de Jerarquía de Encabezados** en el reporte HTML.
- **Prueba desatendida de Retorno de Foco en Modales y Drawers (`--test-modals` - `TB-FOCUS-001`)**:
  - En modo automático, al enfocar un botón disparador de modal/tooltip o selector de cuenta, lo activa con doble tap, captura la modal abierta, la cierra (`Cerrar` / `Close` / `BACK`) y evalúa automáticamente si el foco de TalkBack regresó al botón invocador.
- **Generador de Portada Maestra (`index.html`) y empaquetado `.zip` de suite (`--pack [ZIP_FILE]` y automático en `--view all`)**:
  - `build_suite_index()` en `tb_audit/report.py` construye el dashboard `index.html` con tarjetas de resumen para todas las vistas auditadas y genera el archivo `.zip` autocontenido listo para distribuir.

## [0.2.3] - 2026-10-22

### Añadido
- **Cambio automático de idioma del emulador (`--locale` y `"locale"` en el perfil JSON)**:
  - `AdbClient.ensure_locale(target_locale)` verifica el idioma activo de Android (`persist.sys.locale`) y, si difiere del idioma de la app bajo prueba (ej. `en-US` vs `es-AR`), reordena automáticamente el idioma preferido #1 en `LOCALE_SETTINGS` y reinicia TalkBack para limpiar la caché de roles de accesibilidad de Chromium (`heading 1` / `Button` / `link` vs `encabezado 1` / `Botón` / `vínculo`).
- **Selección de socket CDP por PID de la app activa y filtrado de WebViews de analítica (`tb_audit/cdp.py`)**:
  - Cuando coexisten varias aplicaciones con WebViews abiertos en el emulador, `_connect_cdp_ws` resuelve el `PID` del paquete en primer plano (`pidof <fg_pkg>`).
  - Filtra automáticamente WebViews secundarios en segundo plano (como contenedores de telemetría/tag managers `utag/` o `about:blank`) para conectarse siempre al WebView real de la vista.
- **Priorización de diccionarios `IndexedDB` de dominio y auditoría cruzada `en` <-> `es` (`tb_audit/cdp.py`)**:
  - Prioriza almacenes de traducciones de dominio (`> 30 keys`) sobre almacenes de configuración cortos (`CONFIG`) y detecta tanto textos en inglés sin localizar dentro de paquetes `es-*` como textos en español olvidados dentro de paquetes `en-*`.
- **Reglas y automatismos bilingües `es` / `en` (`tb_audit/rules.py`, `talkback_audit.py`)**:
  - Soporte bilingüe en `TB-CHART-001` y `[auto-skip gráfica]` (`Date: ..., Value: ...` y `Fecha: ..., Valor: ...`), avance automático de carruseles (`Next tip` y `Siguiente consejo`), detección de enlaces duplicados en `TB-LINK-001` (`Learn more. Learn more...` y `Saber más. Saber más...`) y evaluación de `TB-LANG-001` / `TB-CURR-001` sensible al idioma esperado de la vista.
- **Auto-cierre de diálogos de sistema tras instalar un `.apk` (`AdbClient.dismiss_system_dialogs`)**:
  - Cierra automáticamente en primer arranque el aviso de compatibilidad de página de 16 KB de Android 15/16 (`No volver a mostrar` / `Don't show again`) y el diálogo de permiso de notificaciones (`Permitir` / `Allow`).

### Corregido
- **Aislamiento de perfiles al usar `--config <archivo.json>` (`tb_audit/config.py`, `tb_audit/report.py`)**:
  - Pasar `--config` ahora carga exclusivamente el archivo indicado sin mezclar claves de `config.local.json`, y propaga el objeto `cfg` a `build_report` y `rebuild_report`.
- **Corrección de atributo `self.adb_bin` en `AdbClient.install_apk` (`tb_audit/adb_client.py`)**.

## [0.2.2] - 2026-10-21

### Añadido
- **Facilitadores de onboarding para cualquier aplicación Android (`talkback_audit.py`, `tb_audit/adb_client.py`)**:
  - `--apk <archivo.apk>`: instala el APK en el emulador (`adb install -r`), extrae automáticamente su `packageName` (vía `aapt2`/`aapt` o diferencial de paquetes), lanza la aplicación y la audita sin necesidad de conocer el nombre del paquete.
  - `--list-apps`: lista numerada de todas las aplicaciones de usuario instaladas en el emulador (`pm list packages -3`), indicando cuál se encuentra actualmente activa en pantalla (`[ACTIVA EN PANTALLA]`).
  - `--init`: asistente interactivo en terminal para elegir una app instalada o instalar un `.apk` y generar/actualizar `config.local.json` automáticamente.
  - **Auto-detección de paquete en primer plano (`get_foreground_package`)**: cuando no se especifica `--pkg` ni existe `config.local.json`, detecta automáticamente la aplicación abierta en pantalla (`topResumedActivity`).

## [0.2.1] - 2026-10-21

### Añadido
- **Perfiles declarativos de navegación a vistas (`--view <id|all>` y `--view-title`)**:
  - Permite declarar en `config.local.json` (`views`) cómo llegar a cada pantalla de cualquier aplicación Android (`start_activity`, `entry_tap` y pasos declarativos `cdp_steps` de tipo `click`, `click_text`, `hash` o `eval`), ejecutando una vista individual (`--view landing`) o toda la suite (`--view all`).
  - Suspende temporalmente TalkBack durante la navegación previa de preparación, captura el árbol nativo y el DOM/IndexedDB en frío sin interferencia del servicio de accesibilidad, y activa TalkBack justo al iniciar el barrido lineal.
- **Identificación automática del título de vista y ruta en el reporte HTML (`tb_audit/report.py`, `tb_audit/cdp.py`)**:
  - Extrae automáticamente el encabezado `<h1>` y el hash/ruta de la vista para mostrarlos en el `<title>` de la pestaña del navegador (facilitando distinguir múltiples reportes abiertos simultáneamente) y en un banner destacado `.view-banner` dentro de la cabecera del reporte.
  - Selectores DOM enriquecidos con el `data-testid` del contenedor padre (`div[data-testid="..."] > p[data-testid="text"]`) cuando el nodo hijo tiene un `data-testid` genérico.
  - Salto instantáneo de gráficas (`[auto-skip gráfica]`) vía CDP tras capturar los primeros 5 puntos (`TB-CHART-001`), permitiendo completar en segundos vistas con series de 30 a 300+ nodos SVG.

## [0.2.0] - 2026-10-21

### Añadido
- **Arquitectura 100% agnóstica de aplicación (`tb_audit/config.py`, `config.example.json`)**:
  - Separación completa entre el motor de auditoría y los perfiles específicos de aplicación (`config.local.json`, ignorado en git).
  - Nuevo flag `--pkg PACKAGE` en CLI para auditar cualquier paquete Android al vuelo.
  - Detección dinámica en `tb_audit/cdp.py` de bases de datos de internacionalización en `IndexedDB` dentro de WebViews híbridos.
- **Rediseño de snippets de código y tarjetas ejecutivas (`tb_audit/report.py`, `tb_audit/wcag_catalog.py`)**:
  - Limpieza automática de clases hash autogeneradas (`styled-components`), `<span>` decorativos vacíos y rutas largas de iconos en los bloques `.dombox`.
  - Formateo multi-línea con sangría de 2 espacios, resaltado de sintaxis HTML/JS y botón **`Copiar HTML`** en cada paso.
  - Opciones de remediación para desarrolladores (**Opción A** y **Opción B**) con ejemplos de código resaltados (`<pre class="code-snip">`) y píldoras `<code class="inl-code">` sin desborde horizontal.
- **Tabla opcional de regresión contra tickets Jira y auditoría de diccionario i18n en memoria (`IndexedDB`)**:
  - Cruza cada elemento DOM con la key de traducción que lo genera e identifica el origen del defecto (`Diccionario i18n` vs `Código del componente`).
- **Desatasco automático de teclado virtual en vistas con `<input>` (`talkback_audit.py`)**:
  - Detecta cuando un campo editable abre el teclado o deja a TalkBack en el anuncio secundario `«Tocar dos veces para activar»`, cierra el teclado y avanza el foco para completar el barrido lineal.
- **Documentación técnica extendida en `docs/`**:
  - `docs/architecture.md`, `docs/wcag-rules-catalog.md`, `docs/configuration-and-profiles.md` y `docs/troubleshooting-talkback-android.md`.

## [0.1.0] - 2026-10-20

### Añadido
- **Inspector técnico DOM / ARIA para WebView por Chrome DevTools Protocol (`tb_audit/cdp.py`)**: conexión automática al socket `webview_devtools_remote_<pid>` del emulador, extracción de nodos DOM (`data-testid`, `id`, `role`, `aria-label`, `aria-labelledby`, `tabindex`, `outerHTML`) y correlación con cada paso del reporte HTML (`.dombox`).

## [0.0.9] - 2026-10-20

### Añadido
- **Navegación lineal 100% automática con gestos reales de TalkBack (`--mode swipe`)**: inyección de eventos táctiles por el socket de consola QEMU del emulador (`127.0.0.1:<port>` → `event mouse`), permitiendo ejecutar `emu_swipe`, `emu_double_tap` y `emu_explore_touch` nativos de TalkBack sin intervención manual.
- **Salto inteligente de gráficas (`[auto-skip gráfica]`) y recorrido automático de carruseles (`[auto-carrusel]`)**: tras capturar los primeros 5 puntos de una gráfica (activando `TB-CHART-001`), el barrido automático salta el resto de los puntos de la serie para auditar toda la vista hasta el final (`No hay más elemento enfocable`), y activa automáticamente el avance en carruseles para auditar todas sus tarjetas.
- **Limpieza de color en `tb_ocr.swift` para la barra de subtítulos**: aplana píxeles no blancos (`RGB < 170`) en la franja del caption de TalkBack para eliminar el texto oscuro de la app que se transparenta detrás.
- **Nuevas reglas en `WCAG_CATALOG`**:
  - `TB-I18N-001` (`WCAG 3.1.2 / 2.4.6` - Internacionalización / i18n): detecta keys crudas sin resolver, textos en inglés dentro de vistas en español, variables sin interpolar (`{placeholder}`) e inconsistencias ortográficas o de voseo.
  - `TB-LINK-001` (`WCAG 2.4.4` - Propósito de los enlaces): detecta enlaces sin destino (`«(Abrir una nueva ventana). vínculo»`) y etiquetas duplicadas (`«Saber más. Saber más...»`).

## [0.0.8] - 2026-10-20

### Añadido
- **Parametrización de usuario para hooks SSO (`--user` / `-u` y `--core-user-id`)** en `talkback_audit.py` y `tb_audit/config.py`.
- **Arranque automático de emulador (`AdbClient.ensure_emulator_running` / `--avd`)**: si no hay ningún emulador activo en `adb devices`, detecta el AVD instalado, lo lanza y espera a `sys.boot_completed=1`.

## [0.0.7] - 2026-10-20

### Añadido
- **Regla `TB-CHART-001` (WCAG 2.4.1 Evitar bloques - Gráficas interactivas)**: detecta cuando TalkBack queda atrapado recorriendo `>= 5` puntos individuales consecutivos de una gráfica (`Fecha: ..., Valor: ...`).
- **Simulación de latencia de red (`--net-delay MS`)**: aplica `adb emu network delay` durante la corrida para observar todos los skeletons y anuncios `«Cargando {título}»`.
- **Filtro geométrico de precisión en `tb_audit/vision.py`**: restringe la lectura del caption a líneas alineadas al borde izquierdo debajo de la cabecera `"TalkBack"`, eliminando texto de fondo.

### Cambiado
- **Rediseño de cabecera y tarjetas de estadísticas (`tb_audit/report.py`)**: contenedor `.hdr-inner` alineado a `1180px`, metadatos en chips (`.meta-chip`) y grilla uniforme de 6 columnas (`.stats`).
- **Proporciones de tabla y filtrado del árbol accesible (`tb_audit/report.py`, `tb_audit/rules.py`)**: `<colgroup>` con anchos fijos y exclusión de contenedores de layout vacíos (`FrameLayout`, `LinearLayout`, `View` no clicable sin texto).

## [0.0.6] - 2026-10-19

### Cambiado
- **Desacoplamiento modular (`tb_audit/`)**: refactorización en un paquete estructurado por responsabilidades (`config.py`, `adb_client.py`, `sso.py`, `vision.py`, `wcag_catalog.py`, `rules.py`, `report.py`), dejando `talkback_audit.py` como entrypoint CLI ligero.
- **Preflight de entorno y modo `--self-test`**: verificación de SDK, detección temprana de `locale` del emulador (`en-US` vs `es-AR`) y autodiagnóstico sin emulador.

## [0.0.5] - 2026-10-19

### Añadido
- **Catálogo taxonómico completo WCAG 2.2 (`WCAG_PRINCIPLES`, `WCAG_GUIDELINES`, `WCAG_CRITERIA` con los 86 criterios A/AA/AAA)**.
- **Detección automática de pantallas/drawers con Skeletons (`ocr_step_info` / `TB-SKEL-001`)**: identifica vistas en estado de carga y verifica si TalkBack anunció `«Cargando {título}»` / `«Loading {title}»`.

## [0.0.4] - 2026-10-19

### Añadido
- **Resumen ejecutivo por criterio WCAG**, **filmstrip interactivo**, **buscador en tiempo real**, **visor Lightbox con teclado** y **modo de impresión PDF (`@media print`)**.

## [0.0.3] - 2026-10-19

### Añadido
- **Keep-alive de sesión en segundo plano (`--keep-alive`)**, **persistencia en `steps.json` (`--rebuild`)** y **heurísticas de secuencia (`Focus Return` y contenedores fusionados)**.

## [0.0.2] - 2026-10-19

### Añadido
- **Modo manual asistido (`--manual`)** con detección de cambio de pantalla por firma de píxeles y hooks opcionales de login.

## [0.0.1] - 2026-10-19

### Añadido
- Activación/desactivación de TalkBack y de **"Display speech output"** vía `adb`, captura única de árbol accesible (`uiautomator dump`) y extracción OCR de utterances mediante `Vision.framework` (`tb_ocr.swift`).
