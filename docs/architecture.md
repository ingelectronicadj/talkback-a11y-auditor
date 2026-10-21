# Arquitectura y Funcionamiento Interno

Este documento describe las decisiones técnicas de diseño de **TalkBack Audit** para lograr barridos lineales deterministas, captura fiel de voz de TalkBack e inspección profunda de componentes nativos (`Views` / `Jetpack Compose`) e híbridos (`WebView`).

---

## 1. El problema de automatizar TalkBack en Android

Automatizar pruebas reales con **Google TalkBack** sobre Android presenta tres obstáculos técnicos conocidos:

1. **`adb shell input swipe` es ignorado por TalkBack**:
   Cuando TalkBack activa el modo *Explore by Touch* (`TouchExploration`), el `AccessibilityManagerService` intercepta eventos táctiles de hardware antes de que lleguen a la vista, pero ignora los eventos sintéticos inyectados por `adb shell input swipe` o `adb shell input tap` salvo que provengan del dispositivo táctil del kernel (`/dev/input/event*`).
2. **`uiautomator dump` reinicia el foco de accesibilidad en WebViews y Compose**:
   Ejecutar `adb shell uiautomator dump` en cada paso provoca que `UiAutomation` se conecte al `AccessibilityInteractionClient` y fuerce un re-cálculo del árbol accesible, lo que en contenedores `WebView` y `ComposeView` devuelve el cursor de TalkBack al primer nodo de la pantalla.
3. **TalkBack no expone un API público de Speech History**:
   A diferencia de NVDA Speech Viewer en Windows, Android no expone por `adb` un stream de texto con la frase exacta que TalkBack acaba de enviar al motor TTS (`TextToSpeech`), especialmente cuando TalkBack combina `aria-label`, estado (`seleccionado`, `Inhabilitado`), posición en lista (`1 de 4. En la lista`) y rol localizado (`Botón`, `encabezado 2`, `vínculo`).

---

## 2. Cómo los resuelve TalkBack Audit

### A. Inyección de gestos nativos vía Consola QEMU (`tb_audit/adb_client.py`)

En lugar de `adb shell input swipe`, `AdbClient` se conecta por TCP al socket de consola del emulador QEMU (`127.0.0.1:5554`, autenticando con `~/.emulator_console_auth_token`) y emite comandos `event mouse <x> <y> 0 <button>`:

- **`emu_swipe(backward=False)`**: interpola 12 puntos horizontales en `100 ms` a través del dispositivo puntero virtual de QEMU. Android lo recibe como un gesto físico real de un dedo y TalkBack avanza (swipe derecha) o retrocede (swipe izquierda) al siguiente nodo accesible.
- **`emu_explore_touch(x, y)`**: mantiene pulsado durante `~320 ms` con un micro-deslizamiento de `24 px` para colocar el foco de TalkBack sobre una coordenada específica (por ejemplo, el título `<h1>` superior) sin activar ningún botón.
- **`emu_double_tap()`**: envía dos toques rápidos (`40 ms`) para activar el elemento actualmente enfocado por TalkBack (por ejemplo, para avanzar un carrusel).

### B. Captura única del árbol nativo + lectura visual de framebuffer (`tb_audit/vision.py`)

- `uiautomator dump` se ejecuta **una única vez al inicio** de la corrida (`nodes0`) antes de comenzar el barrido lineal.
- En cada paso posterior solo se captura el framebuffer RGBA (`adb exec-out screencap`), localizando en memoria:
  - El **recuadro verde de foco de TalkBack** (`find_focus_box`: píxeles con `G > 150` y `G > R + 45`, `G > B + 45`).
  - La **franja oscura de subtítulos de TalkBack** (`find_caption_bar`: banda horizontal inferior con luminancia uniforme oscura).
  - La **firma visual de pantalla** (`screen_sig` 8×12) para detectar transiciones de pantalla o apertura de modales.

### C. Extracción OCR con filtro de color en `Vision.framework` (`tb_ocr.swift`)

La opción oficial de desarrollador de TalkBack **"Display speech output"** (*Mostrar salida de voz*) dibuja en la parte inferior de la pantalla una ventana semitransparente con el texto exacto enviado al motor TTS.

Para evitar que el OCR lea texto oscuro de la aplicación que se transparenta detrás del banner de TalkBack:

1. `tb_ocr.swift` (compilado a código nativo con `swiftc -O`) inspecciona la región inferior (`y >= 0.82` en coordenadas de pantalla).
2. Todo píxel que no sea texto blanco brillante (`R < 170 || G < 170 || B < 170`) se aplana a gris oscuro uniforme (`RGB = 45, 45, 45`) antes de invocar `VNRecognizeTextRequest` (`level = .accurate`, `languages = ["es-ES", "es-MX", "en-US"]`).
3. `tb_audit/vision.py` (`ocr_step_info`) filtra además por alineación izquierda (`x <= 0.75`) debajo de la cabecera `"TalkBack"`, eliminando botones o importes de fondo y detectando simultáneamente si el cuerpo central de la vista está en estado **Skeleton** (`is_skeleton`).

### D. Inspección DOM / ARIA e `IndexedDB` vía Chrome DevTools Protocol (`tb_audit/cdp.py`)

Cuando la aplicación bajo prueba contiene un `WebView` con depuración habilitada:

1. `capture_webview_dom()` localiza el socket abstracto `webview_devtools_remote_<pid>` en `/proc/net/unix` y lo reenvía a `127.0.0.1:9222` con `adb forward`.
2. Abre una conexión WebSocket directa (RFC 6455 sobre `socket` estándar de Python, sin librerías externas) y evalúa `DOM_EXTRACT_JS` con `awaitPromise: true`.
3. Extrae:
   - Todos los elementos semánticos e interactivos (`h1..h4`, `button`, `a`, `input`, `svg`, `img`, `circle`, `dt`, `dd`, `[role]`, `[aria-label]`, `[aria-labelledby]`, `[aria-live]`, `[data-testid]`).
   - El diccionario de internacionalización almacenado en `IndexedDB` (si existe), auditando automáticamente todas las keys cargadas en memoria (keys vacías, textos en inglés dentro de paquetes en español, placeholders sin interpolar y errores ortográficos) y cruzando cada nodo DOM con la key exacta que lo produjo.
4. `tb_audit/report.py` limpia el `outerHTML` de cada nodo (eliminando clases hash autogeneradas de `styled-components` y `<span>` decorativos vacíos), lo formatea con sangría de 2 espacios y aplica resaltado de sintaxis.
