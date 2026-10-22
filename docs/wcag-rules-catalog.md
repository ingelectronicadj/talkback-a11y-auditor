# Catálogo de Reglas `TB-*` y Taxonomía WCAG 2.2

**TalkBack Audit** incluye los **86 criterios de conformidad de WCAG 2.2 (Niveles A, AA y AAA)** en `tb_audit/wcag_catalog.py` y evalúa automáticamente **16 reglas especializadas para lectores de pantalla móviles (`TB-*`)** en `tb_audit/rules.py`.

---

## Resumen de las 16 Reglas Automatizadas (`TB-*`)

| ID Regla | Criterio WCAG 2.2 | Nivel | Severidad | Qué detecta |
|---|---|---|---|---|
| `TB-I18N-001` | `3.1.2` Idioma de las partes / `2.4.6` | AA | Alta | Keys de traducción crudas sin resolver (`a11y_*`, `mb_mc_*`), textos en inglés dentro de vistas en español (o viceversa), placeholders sin interpolar (`{variable}`) o errores de tilde/voseo. |
| `TB-LINK-001` | `2.4.4` Propósito de los enlaces | A | Alta | Enlaces sin texto de destino (anuncian solo `«(Abrir una nueva ventana). vínculo»`) o que duplican su etiqueta (`«Saber más. Saber más...»`) por autorreferencia en `aria-labelledby`. |
| `TB-SKEL-001` | `4.1.3` Mensajes de estado / `2.4.3` | AA | Alta | Pantallas o drawers en estado de carga con *skeletons* que no anuncian `«Cargando {título}»`, pierden el foco hacia el overlay de TalkBack o dejan nodos `role="status"` vacíos (`«status»`). |
| `TB-CHART-001` | `2.4.1` Evitar bloques | A | Alta | Gráficas interactivas (`<svg>`) cuyos puntos individuales (`<circle>`) tienen `tabindex="0"` y obligan al usuario de TalkBack a hacer decenas o cientos de swipes para cruzar la gráfica. |
| `TB-FOCUS-001` | `2.4.3` Orden del foco | A | Alta | Pérdida de retorno de foco (*Focus Return*): al cerrar un diálogo modal, tooltip o drawer, el foco de TalkBack no regresa al botón disparador que lo abrió. |
| `TB-CURR-001` | `1.3.1` Información y relaciones | A | Alta | Importes monetarios en pesos u otra moneda local que usan el símbolo `$` sin desambiguar en `aria-label` / `contentDescription`, haciendo que el TTS en español anuncie `«dólares»` o `«Signo de dólar»`. |
| `TB-UNREACH-001` | `1.3.1` Información y relaciones / `2.1.1` | A | Alta | Elementos o etiquetas semánticas presentes en el DOM activo (como el par de activos en filas 2..N de listas de movimientos o controles visibles) que son omitidos por TalkBack durante el barrido lineal. |
| `TB-HEAD-002` | `1.3.1` Información y relaciones / `2.4.6` | A | Media | Jerarquía de encabezados (`H1-H6`) con saltos de nivel (`H1 -> H3` sin `H2`), ausencia de `H1` principal o encabezados ocultos (`screen-reader`) que contienen párrafos extensos (`> 120` caracteres). |
| `TB-NAME-001` | `4.1.2` Nombre, función, valor | A | Alta | Controles interactivos (`clickable` / `focusable`) que carecen de nombre accesible (`text`, `contentDescription` o `aria-label`). |
| `TB-IMG-001` | `1.1.1` Contenido no textual | A | Alta | Imágenes, iconos o gráficos (`ImageView`, `ImageButton`, `<svg>`, `<img>`) sin alternativa textual (`Sin etiquetar. Imagen`) o logos decorativos sin `alt=""` que disparan el OCR de TalkBack (`Detected: Text`). |
| `TB-MERGE-001` | `1.3.2` Secuencia significativa | A | Media | Un único paso de foco concatena `>= 18` palabras (o duplica párrafos largos dentro de un encabezado oculto `<h2>`), o fragmenta filas relacionales omitiendo contexto. |
| `TB-LABEL-001` | `2.5.3` Etiqueta en el nombre | A | Media | El `contentDescription` / `aria-label` no contiene el texto visible en pantalla del botón o control. |
| `TB-TARGET-001` | `2.5.8` Tamaño del objetivo (mínimo) | AA | Media | Controles interactivos con área táctil inferior a `44x44 px` (`48x48 dp` recomendados en Android). |
| `TB-STATUS-001` | `4.1.3` Mensajes de estado | AA | Media | Mensajes de error de sección (`Tuvimos un problema`, `No es posible recuperar...`) o contenedores `role="status"` vacíos expuestos en el barrido lineal. |
| `TB-HEAD-001` | `2.4.6` Encabezados y etiquetas | AA | Baja | La etiqueta accesible incluye manualmente el nombre del rol (`botón`, `icono`, `imagen`), provocando anuncios redundantes (`«Cerrar botón, Botón»`). |
| `TB-LANG-001` | `3.1.2` Idioma de las partes | AA | Baja | El lector mezcla frases del sistema en inglés (`Showing Gboard`, `Button`, `Double-tap to activate`) con interfaz en español por configuración de `locale` del dispositivo o ausencia de `lang`. |

---

## Patrones de Remediación por Tecnología

### 1. Android Views (XML / Kotlin)
- **Moneda (`TB-CURR-001`)**:
  ```kotlin
  amountTextView.text = "$ 11.431.667,53"
  amountTextView.contentDescription = "11.431.667 con 53 pesos argentinos"
  ```
- **Imágenes decorativas (`TB-IMG-001`)**:
  ```xml
  <ImageView
      android:importantForAccessibility="no"
      android:contentDescription="@null" />
  ```
- **Estados de carga (`TB-SKEL-001`)**:
  ```kotlin
  skeletonContainer.accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
  skeletonContainer.contentDescription = getString(R.string.a11y_loading_section, sectionTitle)
  ```

### 2. Jetpack Compose
- **Agrupación semántica y reemplazo de etiqueta**:
  ```kotlin
  Row(
      modifier = Modifier.semantics(mergeDescendants = true) {
          contentDescription = "Orden 1 de 3: ARS a Bitcoin, 24/09/2026, +0.01166 BTC, -1.527.042,80 pesos argentinos"
      }
  ) { /* ... */ }
  ```
- **Retorno de foco tras cerrar ModalBottomSheet / Dialog (`TB-FOCUS-001`)**:
  Guardar un `FocusRequester` en el `IconButton` invocador y llamar a `triggerFocusRequester.requestFocus()` al cerrarse el estado del diálogo.

### 3. WebView Híbrido (React / HTML / ARIA)
- **Gráficas SVG (`TB-CHART-001`)**:
  En WebView móvil con TalkBack, el barrido lineal recorre todos los nodos del Accessibility Tree aunque tengan `tabindex="-1"`, y si tienen `tabindex="0"` atrapa también la navegación por teclado. Ocultar los puntos individuales con `aria-hidden="true"` y exponer una tabla o botón alternativo (`Mostrar datos del gráfico`).
- **Logos decorativos (`TB-IMG-001`)**:
  En Chromium Android, `<img aria-hidden="true" src="logo.svg">` sin atributo `alt` puede seguir disparando el OCR de imagen de TalkBack (`Detected: Text`) cuando forma parte de un contenedor enfocable. Siempre incluir `alt=""` y `role="presentation"` junto a `aria-hidden="true"`.
