# AISTATE Web — Información

**AISTATE Web** (*Artificial Intelligence Speech‑To‑Analysis‑Translation‑Engine*) es una aplicación web para **transcripción**, **diarización de hablantes**, **traducción**, **análisis GSM/BTS** y **análisis financiero AML**.

---

## 🚀 Qué hace

- **Transcripción** — Audio → texto (Whisper, WhisperX, NeMo)
- **Diarización** — "quién habló cuándo" + segmentos por hablante (pyannote, NeMo)
- **Traducción** — Texto → otros idiomas (NLLB‑200, completamente offline)
- **Análisis (LLM / Ollama)** — resúmenes, hallazgos, informes
- **Análisis GSM / BTS** — importación de facturación, mapa BTS, rutas, clústeres, línea de tiempo
- **Análisis financiero (AML)** — análisis de extractos bancarios, puntuación de riesgo, detección de anomalías
- **Registros y progreso** — monitorización de tareas + diagnósticos

---

## 🆕 Novedades en 3.7.1 beta

### 🔐 Análisis de criptomonedas — Binance XLSX
- Análisis ampliado de datos del exchange Binance
- Perfilado de comportamiento del usuario (10 patrones: HODLer, Scalper, Day Trader, Swing Trader, Staker, Whale, Institutional, Alpha Hunter, Meme Trader, Bagholder)
- 18 tarjetas de análisis forense:
  - Contrapartes internas, Pay C2C, direcciones on-chain, flujos pass-through, monedas de privacidad, registros de acceso, tarjetas de pago
  - **NUEVO:** Análisis temporal (distribución horaria, ráfagas, dormancia), cadenas de conversión de tokens, detección de structuring/smurfing, wash trading, análisis fiat on/off ramp, análisis P2P, velocidad depósito-retiro, análisis de comisiones, análisis de redes blockchain, análisis de seguridad extendido (detección VPN/proxy)

---

## 🆕 Novedades en 3.6 beta

### 📱 Análisis GSM / BTS
- Importar datos de facturación (CSV, XLSX, PDF)
- **Mapa BTS** interactivo con múltiples vistas: puntos, ruta, clústeres, viajes, cobertura BTS, mapa de calor, línea de tiempo
- **Mapas offline** — soporte MBTiles (raster PNG/JPG/WebP + vector PBF vía MapLibre GL)
- **Capas superpuestas**: bases militares, aeropuertos civiles, embajadas (datos integrados)
- **Importación KML/KMZ** — capas personalizadas desde Google Earth y otras herramientas GIS
- Selección de área (círculo / rectángulo) para consultas espaciales
- Grafo de contactos, mapa de calor de actividad, análisis de contactos principales
- Capturas de pantalla del mapa con marca de agua (mapas online y offline + todas las capas)

### 💰 Análisis financiero (AML)
- Pipeline **Anti‑Money Laundering** para extractos bancarios
- Detección automática de bancos y análisis de PDF: PKO BP, ING, mBank, Pekao SA, Santander, Millennium, Revolut (+ fallback genérico)
- Soporte de formato MT940 (SWIFT)
- Normalización de transacciones, clasificación basada en reglas y puntuación de riesgo
- **Detección de anomalías**: línea base estadística + ML (Isolation Forest)
- **Análisis de grafos** — visualización de la red de contrapartes
- Análisis multi-cuenta para investigaciones
- Análisis de gastos, patrones de comportamiento, categorización de comercios
- Análisis asistido por LLM (constructor de prompts para modelos Ollama)
- Informes HTML con gráficos
- Perfiles de anonimización de datos para compartir de forma segura

---

## 🆕 Novedades en 3.5.1 beta

- **Corrección de texto** — comparación lado a lado del original vs. texto corregido, selector de modelo (Bielik, PLLuM, Qwen3), modo expandido.
- **Vista de proyecto rediseñada** — diseño en cuadrícula, info de equipo, invitaciones por tarjeta.
- Correcciones menores de interfaz y estabilidad.

---

## 🆕 Novedades en 3.2 beta

- **Módulo de traducción (NLLB)** — traducción multilingüe local (incl. PL/EN/ZH y más).
- **Configuración NLLB** — selección de modelo, opciones de ejecución, visibilidad de caché.

---

## 📦 De dónde se descargan los modelos

AISTATE web **no** incluye los pesos de los modelos en el repositorio. Los modelos se descargan bajo demanda y se almacenan en caché localmente:

