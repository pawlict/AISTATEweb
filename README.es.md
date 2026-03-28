# AISTATEweb Community (3.7.2 beta)

[![English](https://flagcdn.com/24x18/gb.png) English](README.md) | [![Polski](https://flagcdn.com/24x18/pl.png) Polski](README.pl.md) | [![한국어](https://flagcdn.com/24x18/kr.png) 한국어](README.ko.md) | [![Español](https://flagcdn.com/24x18/es.png) Español](README.es.md) | [![Français](https://flagcdn.com/24x18/fr.png) Français](README.fr.md) | [![中文](https://flagcdn.com/24x18/cn.png) 中文](README.zh.md) | [![Українська](https://flagcdn.com/24x18/ua.png) Українська](README.uk.md) | [![Deutsch](https://flagcdn.com/24x18/de.png) Deutsch](README.de.md)

![Versión](https://img.shields.io/badge/Versión-3.7.2%20beta-orange)
![Edición](https://img.shields.io/badge/Edición-Community-blue)
![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![Plataforma](https://img.shields.io/badge/Plataforma-Web-lightgrey)
![Licencia](https://img.shields.io/badge/Licencia-MIT-green)

* * *

AISTATEweb Community es una herramienta web para transcripción de audio, diarización de hablantes, traducción, análisis asistido por IA y generación de informes estructurados — completamente sin conexión, ejecutándose en hardware local.

#### Comentarios / Soporte

Si tiene algún problema, sugerencia o solicitud de funcionalidad, contácteme en: **pawlict@proton.me**

* * *

## 🚀 Funcionalidades principales

### 🎙️ Procesamiento de voz
- Reconocimiento automático de voz (ASR) mediante **Whisper**, **WhisperX** y **NVIDIA NeMo**
- Soporte para audio multilingüe (PL / EN / UA / RU / BY y más)
- Ejecución de modelos local y sin conexión (sin dependencia de la nube)
- Transcripción de alta calidad optimizada para grabaciones largas

### 🧩 Diarización de hablantes
- Diarización avanzada de hablantes mediante **pyannote** y **NeMo Diarization**
- Detección y segmentación automática de hablantes
- Soporte para conversaciones con múltiples hablantes (reuniones, entrevistas, llamadas)
- Motores y modelos de diarización configurables

### 🌍 Traducción multilingüe
- Traducción automática neuronal basada en **NLLB-200**
- Pipeline de traducción completamente sin conexión
- Selección flexible de idioma de origen y destino
- Diseñado para flujos de trabajo de OSINT y análisis multilingüe

### 🧠 Inteligencia y análisis
- Análisis de contenido asistido por IA mediante modelos **LLM** locales
- Transformación de voz y texto sin procesar en información estructurada
- Soporte para informes analíticos y flujos de trabajo orientados a inteligencia

### 📱 Análisis GSM / BTS
- Importación y análisis de **datos de facturación GSM** (CSV, XLSX, PDF)
- **Visualización interactiva en mapa** de ubicaciones BTS (Leaflet + OpenStreetMap)
- Soporte de **mapas sin conexión** mediante MBTiles (ráster PNG/JPG/WebP + vector PBF vía MapLibre GL)
- Múltiples vistas de mapa: todos los puntos, trayectoria, clústeres, viajes, cobertura BTS, mapa de calor, línea de tiempo
- **Selección de área** (círculo / rectángulo) para consultas espaciales
- **Capas superpuestas**: bases militares, aeropuertos civiles, sedes diplomáticas (datos integrados)
- **Importación KML/KMZ** — capas personalizadas desde Google Earth y otras herramientas GIS
- Capturas de pantalla del mapa con marca de agua (mapas en línea y sin conexión + todas las capas superpuestas)
- Gráfico de contactos, mapa de calor de actividad, análisis de contactos principales
- Reproductor de línea de tiempo con animación por mes/día

### 💰 AML — Análisis financiero
- Pipeline de análisis **Anti-Lavado de Dinero** para extractos bancarios
- Detección automática de bancos y análisis de PDF para bancos polacos:
  PKO BP, ING, mBank, Pekao SA, Santander, Millennium, Revolut (+ respaldo genérico)
- Soporte del formato de extractos MT940 (SWIFT)
- Normalización de transacciones, clasificación basada en reglas y puntuación de riesgo
- **Detección de anomalías**: línea base estadística + basada en ML (Isolation Forest)
- **Análisis de grafos** — visualización de red de contrapartes
- Análisis cruzado de cuentas para investigaciones multicuenta
- Resolución de entidades y memoria de contrapartes (etiquetas/notas persistentes)
- Análisis de gastos, patrones de comportamiento, categorización de comercios
- Análisis asistido por LLM (constructor de prompts para modelos Ollama)
- Generación de informes HTML con gráficos
- Perfiles de anonimización de datos para compartir de forma segura

### 🔗 Crypto — Análisis de transacciones blockchain *(experimental)*
- Análisis sin conexión de transacciones de criptomonedas **BTC** y **ETH**
- Importación desde CSV de **WalletExplorer.com** y múltiples formatos de exchanges (Binance, Etherscan, Kraken, Coinbase y más)
- Detección automática de formato a partir de firmas de columnas CSV
- Puntuación de riesgo con detección de patrones: peel chain, dust attack, round-trip, smurfing
- Base de datos de direcciones sancionadas por OFAC y búsqueda de contratos DeFi conocidos
- **Gráfico interactivo de flujo de transacciones** (Cytoscape.js)
- Gráficos: línea de tiempo de saldo, volumen mensual, actividad diaria, ranking de contrapartes (Chart.js)
- Análisis narrativo asistido por LLM vía Ollama
- *Este módulo se encuentra actualmente en fase de pruebas inicial — las funcionalidades y formatos de datos pueden cambiar*

### ⚙️ Gestión de GPU y recursos
- **Administrador de recursos GPU** integrado
- Programación y priorización automática de tareas (ASR, diarización, análisis)
- Ejecución segura de tareas concurrentes sin sobrecarga de GPU
- Respaldo en CPU cuando los recursos de GPU no están disponibles

### 📂 Flujo de trabajo basado en proyectos
- Organización de datos orientada a proyectos
- Almacenamiento persistente de audio, transcripciones, traducciones y análisis
- Flujos de trabajo analíticos reproducibles
- Separación de datos de usuario y procesos del sistema

### 📄 Informes y exportación
- Exportación de resultados a **TXT**, **HTML**, **DOC** y **PDF**
- Informes estructurados que combinan transcripción, diarización y análisis
- Informes financieros AML con gráficos e indicadores de riesgo
- Resultados listos para usar en investigación, documentación e investigaciones

### 🌐 Interfaz web
- Interfaz web moderna (**AISTATEweb**)
- Estado de tareas y registros en tiempo real
- Interfaz multilingüe (PL / EN)
- Diseñado para entornos independientes y multiusuario (próximamente)


* * *

## Requisitos

### Sistema (Linux)

Instale los paquetes base (ejemplo):
    sudo apt update -y
    sudo apt install -y python3 python3-venv python3-pip git

### Python

Recomendado: Python 3.11+.

* * *
## pyannote / Hugging Face (necesario para la diarización)

La diarización utiliza pipelines de **pyannote.audio** alojados en **Hugging Face Hub**. Algunos modelos de pyannote están **restringidos**, lo que significa que debe:
  * tener una cuenta en Hugging Face,
  * aceptar las condiciones de uso en las páginas de los modelos,
  * generar un token de acceso **READ** y proporcionarlo a la aplicación.

### Paso a paso (token + permisos)

  1. Cree o inicie sesión en su cuenta de Hugging Face.
  2. Abra las páginas de los modelos de pyannote requeridos y haga clic en **"Agree / Accept"** (condiciones de uso).
     Modelos típicos que puede necesitar aceptar (según la versión):
     * `pyannote/segmentation` (o `pyannote/segmentation-3.0`)
     * `pyannote/speaker-diarization` (o `pyannote/speaker-diarization-3.1`)
  3. Vaya a **Settings → Access Tokens** en Hugging Face y cree un nuevo token con el rol **READ**.
  4. Pegue el token en la configuración de AISTATE Web (o proporciónelo como variable de entorno — según su configuración).
* * *
## Instalación (Linux)

```bash
sudo apt update
sudo apt install -y ffmpeg
curl -fsSL https://ollama.com/install.sh | sh
```
```
mkdir -p ~/projects
cd ~/projects
git clone https://github.com/pawlict/AISTATEweb.git
cd AISTATEweb

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip wheel setuptools
pip install -r requirements.txt
```
* * *

## Ejecutar
```
python3 AISTATEweb.py
```
Ejemplo (uvicorn):
    python -m uvicorn webapp.server:app --host 0.0.0.0 --port 8000

Abrir en el navegador:
    http://127.0.0.1:8000

* * *
# AISTATEweb — Windows (WSL2 + GPU NVIDIA) Configuración

> **Importante:** En WSL2, el controlador de NVIDIA se instala **en Windows**, no dentro de Linux. **No** instale paquetes `nvidia-driver-*` dentro de la distribución WSL.

---

### 1. Lado de Windows

1. Habilite WSL2 (PowerShell: `wsl --install` o Características de Windows).
2. Instale el último **controlador de NVIDIA para Windows** (Game Ready / Studio) — esto proporciona soporte de GPU dentro de WSL2.
3. Actualice WSL y reinicie:
   ```powershell
   wsl --update
   wsl --shutdown
   ```

### 2. Dentro de WSL (se recomienda Ubuntu)

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git python3 python3-venv python3-pip ffmpeg
```

Verifique que la GPU sea visible:
```bash
nvidia-smi
```

### 3. Instalar AISTATEweb

```bash
mkdir -p ~/projects && cd ~/projects
git clone https://github.com/pawlict/AISTATEweb.git
cd AISTATEweb

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip setuptools wheel

# PyTorch con CUDA (ejemplo: cu128)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128

pip install -r requirements.txt
```

Verifique el acceso a la GPU:
```bash
python -c "import torch; print('CUDA:', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"
```

### 4. Ejecutar

```bash
python3 AISTATEweb.py
```
Abrir en el navegador: http://127.0.0.1:8000

### Solución de problemas

Si `nvidia-smi` no funciona dentro de WSL, asegúrese de que **no** haya instalado paquetes de NVIDIA para Linux. Elimínelos si están presentes:
```bash
sudo apt purge -y 'nvidia-*' 'libnvidia-*' && sudo apt autoremove --purge -y
```

---

## Referencias

- [NVIDIA: Guía de usuario de CUDA en WSL](https://docs.nvidia.com/cuda/wsl-user-guide/index.html)
- [Microsoft: Instalar WSL](https://learn.microsoft.com/windows/wsl/install)
- [PyTorch: Primeros pasos](https://pytorch.org/get-started/locally/)
- [pyannote.audio (Hugging Face)](https://huggingface.co/pyannote)
- [Whisper (OpenAI)](https://github.com/openai/whisper)
- [NLLB-200 (Meta)](https://huggingface.co/facebook/nllb-200-distilled-600M)
- [Ollama](https://ollama.com/)

---

"Este proyecto está licenciado bajo MIT (TAL CUAL). Los componentes de terceros tienen licencias independientes — consulte THIRD_PARTY_NOTICES.md."

## beta 3.7.2
- **Panel de analista** — nuevo panel lateral que reemplaza la barra lateral de notas en las páginas de transcripción y diarización
- **Notas en bloques con etiquetas** — las notas ahora pueden tener etiquetas de colores, mostradas como borde izquierdo en los segmentos
- **PDF de Revolut crypto** — analizador para extractos de criptomonedas de Revolut, integrado con el pipeline AML
- **Base de datos de tokens (TOP 200)** — clasificación de tokens conocidos/desconocidos para análisis de criptomonedas
- **Informes mejorados** — informes DOCX/HTML con gráficos, marcas de agua, conclusiones dinámicas, descripciones de secciones
- **Disparador ARIA** — disparador flotante arrastrable con persistencia de posición y ubicación inteligente del HUD
- Corregida la traducción atascada en 5% (caché de modelo de detección automática)
- Corregido el informe de traducción que perdía formato (saltos de línea colapsados)
- Corregidos resultados obsoletos de transcripción/diarización al subir nuevo audio
- Middleware sin caché para archivos estáticos JS/CSS

## beta 3.7.1
- **Análisis de criptomonedas — Binance** — análisis extendido de datos del exchange Binance
- Perfilado de comportamiento de usuario (10 patrones: HODLer, Scalper, Day Trader, Swing Trader, Staker, Whale, Institucional, Alpha Hunter, Meme Trader, Bagholder)
- 18 tarjetas de análisis forense: contrapartes internas, Pay C2C, direcciones on-chain, flujos de paso, monedas de privacidad, registros de acceso, tarjetas de pago + **NUEVO:** análisis temporal, cadenas de conversión de tokens, detección de structuring/smurfing, wash trading, fiat on/off ramp, análisis P2P, velocidad depósito-retiro, análisis de comisiones, análisis de redes blockchain, seguridad extendida (VPN/proxy)
- Eliminados todos los límites de registros — datos completos con tablas desplazables
- Los informes se descargan como archivos (HTML, TXT, DOCX)

## beta 3.7
- **Análisis de criptomonedas** *(experimental)* — módulo de análisis de transacciones blockchain sin conexión (BTC/ETH), importación CSV (WalletExplorer + 16 formatos de exchanges), puntuación de riesgo, detección de patrones, gráfico de flujo, gráficos Chart.js, narrativa LLM — actualmente en fase de pruebas exhaustivas
- Detección automática del idioma de origen al subir archivos y pegar texto (módulo de traducción)
- Exportación multilingüe (todos los idiomas traducidos a la vez)
- Corregidos nombres de archivo en exportación DOCX (problema con guiones bajos)
- Corregido error de síntesis de forma de onda MMS TTS
- Corregida la ausencia del idioma coreano en los resultados de traducción

## beta 3.6
- **Análisis GSM / BTS** — módulo completo de análisis de facturación GSM con mapas interactivos, línea de tiempo, clústeres, viajes, mapa de calor, gráfico de contactos
- **Análisis financiero AML** — pipeline anti-lavado de dinero: análisis de PDF (7 bancos polacos + MT940), detección de anomalías basada en reglas + ML, análisis de grafos, puntuación de riesgo, informes asistidos por LLM
- **Capas superpuestas del mapa** — bases militares, aeropuertos, sedes diplomáticas + importación personalizada KML/KMZ
- **Mapas sin conexión** — soporte MBTiles (ráster + vector PBF vía MapLibre GL)
- **Capturas de pantalla del mapa** — captura completa del mapa incluyendo todas las capas de tiles, superposiciones y marcadores KML
- Corregido el analizador KML/KMZ (error de elemento falsy en ElementTree)
- Corregida la captura de pantalla del canvas de MapLibre GL (preserveDrawingBuffer)
- Corregido el cambio de idioma en la página de información

## beta 3.5.1/3
- Corregido el guardado/asignación de proyectos.
- Mejorado el analizador para banca ING

## beta 3.5.0 (SQLite)
- Migración de JSON a SQLite

## beta 3.4.0
- Añadido multiusuario

## beta 3.2.3 (actualización de traducción)
- Añadido módulo de traducción
- Añadida página de configuración de NLLB
- Añadida la posibilidad de cambiar prioridades de tareas
- Añadido Chat LLM
- Análisis de sonido de fondo *(experimental)*

## beta 3.0 - 3.1
- Módulos LLM Ollama para análisis de datos introducidos
- Asignación / Programación de GPU (Actualización)

Esta actualización introduce un concepto de **Administrador de Recursos GPU** en la interfaz de usuario y el flujo interno para reducir el riesgo de **cargas de trabajo GPU superpuestas** (por ejemplo, ejecutar diarización + transcripción + análisis LLM al mismo tiempo).

### Qué problema resuelve
Cuando múltiples tareas de GPU se inician simultáneamente, puede provocar:
- agotamiento repentino de VRAM (OOM),
- reinicios del controlador / errores CUDA,
- procesamiento extremadamente lento debido a la contención,
- comportamiento inestable cuando varios usuarios ejecutan trabajos al mismo tiempo.

### Compatibilidad con versiones anteriores
- Sin cambios en la disposición funcional de las pestañas existentes.
- Solo se actualizaron la coordinación/admisión de GPU y el etiquetado de administración.

## beta 2.1 -2.2

- Cambio en la metodología de edición de bloques
- Esta actualización se centra en mejorar la observabilidad y usabilidad de los registros de la aplicación.
- Corrección: Revisión del registro (Whisper + pyannote) + Exportación a archivo
