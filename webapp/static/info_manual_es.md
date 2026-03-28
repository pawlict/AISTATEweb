# AISTATE Web Community — Manual de usuario

> **Edición:** Community (código abierto) · **Versión:** 3.7.2 beta
>
> La edición Community es una versión gratuita y completa de AISTATE Web para uso individual, educativo e investigación. Incluye todos los módulos: transcripción, diarización, traducción, análisis (LLM, AML, GSM, Crypto), Chat LLM e informes.

---

## 1. Proyectos

Los proyectos son el elemento central del trabajo con AISTATE. Cada proyecto almacena un archivo de audio, resultados de transcripción, diarización, traducciones, análisis y notas.

### Crear un proyecto
1. Vaya a la pestaña **Proyectos** en la barra lateral.
2. Haga clic en **Crear proyecto** e introduzca un nombre (p. ej., "Entrevista_2026_01").
3. Opcionalmente, agregue un archivo de audio (WAV, MP3, M4A, FLAC, OGG, OPUS, MP4, AAC).
4. Tras la creación, el proyecto se activa — es visible en la barra superior.

### Apertura y gestión
- Haga clic en la tarjeta de un proyecto para abrirlo y establecerlo como activo.
- Exporte un proyecto a un archivo `.aistate` (menú contextual de la tarjeta) — transfiéralo a otra máquina.
- Importe un archivo `.aistate` para agregar un proyecto de otra instancia.

### Eliminación
- Elimine un proyecto desde el menú contextual de la tarjeta. Puede elegir un método de sobrescritura de archivos (rápido / pseudoaleatorio / HMG IS5 / Gutmann).

---

## 2. Transcripción

Módulo de conversión de voz a texto.

### Cómo utilizar
1. Asegúrese de tener un proyecto activo con un archivo de audio (o agregue uno mediante el botón de la barra de herramientas).
2. Seleccione el **motor ASR** (Whisper o NeMo) y el **modelo** (p. ej., `large-v3`).
3. Seleccione el **idioma** de la grabación (o `auto` para detección automática).
4. Haga clic en el botón **Transcribir** (icono de IA).

### Resultado
- El texto aparece en bloques con marcas de tiempo (`[00:00:05.120 - 00:00:08.340]`).
- **Haga clic** en un bloque para reproducir el segmento de audio.
- **Clic derecho** en un bloque para abrir el editor en línea — modifique el texto y el nombre del hablante.
- Todos los cambios se guardan automáticamente.

### Detección de sonidos
- Si tiene instalado un modelo de detección de sonidos (YAMNet, PANNs, BEATs), active la opción **Detección de sonidos** en la barra de herramientas.
- Los sonidos detectados (tos, risa, música, sirena, etc.) aparecerán como marcadores en el texto.

### Corrección de texto
- Utilice la función **Corrección** para corregir automáticamente la transcripción mediante un modelo LLM (p. ej., Bielik, PLLuM, Qwen3).
- Compare el original con el texto corregido en una vista de diferencias lado a lado.

### Notas
- El panel de **Notas** (a la derecha) le permite agregar una nota global y notas para bloques individuales.
- El icono de nota junto a cada bloque indica si tiene una nota asignada.

### Informes
- En la barra de herramientas, seleccione los formatos (HTML, DOC, TXT) y haga clic en **Guardar** — los informes se guardan en la carpeta del proyecto.

---

## 3. Diarización

Módulo de identificación de hablantes — "quién habla cuándo".

### Cómo utilizar
1. Necesita un proyecto activo con un archivo de audio.
2. Seleccione el **motor de diarización**: pyannote (audio) o diarización NeMo.
3. Opcionalmente, establezca el número de hablantes (o déjelo en automático).
4. Haga clic en **Diarizar**.

### Resultado
- Cada bloque tiene una etiqueta de hablante (p. ej., `SPEAKER_00`, `SPEAKER_01`).
- **Mapeo de hablantes**: reemplace las etiquetas con nombres (p. ej., `SPEAKER_00` → "Juan García").
- Introduzca los nombres en los campos → haga clic en **Aplicar mapeo** → las etiquetas serán reemplazadas.
- El mapeo se guarda en `project.json` — se cargará automáticamente al reabrir el proyecto.

### Edición
- Clic derecho en un bloque para abrir el editor: modifique el texto, el hablante, reproduzca el segmento.
- Las notas funcionan igual que en Transcripción.

