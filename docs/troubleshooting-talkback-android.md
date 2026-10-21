# Guía de Troubleshooting: TalkBack en Android Emulator

Esta guía reúne las soluciones a los problemas más frecuentes al auditar accesibilidad con **TalkBack** sobre emuladores Android.

---

## 1. TalkBack anuncia roles en inglés (`Button`, `Heading`, `Link`) en una app en español

- **Causa**: el idioma del sistema del emulador Android está configurado en `en-US` (valor por defecto al crear un AVD nuevo). TalkBack toma el idioma de los roles del sistema (`Botón`, `encabezado 2`, `vínculo`, `Inhabilitado`) del locale activo de Android.
- **Detección**: `talkback_audit.py` ejecuta `preflight_check()` al arrancar y muestra un aviso en consola si detecta `en-*`, además de activar la regla `TB-LANG-001`.
- **Solución**:
  1. En el emulador, abrir **Settings > System > Languages & input > Languages** (*Ajustes > Sistema > Idiomas*).
  2. Añadir **Español (Argentina)** (`es-AR`) o **Español (España)** (`es-ES`) y arrastrarlo a la **posición #1**.
  3. Verificar por terminal:
     ```bash
     adb shell getprop persist.sys.locale
     # Debe devolver: es-AR o es-ES
     ```

---

## 2. No aparece la barra inferior de subtítulos de TalkBack (`Display speech output`)

- **Causa**: la opción de desarrollador de TalkBack *Display speech output* (*Mostrar salida de voz*) viene desactivada por defecto al instalar el emulador.
- **Solución automática**: ejecuta `python3 talkback_audit.py --setup-only`. El método `AdbClient.ensure_speech_display()` abre `TalkBackPreferencesActivity`, navega a *Advanced settings > Developer settings* y activa el interruptor *Display speech output* / *Mostrar salida de voz*.
- **Solución manual** (si cambia el layout de ajustes según la versión de Android Accessibility Suite):
  1. Con TalkBack apagado (`python3 talkback_audit.py --stop-talkback --setup-only`), ejecuta:
     ```bash
     adb shell am start -n com.google.android.marvin.talkback/com.android.talkback.TalkBackPreferencesActivity
     ```
  2. Entra en **Ajustes avanzados > Ajustes para desarrolladores** (*Advanced settings > Developer settings*) y activa **Mostrar salida de voz** (*Display speech output*).

---

## 3. El foco se queda atrapado al pasar por un campo `<input>` o `EditText`

- **Causa**: al enfocar un campo de texto editable o numérico, puede abrirse el teclado virtual (`Gboard`) o TalkBack puede emitir un segundo anuncio diferido (`«Tocar dos veces para activar»` / `«Mostrando Teclado numérico»`).
- **Cómo lo maneja `talkback_audit.py`**:
  - En cada paso verifica `dumpsys input_method` (`mInputShown=true`) y cierra el teclado con `KEYCODE_ESCAPE` / `KEYCODE_BACK` antes de capturar la pantalla.
  - Si el anuncio capturado en modo automático es el hint secundario `«Tocar dos veces para activar»` o `«Mostrando Teclado...»`, envía automáticamente un pulso de avance adicional para continuar con el siguiente elemento de la vista.

---

## 4. No aparece la caja `.dombox` (`DOM WebView`) en los pasos del reporte

- **Causa**:
  1. La pantalla auditada es 100% nativa (`Android Views` o `Jetpack Compose`), por lo que sus nodos aparecen en la sección **Árbol accesible de la pantalla inicial** y en la línea `.nodeline` de cada paso.
  2. O bien es un `WebView` de producción compilado con `WebView.setWebContentsDebuggingEnabled(false)`.
- **Cómo verificar si el WebView expone el socket CDP**:
  ```bash
  adb shell "cat /proc/net/unix | grep webview_devtools_remote"
  ```
  Si devuelve `webview_devtools_remote_<pid>`, `tb_audit/cdp.py` se conectará automáticamente al puerto `9222` y extraerá tanto el árbol DOM/ARIA como las bases de datos `IndexedDB`.

---

## 5. Cómo elegir el modo de navegación (`--mode`)

| Modo | Cuándo usarlo | Comportamiento en TalkBack |
|---|---|---|
| `--mode swipe` *(por defecto)* | **Auditoría lineal completa** de cualquier vista | Inyecta el gesto nativo de swipe horizontal por consola QEMU; recorre absolutamente todos los encabezados, textos estáticos, imágenes y controles en el orden real de lectura de una persona ciega. |
| `--mode alt` | Navegación rápida por teclado de accesibilidad (`Alt + Flecha Derecha`) | Usa el atajo de teclado por defecto de TalkBack. Útil en vistas sin `<input>` activos que intercepten eventos de teclado. |
| `--mode tab` | Prueba de teclado externo Bluetooth (`Tab` / `Shift+Tab`) | Recorre únicamente controles interactivos enfocables (`button`, `a`, `input`, o nodos con `tabindex="0"`), saltándose encabezados y textos estáticos. |
| `--manual` | Flujos multi-pantalla con interacción del evaluador | El evaluador navega libremente en el emulador (o escribe `n`, `p`, `t`, `T`, `e`, `q` en la terminal) y el script graba cada cambio de foco y transición de pantalla. |