- **Hugging Face Hub**: pyannote + NLLB (caché estándar de HF).
- **NVIDIA NGC / NeMo**: modelos ASR/diarización NeMo.
- **Ollama**: modelos LLM descargados por el servicio Ollama.
---

## 🔐 Seguridad y gestión de usuarios

AISTATE Web soporta dos modos de implementación:

- **Modo usuario único** — simplificado, sin inicio de sesión (local / autoalojado).
- **Modo multiusuario** — autenticación completa, autorización y gestión de cuentas (diseñado para 50–100 usuarios concurrentes).

### 👥 Roles y permisos

**Roles de usuario** (acceso a módulos):
- Transkryptor, Lingwista, Analityk, Dialogista, Strateg, Mistrz Sesji

**Roles administrativos:**
- **Architekt Funkcji** — gestión de configuración de la aplicación
- **Strażnik Dostępu** — gestión de cuentas de usuario (crear, aprobar, bloquear, restablecer contraseñas)
- **Główny Opiekun (superadmin)** — acceso completo a todos los módulos y funciones de administración

### 🔑 Mecanismos de seguridad

- **Hash de contraseñas**: PBKDF2-HMAC-SHA256 (260.000 iteraciones)
- **Política de contraseñas**: configurable (ninguna / básica / media / fuerte); los admins siempre requieren contraseñas fuertes (12+ caracteres)
- **Lista negra de contraseñas**: integrada + lista personalizada del admin
- **Expiración de contraseñas**: configurable (forzar cambio tras X días)
- **Bloqueo de cuenta**: tras intentos fallidos configurables (por defecto 5), desbloqueo automático tras 15 min
- **Limitación de velocidad**: login y registro limitados (5 por minuto por IP)
- **Sesiones**: tokens seguros, cookies HTTPOnly + SameSite=Lax, timeout configurable (por defecto 8h)
- **Frase de recuperación**: mnemónico BIP-39 de 12 palabras (~132 bits de entropía)
- **Bloqueo de usuarios**: permanente o temporal, con motivo
- **Cabeceras de seguridad**: X-Content-Type-Options, X-Frame-Options, X-XSS-Protection, Referrer-Policy

### 📝 Auditoría y registro

- Registro completo de eventos: inicios de sesión, intentos fallidos, cambios de contraseña, creación/eliminación de cuentas
- Registro de dirección IP y huella digital del navegador
- Logs basados en archivos con rotación horaria + base de datos SQLite
- Historial de acceso + pista de auditoría completa para administradores

### 📋 Registro y aprobación

- Auto-registro con aprobación obligatoria del administrador
- Cambio obligatorio de contraseña en el primer inicio de sesión
- Frase de recuperación generada y mostrada una sola vez

---

## ⚖️ Licencias

### Licencia de la aplicación

- **AISTATE Web**: **Licencia MIT** (AS IS).

### Motores / bibliotecas (licencias de código)

- **OpenAI Whisper**: **MIT**.
- **pyannote.audio**: **MIT**.
- **WhisperX**: **MIT**.
- **NVIDIA NeMo Toolkit**: **Apache 2.0**.
- **Ollama (servidor/CLI)**: **MIT**.

### Licencias de modelos (pesos / checkpoints)

> Los pesos de los modelos tienen licencia **separada** del código. Verifique siempre los términos del proveedor.

- **Meta NLLB‑200 (NLLB)**: **CC‑BY‑NC 4.0** (restricciones no comerciales).
- **Pipelines pyannote (HF)**: depende del modelo; algunos están **restringidos** y requieren aceptar términos.
- **Modelos NeMo (NGC/HF)**: depende del modelo.
- **LLMs vía Ollama**: depende del modelo.

### Mapas y datos geográficos

- **Leaflet** (motor de mapas): **BSD‑2‑Clause** — https://leafletjs.com
- **MapLibre GL JS** (renderizado vector PBF): **BSD‑3‑Clause** — https://maplibre.org
- **OpenStreetMap** (tiles online): datos © OpenStreetMap contributors, **ODbL 1.0** — atribución requerida
- **OpenMapTiles** (esquema PBF): **BSD‑3‑Clause**; datos bajo ODbL
- **html2canvas** (capturas): **MIT**

### Importante

- Esta página es un resumen. Consulte **THIRD_PARTY_NOTICES.md** en el repositorio para la lista completa.
- Para uso comercial / organizacional, preste especial atención a **NLLB (CC‑BY‑NC)** y las licencias de los modelos LLM elegidos.

---

## 💬 Contacto / soporte

Problemas, sugerencias, solicitudes de funciones: **pawlict@proton.me**