### Informes
- Exporte los resultados a HTML / DOC / TXT desde la barra de herramientas.

---

## 4. Traducción

Módulo de traducción multilingüe basado en modelos NLLB (Meta).

### Cómo utilizar
1. Vaya a la pestaña **Traducción**.
2. Seleccione un **modelo NLLB** (debe estar instalado en Configuración de NLLB).
3. Pegue texto o importe un documento (TXT, DOCX, PDF, SRT).
4. Seleccione el **idioma de origen** y los **idiomas de destino** (puede seleccionar varios).
5. Haga clic en **Generar**.

### Modos
- **Rápido (NLLB)** — modelos más pequeños, traducción más rápida.
- **Preciso (NLLB)** — modelos más grandes, mejor calidad.

### Funciones adicionales
- **Preservar formato** — mantiene los párrafos y saltos de línea.
- **Glosario de terminología** — utilice un glosario de términos especializados.
- **TTS (Lector)** — escuche el texto de origen y la traducción (requiere un motor TTS instalado).
- **Preajustes** — configuraciones predefinidas (documentos empresariales, artículos científicos, transcripciones de audio).

### Informes
- Exporte los resultados a HTML / DOC / TXT.

---

## 5. Chat LLM

Interfaz de chat con modelos LLM locales (a través de Ollama).

### Cómo utilizar
1. Vaya a **Chat LLM**.
2. Seleccione un **modelo** de la lista (debe estar instalado en Ollama).
3. Escriba un mensaje y haga clic en **Enviar**.

### Opciones
- **Prompt del sistema** — defina el rol del asistente (p. ej., "Usted es un abogado especializado en derecho español").
- **Temperatura** — controle la creatividad de las respuestas (0 = determinista, 1.5 = muy creativo).
- **Historial** — las conversaciones se guardan automáticamente. Vuelva a una conversación anterior desde la barra lateral.

---

## 6. Análisis

La pestaña Análisis contiene cuatro módulos: LLM, AML, GSM y Crypto. Cambie entre ellos usando las pestañas en la parte superior.

### 6.1 Análisis LLM

Módulo de análisis de contenido mediante modelos LLM.

1. Seleccione las **fuentes de datos** en el panel lateral (transcripción, diarización, notas, documentos).
2. Elija **prompts** — plantillas o cree los suyos propios.
3. Haga clic en **Generar** (icono de IA en la barra de herramientas).

#### Análisis rápido
- Análisis automático y ligero que se activa tras la transcripción.
- Utiliza un modelo más pequeño (configurado en Configuración de LLM).

#### Análisis profundo
- Análisis completo a partir de las fuentes y prompts seleccionados.
- Admite prompts personalizados: escriba una instrucción en el campo "Prompt personalizado" (p. ej., "Cree un acta de reunión con las decisiones").

### 6.2 Análisis AML (Anti-Money Laundering)

Módulo de análisis financiero para extractos bancarios.

1. Cargue un extracto bancario (PDF o MT940) — el sistema detecta automáticamente el banco y analiza las transacciones.
2. Revise la **información del extracto**, las cuentas y tarjetas identificadas.
3. Clasifique las transacciones: neutral / legítima / sospechosa / monitoreo.
4. Vea los **gráficos**: saldo en el tiempo, categorías, canales, tendencia mensual, actividad diaria, principales contrapartes.
5. **Anomalías ML** — el algoritmo Isolation Forest detecta transacciones inusuales.
6. **Grafo de flujos** — visualización de relaciones entre contrapartes (diseños: flujo, monto, línea de tiempo).
7. Haga preguntas al modelo LLM sobre los datos financieros (sección "Pregunta / instrucción para el análisis").
8. Descargue un **informe HTML** con los resultados del análisis.

#### Panel del analista (AML)
- Panel izquierdo con búsqueda, nota global y notas de elementos.
- **Ctrl+M** — agregue rápidamente una nota al elemento actual.
- Etiquetas: neutral, legítima, sospechosa, monitoreo + 4 etiquetas personalizadas (doble clic para renombrar).

### 6.3 Análisis GSM / BTS

Módulo de análisis de datos de facturación GSM.

1. Cargue los datos de facturación (CSV, XLSX, PDF, ZIP con varios archivos).
2. Vea el **resumen**: cantidad de registros, período, dispositivos (IMEI/IMSI).
3. **Anomalías** — detección de patrones inusuales (actividad nocturna, roaming, doble SIM, etc.).
4. **Números especiales** — identificación de números de emergencia, de servicio, etc.
5. **Grafo de contactos** — visualización de los contactos más frecuentes (Top 5/10/15/20).
6. **Registros** — tabla de todos los registros con filtrado, búsqueda y gestión de columnas.
7. **Gráficos de actividad** — mapa de calor de distribución horaria, actividad nocturna y de fines de semana.
8. **Mapa BTS** — mapa interactivo con múltiples vistas:
   - Todos los puntos, ruta, clústeres, viajes, frontera, cobertura BTS, mapa de calor, línea de tiempo.
   - **Capas superpuestas**: bases militares, aeropuertos civiles, sedes diplomáticas.
   - **Importación KML/KMZ** — capas personalizadas desde Google Earth.
   - **Mapas sin conexión** — soporte MBTiles (ráster + vector PBF).
   - **Selección de área** — círculo / rectángulo para consultas espaciales.
9. **Ubicaciones detectadas** — clústeres de las ubicaciones más frecuentes.
10. **Cruces de frontera** — detección de viajes al extranjero.
11. **Estancias nocturnas** — análisis de ubicaciones de pernocta.
12. **Análisis narrativo (LLM)** — genere un informe de análisis GSM mediante un modelo Ollama.
13. **Informes** — exportación a HTML / DOCX / TXT. Notas analíticas en DOCX con gráficos.

#### Disposición de secciones
- El botón **Personalizar disposición** en el panel del analista le permite cambiar el orden y la visibilidad de las secciones (arrastrar / marcar-desmarcar).

#### Panel del analista (GSM)
- Panel izquierdo con búsqueda, nota global y notas de elementos.
- **Ctrl+M** — agregue rápidamente una nota al registro actual.

#### Mapa independiente
- Abra un mapa sin datos de facturación (botón de mapa en la barra de herramientas).
- Modo de edición — agregue puntos, polígonos, capas de usuario.

### 6.4 Análisis Crypto *(experimental)*

Módulo de análisis sin conexión de transacciones de criptomonedas (BTC / ETH) y datos de exchanges.

#### Importación de datos
1. Vaya a la pestaña **Crypto** en el módulo de Análisis.
2. Haga clic en **Cargar datos** y seleccione un archivo CSV o JSON.
3. El sistema detecta automáticamente el formato:
   - **Blockchain**: WalletExplorer.com, Etherscan
   - **Exchanges**: Binance, Kraken, Coinbase, Revolut y más (más de 16 formatos)
4. Tras la carga, aparece la información de los datos: cantidad de transacciones, período, portafolio de tokens.

#### Vista de datos
- **Modo exchange** — tabla de transacciones del exchange con tipos (depósito, retiro, intercambio, staking, etc.).
- **Modo blockchain** — tabla de transacciones en cadena con direcciones y montos.
- **Portafolio de tokens** — lista de tokens con descripciones, clasificación (conocido / desconocido) y valores.
- **Diccionario de tipos de transacción** — pase el cursor sobre un tipo para ver su descripción (tooltip).

#### Clasificación y revisión
- Clasifique las transacciones: neutral / legítima / sospechosa / monitoreo.
- El sistema clasifica automáticamente algunas transacciones basándose en patrones.

#### Anomalías
- **Detección de anomalías ML** — el algoritmo detecta transacciones inusuales (montos elevados, horarios inusuales, patrones sospechosos).
- Tipos de anomalías: peel chain, dust attack, round-trip, smurfing, structuring.
- Base de datos de direcciones sancionadas por **OFAC** y búsqueda de contratos DeFi conocidos.

#### Gráficos
- **Línea de tiempo del saldo** — cambios en el saldo a lo largo del tiempo (con normalización logarítmica).
- **Volumen mensual** — totales de transacciones por mes.
- **Actividad diaria** — distribución de transacciones por día de la semana.
- **Ranking de contrapartes** — socios de transacción más frecuentes.

#### Grafo de flujos
- **Grafo de transacciones** interactivo (Cytoscape.js) — visualización de flujos entre direcciones/contrapartes.
- Haga clic en un nodo para ver los detalles.

#### Perfil de usuario (Binance)
- 10 patrones de comportamiento: HODLer, Scalper, Day Trader, Swing Trader, Staker, Whale, Institutional, Alpha Hunter, Meme Trader, Bagholder.
- 18 fichas de análisis forense (contrapartes internas, direcciones en cadena, wash trading, P2P, análisis de comisiones y más).

#### Análisis narrativo (LLM)
- Haga clic en **Generar análisis** → un modelo Ollama generará un informe descriptivo con conclusiones y recomendaciones.

#### Informes
- Exporte los resultados a **HTML / DOCX / TXT** desde la barra de herramientas.

#### Panel del analista (Crypto)
- Panel izquierdo con nota global y notas de transacciones.
- **Ctrl+M** — agregue rápidamente una nota a la transacción actual.
- Etiquetas: neutral, legítima, sospechosa, monitoreo + 4 etiquetas personalizadas.

---

## 7. Registros

Monitoreo de tareas y diagnóstico del sistema.

- Vaya a la pestaña **Registros** para ver el estado de todas las tareas (transcripción, diarización, análisis, traducción).
- Copie los registros al portapapeles o guárdelos en un archivo.
- Limpie la lista de tareas (no elimina los proyectos).

---

## 8. Panel de administración

### Configuración de GPU
- Monitoree las tarjetas GPU, VRAM, tareas activas.
- Establezca límites de concurrencia (ranuras por GPU, fracción de memoria).
- Visualice y administre la cola de trabajos.
- Establezca prioridades de tipos de tareas (arrastre para reordenar).

### Configuración de ASR
- Instale modelos Whisper (tiny → large-v3).
- Instale modelos de ASR y diarización NeMo.
- Instale modelos de detección de sonido (YAMNet, PANNs, BEATs).

### Configuración de LLM
- Explore e instale modelos Ollama (análisis rápido, análisis profundo, financiero, corrección, traducción, visión/OCR).
- Agregue un modelo Ollama personalizado.
- Configure tokens (Hugging Face).

### Configuración de NLLB
- Instale modelos de traducción NLLB (distilled-600M, distilled-1.3B, base-3.3B).
- Consulte la información del modelo (tamaño, calidad, requisitos).

### Configuración de TTS
- Instale motores de lectura: Piper (rápido, CPU), MMS (más de 1100 idiomas), Kokoro (máxima calidad).
- Pruebe las voces antes de usarlas.

---

## 9. Configuración

- **Idioma de la interfaz** — cambie entre PL / EN / KO.
- **Token de Hugging Face** — requerido para los modelos de pyannote (modelos con acceso restringido).
- **Modelo Whisper predeterminado** — preferencia para nuevas transcripciones.

---

## 10. Gestión de usuarios (modo multiusuario)

Si el modo multiusuario está habilitado:
- Los administradores crean, editan, suspenden y eliminan cuentas de usuario.
- Los nuevos usuarios esperan la aprobación del administrador después del registro.
- Cada usuario tiene un rol asignado que determina los módulos disponibles.

---

## 11. Cifrado de proyectos

AISTATE permite cifrar proyectos para proteger los datos contra el acceso no autorizado.

### Configuración (administrador)

En el panel **Gestión de usuarios → Seguridad → Política de seguridad**, el administrador configura:

- **Cifrado de proyectos** — habilitar / deshabilitar la capacidad de cifrado.
- **Método de cifrado** — elija uno de tres métodos:

| Nivel | Algoritmo | Descripción |
|-------|-----------|-------------|
| **Ligero** | AES-128-GCM | Cifrado rápido, protección contra acceso casual |
| **Estándar** | AES-256-GCM | Nivel predeterminado — equilibrio entre velocidad y seguridad |
| **Máximo** | AES-256-GCM + ChaCha20-Poly1305 | Cifrado de doble capa para datos sensibles |

- **Forzar cifrado** — cuando está habilitado, los usuarios no pueden crear proyectos sin cifrar.

El nivel de cifrado seleccionado se aplica a todos los proyectos posteriores creados por los usuarios.

### Creación de un proyecto cifrado

Al crear un proyecto, aparece una casilla **Cifrar proyecto** con información sobre el método actual (por ejemplo, "AES-256-GCM"). La casilla está marcada de forma predeterminada si el administrador ha habilitado el cifrado, y bloqueada si el cifrado es obligatorio.

### Exportación e importación

- **Exportación** de un proyecto cifrado — el archivo `.aistate` siempre está cifrado. El sistema solicita una **contraseña de exportación** (diferente de la contraseña de la cuenta).
- **Importación** — el sistema detecta automáticamente si el archivo `.aistate` está cifrado. Si es así, solicita la contraseña. Después de la importación, el proyecto se vuelve a cifrar según la política actual del administrador.
- Un proyecto sin cifrar puede exportarse sin contraseña O con la opción "cifrar exportación".

### <span style="color:red">⚠ Recuperación de acceso — procedimientos paso a paso</span>

<span style="color:red">Cada proyecto cifrado tiene una clave de cifrado aleatoria (Project Key), que está protegida por la clave del usuario (derivada de su contraseña). Además, la clave del proyecto está asegurada por la **Master Key** del administrador. El administrador **no puede descifrar un proyecto solo** — se requiere la interacción del usuario.</span>

#### <span style="color:red">Escenario 1: El usuario olvidó su contraseña (autorrecuperación)</span>

<span style="color:red">El usuario tiene su frase de recuperación (12 palabras recibidas al crear la cuenta).</span>

<span style="color:red">**Pasos del usuario:**</span>
<span style="color:red">1. En la pantalla de inicio de sesión, haga clic en **"Olvidé mi contraseña"**.</span>
<span style="color:red">2. Introduzca su **frase de recuperación** (12 palabras, separadas por espacios).</span>
<span style="color:red">3. El sistema verifica la frase — si es correcta, aparece un formulario para nueva contraseña.</span>
<span style="color:red">4. Establezca una **nueva contraseña** y confírmela.</span>
<span style="color:red">5. El sistema vuelve a cifrar automáticamente las claves de todos sus proyectos cifrados con la nueva contraseña.</span>
<span style="color:red">6. Inicie sesión normalmente con la nueva contraseña.</span>

<span style="color:red">**No se necesita la intervención del administrador** — el proceso es completamente automático.</span>

#### <span style="color:red">Escenario 2: El usuario olvidó su contraseña pero tiene la frase de recuperación (recuperación asistida por el administrador)</span>

<span style="color:red">Si el restablecimiento de autoservicio no funcionó o está deshabilitado por política:</span>

<span style="color:red">**Pasos del administrador:**</span>
<span style="color:red">1. Abra **Gestión de usuarios** → busque la cuenta del usuario.</span>
<span style="color:red">2. Haga clic en **"Generar token de recuperación"** — el sistema genera un token de un solo uso (válido durante 24 horas).</span>
<span style="color:red">3. Entregue el token al usuario (en persona, por teléfono o a través de otro canal seguro).</span>

<span style="color:red">**Pasos del usuario:**</span>
<span style="color:red">1. Vaya a la página de **recuperación de acceso** (enlace en la pantalla de inicio de sesión).</span>
<span style="color:red">2. Introduzca el **token de recuperación** recibido del administrador.</span>
<span style="color:red">3. Introduzca su **frase de recuperación** (12 palabras).</span>
<span style="color:red">4. Establezca una **nueva contraseña**.</span>
<span style="color:red">5. El sistema vuelve a cifrar las claves del proyecto con la nueva contraseña.</span>
<span style="color:red">6. El token se invalida después de su uso.</span>

#### <span style="color:red">Escenario 3: El usuario perdió la contraseña Y la frase de recuperación (recuperación con Master Key)</span>

<span style="color:red">Este es el único escenario en el que se utiliza la **Master Key**.</span>

<span style="color:red">**Pasos del administrador:**</span>
<span style="color:red">1. Abra **Gestión de usuarios → Seguridad → Cifrado**.</span>
<span style="color:red">2. Introduzca su **contraseña de administrador** para desbloquear la Master Key.</span>
<span style="color:red">3. Seleccione la cuenta del usuario que perdió el acceso.</span>
<span style="color:red">4. Haga clic en **"Recuperación de emergencia"** — el sistema utiliza la Master Key para descifrar las claves del proyecto del usuario.</span>
<span style="color:red">5. El sistema genera una **nueva frase de recuperación** para el usuario.</span>
<span style="color:red">6. El sistema genera un **token de recuperación de un solo uso**.</span>
<span style="color:red">7. Entregue al usuario: el token + la nueva frase de recuperación.</span>

<span style="color:red">**Pasos del usuario:**</span>
<span style="color:red">1. Vaya a la página de **recuperación de acceso**.</span>
<span style="color:red">2. Introduzca el **token** del administrador.</span>
<span style="color:red">3. Introduzca la **nueva frase de recuperación** del administrador.</span>
<span style="color:red">4. Establezca una **nueva contraseña**.</span>
<span style="color:red">5. El sistema vuelve a cifrar las claves del proyecto con la nueva contraseña.</span>

<span style="color:red">**IMPORTANTE:** ¡La nueva frase de recuperación debe guardarse inmediatamente y almacenarse en un lugar seguro!</span>

### <span style="color:red">⚠ Copia de seguridad de la Master Key</span>

<span style="color:red">**ADVERTENCIA:** Si un usuario pierde su contraseña y su frase de recuperación, y el administrador pierde la Master Key — **los datos de los proyectos cifrados serán irrecuperables**. No existe una "puerta trasera".</span>

<span style="color:red">**Responsabilidades del administrador:**</span>
<span style="color:red">1. Después de inicializar la Master Key, haga clic en **"Copia de seguridad de la Master Key"** en el panel de cifrado.</span>
<span style="color:red">2. Introduzca la contraseña de administrador — el sistema muestra la clave en formato base64.</span>
<span style="color:red">3. **Guarde la clave en un medio sin conexión** (unidad USB, impresión en una caja fuerte) — NO la almacene en el sistema ni en el correo electrónico.</span>
<span style="color:red">4. Verifique periódicamente la copia de seguridad utilizando el botón **"Verificar Master Key"**.</span>

<span style="color:red">**Pérdida de la Master Key + contraseña del usuario + frase de recuperación = pérdida permanente de datos.**</span>

### <span style="color:red">⚠ Búsqueda en proyectos cifrados</span>

<span style="color:red">La lista de proyectos (nombre, fecha de creación) siempre es visible. Sin embargo, la **búsqueda de contenido** (transcripciones, notas, resultados de análisis) requiere el descifrado de los datos y funciona **solo en el proyecto activo (abierto)**. No es posible buscar en múltiples proyectos cifrados simultáneamente.</span>

---

## 12. A.R.I.A. — Asistente de IA

El botón flotante de A.R.I.A. (esquina inferior derecha) abre el panel del asistente de IA.

### Características
- **Chat de IA** — haga preguntas sobre el contexto actual (transcripción, análisis, datos).
- **Contexto automático** — el asistente incluye automáticamente los datos de la página actualmente abierta.
- **Lectura de respuestas** (TTS) — escuche la respuesta del asistente.
- **Sugerencias rápidas** — preguntas predefinidas adaptadas al módulo actual.
- **Arrastrable** — el botón de A.R.I.A. se puede arrastrar a cualquier lugar de la pantalla (la posición se recuerda).

---

## 13. Reproductor de audio

La barra del reproductor de audio aparece en Transcripción y Diarización cuando el proyecto tiene un archivo de audio.

- **Reproducir / Pausar** — reproduzca o detenga la grabación.
- **Saltar** ±5 segundos (botones o clic en la barra de progreso).
- **Velocidad de reproducción** — 0.5×, 0.75×, 1×, 1.25×, 1.5×, 2× (guardada en el navegador).
- **Haga clic en un segmento de texto** para reproducir el fragmento de audio correspondiente.
- **Mapa de forma de onda** — visualización de amplitud con marcadores de segmentos.

---

## 14. Búsqueda y edición de segmentos

### Búsqueda de texto
- En Transcripción y Diarización, use **Ctrl+F** o el icono de lupa en la barra de herramientas.
- La búsqueda resalta las coincidencias y muestra el recuento.
- Navegue entre las coincidencias con las flechas ↑ ↓.

### Fusión y división de segmentos
- **Fusionar segmentos** — seleccione dos bloques adyacentes y haga clic en "Fusionar" (icono de la barra de herramientas).
- **Dividir segmento** — coloque el cursor en un bloque y haga clic en "Dividir" → el bloque se divide en la posición del cursor.

---

## 15. Modo oscuro / claro

- Haga clic en el icono de tema en la barra lateral (icono de sol / luna).
- La elección se recuerda en el navegador.

---

## Atajos de teclado

| Atajo | Acción |
|-------|--------|
| **Esc** | Cerrar el editor de bloques / cerrar la búsqueda |
| **Ctrl+F** | Abrir búsqueda de texto (transcripción / diarización) |
| **Ctrl+Enter** | Guardar nota |
| **Ctrl+M** | Agregar nota de analista (AML / GSM / Crypto) |
| **Clic derecho** | Abrir editor de bloques (transcripción / diarización) |
| **Clic en segmento** | Reproducir fragmento de audio |
