# AISTATEweb Community (3.7.2 베타)

[![English](https://flagcdn.com/24x18/gb.png) English](README.md) | [![Polski](https://flagcdn.com/24x18/pl.png) Polski](README.pl.md) | [![한국어](https://flagcdn.com/24x18/kr.png) 한국어](README.ko.md) | [![Español](https://flagcdn.com/24x18/es.png) Español](README.es.md) | [![Français](https://flagcdn.com/24x18/fr.png) Français](README.fr.md)

![Version](https://img.shields.io/badge/버전-3.7.2%20beta-orange)
![Edition](https://img.shields.io/badge/에디션-Community-blue)
![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![Platform](https://img.shields.io/badge/플랫폼-Web-lightgrey)
![License](https://img.shields.io/badge/라이선스-MIT-green)

* * *

AISTATEweb Community는 오디오 전사, 화자 분리, 번역, AI 기반 분석 및 구조화된 보고서를 위한 웹 기반 도구입니다 — 완전 오프라인, 로컬 하드웨어에서 실행됩니다.

#### 피드백 / 지원

문의, 제안 또는 버그 신고: **pawlict@proton.me**

* * *

## 🚀 주요 기능

### 🎙️ 음성 처리
- **Whisper**, **WhisperX**, **NVIDIA NeMo**를 이용한 자동 음성 인식(ASR)
- 다국어 오디오 지원 (PL / EN / UA / RU / BY 등)
- 오프라인 로컬 모델 실행 (클라우드 불필요)
- 긴 녹음에 최적화된 고품질 전사

### 🧩 화자 분리
- **pyannote** 및 **NeMo Diarization**을 이용한 고급 화자 분리
- 자동 화자 감지 및 분할
- 다자 대화 지원 (회의, 인터뷰, 통화)
- 설정 가능한 분리 엔진 및 모델

### 🌍 다국어 번역
- **NLLB-200** 기반 신경 기계 번역
- 완전 오프라인 번역 파이프라인
- 유연한 소스 및 타겟 언어 선택
- OSINT 및 다국어 분석 워크플로우용 설계

### 🧠 분석 및 인텔리전스
- 로컬 **LLM 모델**을 이용한 AI 지원 콘텐츠 분석
- 원시 음성과 텍스트를 구조화된 인사이트로 변환
- 분석 보고서 및 인텔리전스 워크플로우 지원

### 📱 GSM / BTS 분석
- **GSM 빌링 데이터** 가져오기 및 분석 (CSV, XLSX, PDF)
- BTS 위치의 인터랙티브 **지도 시각화** (Leaflet + OpenStreetMap)
- MBTiles를 통한 **오프라인 지도** 지원 (래스터 PNG/JPG/WebP + 벡터 PBF via MapLibre GL)
- 다양한 지도 보기: 전체 포인트, 경로, 클러스터, 이동, BTS 커버리지, 히트맵, 타임라인
- **영역 선택** (원 / 사각형) 공간 쿼리
- **오버레이 레이어**: 군사 기지, 민간 공항, 외교 공관 (내장 데이터)
- **KML/KMZ 가져오기** — Google Earth 및 기타 GIS 도구의 사용자 정의 레이어
- 워터마크 포함 지도 스크린샷 (온라인 및 오프라인 지도 + 모든 오버레이)
- 연락처 그래프, 활동 히트맵, 상위 연락처 분석
- 월/일 애니메이션이 있는 타임라인 플레이어

### 💰 AML — 금융 분석
- 은행 명세서를 위한 **자금세탁방지** 분석 파이프라인
- 폴란드 은행 자동 감지 및 PDF 파싱:
  PKO BP, ING, mBank, Pekao SA, Santander, Millennium, Revolut (+ 일반 폴백)
- MT940 (SWIFT) 명세서 형식 지원
- 거래 정규화, 규칙 기반 분류, 위험 점수화
- **이상 감지**: 통계 기준선 + ML 기반 (Isolation Forest)
- **그래프 분석** — 거래 상대방 네트워크 시각화
- 다중 계좌 조사를 위한 교차 계좌 분석
- 엔터티 해결 및 거래 상대방 메모리 (라벨/노트)
- 지출 분석, 행동 패턴, 가맹점 분류
- LLM 지원 분석 (Ollama 모델용 프롬프트 빌더)
- 차트가 포함된 HTML 보고서 생성
- 안전한 공유를 위한 데이터 익명화 프로파일

### 🔗 Crypto — 블록체인 거래 분석 *(실험적)*
- **BTC** 및 **ETH** 암호화폐 거래의 오프라인 분석
- **WalletExplorer.com** CSV 및 다양한 거래소 형식에서 가져오기 (Binance, Etherscan, Kraken, Coinbase 등)
- CSV 열 시그니처를 통한 자동 형식 감지
- 패턴 감지를 통한 위험 점수화: peel chain, dust attack, round-trip, smurfing
- OFAC 제재 주소 데이터베이스 및 알려진 DeFi 컨트랙트 조회
- 인터랙티브 **거래 흐름 그래프** (Cytoscape.js)
- 차트: 잔액 타임라인, 월간 거래량, 일일 활동, 거래 상대방 순위 (Chart.js)
- Ollama를 통한 LLM 지원 내러티브 분석
- *이 모듈은 초기 테스트 단계입니다 — 기능 및 데이터 형식이 변경될 수 있습니다*

### ⚙️ GPU 및 리소스 관리
- 통합 **GPU Resource Manager**
- 자동 작업 스케줄링 및 우선순위 지정 (ASR, 분리, 분석)
- GPU 과부하 없는 동시 작업 안전 실행
- GPU 리소스 미사용 시 CPU 폴백

### 📂 프로젝트 기반 워크플로우
- 프로젝트 단위 데이터 구성
- 오디오, 전사, 번역, 분석의 영구 저장
- 재현 가능한 분석 워크플로우
- 사용자 데이터와 시스템 프로세스의 분리

### 📄 보고서 및 내보내기
- **TXT**, **HTML**, **DOC**, **PDF**로 결과 내보내기
- 전사, 분리, 분석을 결합한 구조화된 보고서
- 차트와 위험 지표가 포함된 AML 금융 보고서
- 연구, 문서화, 수사에 즉시 사용 가능한 출력물

### 🌐 웹 기반 인터페이스
- 모던 웹 UI (**AISTATEweb**)
- 실시간 작업 상태 및 로그
- 다국어 인터페이스 (PL / EN)
- 단독 및 다중 사용자 환경용 설계 (곧 출시)

* * *

## 요구 사항

### 시스템 (Linux)

기본 패키지 설치 (예시):
    sudo apt update -y
    sudo apt install -y python3 python3-venv python3-pip git

### Python

권장: Python 3.11+.

* * *
## pyannote / Hugging Face (화자 분리에 필요)

화자 분리는 **Hugging Face Hub**에 호스팅된 **pyannote.audio** 파이프라인을 사용합니다. 일부 pyannote 모델은 **게이트**되어 있어 다음이 필요합니다:
  * Hugging Face 계정,
  * 모델 페이지에서 사용 조건 동의,
  * **READ** 액세스 토큰 생성 및 앱에 제공.

### 단계별 안내 (토큰 + 권한)

  1. Hugging Face 계정을 만들거나 로그인합니다.
  2. 필요한 pyannote 모델 페이지를 열고 **"Agree / Accept"** (사용 조건)을 클릭합니다.
     동의가 필요한 일반적인 모델 (버전에 따라 다름):
     * `pyannote/segmentation` (또는 `pyannote/segmentation-3.0`)
     * `pyannote/speaker-diarization` (또는 `pyannote/speaker-diarization-3.1`)
  3. Hugging Face **Settings → Access Tokens**에서 **READ** 역할의 새 토큰을 생성합니다.
  4. AISTATE Web 설정에 토큰을 입력합니다 (또는 환경 변수로 제공).
* * *
## 설치 (Linux)

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

## 실행
```
python3 AISTATEweb.py
```
예시 (uvicorn):
    python -m uvicorn webapp.server:app --host 0.0.0.0 --port 8000

브라우저에서 열기:
    http://127.0.0.1:8000

* * *
# AISTATEweb — Windows (WSL2 + NVIDIA GPU) 설정

> **중요:** WSL2에서 NVIDIA 드라이버는 **Windows에** 설치됩니다 — Linux 내부가 아닙니다. WSL 배포판 내에 `nvidia-driver-*` 패키지를 설치하지 **마세요**.

---

### 1. Windows 측

1. WSL2 활성화 (PowerShell: `wsl --install` 또는 Windows 기능).
2. 최신 **NVIDIA Windows 드라이버** (Game Ready / Studio) 설치 — WSL2 내 GPU 지원을 제공합니다.
3. WSL 업데이트 및 재시작:
   ```powershell
   wsl --update
   wsl --shutdown
   ```

### 2. WSL 내부 (Ubuntu 권장)

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git python3 python3-venv python3-pip ffmpeg
```

GPU 확인:
```bash
nvidia-smi
```

### 3. AISTATEweb 설치

```bash
mkdir -p ~/projects && cd ~/projects
git clone https://github.com/pawlict/AISTATEweb.git
cd AISTATEweb

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip setuptools wheel

# CUDA가 포함된 PyTorch (예시: cu128)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128

pip install -r requirements.txt
```

GPU 접근 확인:
```bash
python -c "import torch; print('CUDA:', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"
```

### 4. 실행

```bash
python3 AISTATEweb.py
```
브라우저에서 열기: http://127.0.0.1:8000

### 문제 해결

WSL 내에서 `nvidia-smi`가 작동하지 않으면, Linux NVIDIA 패키지를 설치하지 **않았는지** 확인하세요. 있다면 제거:
```bash
sudo apt purge -y 'nvidia-*' 'libnvidia-*' && sudo apt autoremove --purge -y
```

---

## 참고 자료

- [NVIDIA: WSL의 CUDA 사용자 가이드](https://docs.nvidia.com/cuda/wsl-user-guide/index.html)
- [Microsoft: WSL 설치](https://learn.microsoft.com/windows/wsl/install)
- [PyTorch: 시작하기](https://pytorch.org/get-started/locally/)
- [pyannote.audio (Hugging Face)](https://huggingface.co/pyannote)
- [Whisper (OpenAI)](https://github.com/openai/whisper)
- [NLLB-200 (Meta)](https://huggingface.co/facebook/nllb-200-distilled-600M)
- [Ollama](https://ollama.com/)

---

"이 프로젝트는 MIT 라이선스 (AS IS)입니다. 서드파티 컴포넌트는 별도 라이선스를 따릅니다 — THIRD_PARTY_NOTICES.md를 참조하세요."

## 베타 3.7.2
- **분석가 패널** — 전사 및 화자 분리 페이지에서 노트 사이드바를 대체하는 새 사이드바 패널
- **태그가 있는 블록 노트** — 노트에 색상 태그를 추가할 수 있으며, 세그먼트에 왼쪽 테두리로 표시
- **Revolut 크립토 PDF** — AML 파이프라인과 통합된 Revolut 암호화폐 명세서 파서
- **토큰 데이터베이스 (TOP 200)** — 크립토 분석의 알려진/미확인 토큰 분류
- **향상된 보고서** — 차트, 워터마크, 동적 결론, 섹션 설명이 포함된 DOCX/HTML 보고서
- **ARIA 트리거** — 위치 유지 기능과 스마트 HUD 배치가 있는 드래그 가능한 플로팅 트리거
- 5%에서 멈추는 번역 수정 (모델 캐시 자동 감지)
- 번역 보고서 서식 손실 수정 (줄바꿈이 하나의 블록으로 합쳐짐)
- 새 오디오 업로드 시 오래된 전사/분리 결과 수정
- 정적 JS/CSS 파일용 no-cache 미들웨어

## 베타 3.7.1
- **암호화폐 분석 — Binance** — Binance 거래소 데이터의 확장된 분석
- 사용자 행동 프로파일링 (10가지 패턴: HODLer, Scalper, Day Trader, Swing Trader, Staker, Whale, Institutional, Alpha Hunter, Meme Trader, Bagholder)
- 18개 포렌식 분석 카드: 내부 거래 상대방, Pay C2C, 온체인 주소, pass-through 흐름, 프라이버시 코인, 접근 로그, 결제 카드 + **신규:** 시간 분석, 토큰 변환 체인, 구조화/smurfing 감지, wash trading, 법정화폐 on/off ramp, P2P 분석, 입출금 속도, 수수료 분석, 블록체인 네트워크 분석, 확장 보안 (VPN/proxy)
- 모든 레코드 제한 제거 — 스크롤 가능한 테이블의 전체 데이터
- 파일로 보고서 다운로드 (HTML, TXT, DOCX)

## 베타 3.7
- **크립토 분석** *(실험적)* — 오프라인 블록체인 거래 분석 모듈 (BTC/ETH), CSV 가져오기 (WalletExplorer + 16개 거래소 형식), 위험 점수화, 패턴 감지, 흐름 그래프, Chart.js 차트, LLM 내러티브 — 심층 테스트 단계
- 파일 업로드 및 텍스트 붙여넣기 시 소스 언어 자동 감지 (번역 모듈)
- 다국어 내보내기 (모든 번역된 언어 한 번에)
- DOCX 내보내기 파일명 수정 (밑줄 문제)
- MMS TTS 파형 합성 오류 수정
- 번역 결과에서 한국어 누락 수정

## 베타 3.6
- **GSM / BTS 분석** — 인터랙티브 지도, 타임라인, 클러스터, 이동, 히트맵, 연락처 그래프가 포함된 전체 GSM 빌링 분석 모듈
- **AML 금융 분석** — 자금세탁방지 파이프라인: PDF 파싱 (폴란드 은행 7곳 + MT940), 규칙 기반 + ML 이상 감지, 그래프 분석, 위험 점수화, LLM 지원 보고서
- **지도 오버레이** — 군사 기지, 공항, 외교 공관 + 사용자 정의 KML/KMZ 가져오기
- **오프라인 지도** — MBTiles 지원 (래스터 + MapLibre GL을 통한 PBF 벡터)
- **지도 스크린샷** — 모든 타일 레이어, 오버레이, KML 마커를 포함한 전체 지도 캡처
- KML/KMZ 파서 수정 (ElementTree falsy element 버그)
- MapLibre GL 캔버스 스크린샷 수정 (preserveDrawingBuffer)
- 정보 페이지 언어 전환 수정

## 베타 3.5.1/3
- 프로젝트 저장/할당 수정
- ING 은행 파서 개선

## 베타 3.5.0 (SQLite)
- JSON -> SQLite 마이그레이션

## 베타 3.4.0
- 다중 사용자 추가

## 베타 3.2.3 (번역 업데이트)
- 번역 모듈 추가
- NLLB 설정 페이지 추가
- 작업 우선순위 변경 기능 추가
- Chat LLM 추가
- 배경 사운드 분석 *(실험적)*

## 베타 3.0 - 3.1
- 데이터 분석을 위한 LLM Ollama 모듈 도입
- GPU 할당 / 스케줄링 (업데이트)

이 업데이트는 **겹치는 GPU 작업** (예: 동시 분리 + 전사 + LLM 분석)의 위험을 줄이기 위해 UI 및 내부 흐름에 **GPU Resource Manager** 개념을 도입합니다.

### 해결하는 문제
여러 GPU 작업이 동시에 시작되면 다음이 발생할 수 있습니다:
- 갑작스러운 VRAM 고갈 (OOM),
- 드라이버 리셋 / CUDA 오류,
- 리소스 경합으로 인한 극도로 느린 처리,
- 여러 사용자가 동시에 작업을 실행할 때 불안정한 동작.

### 하위 호환성
- 기존 탭의 기능 레이아웃에 변경 없음.
- GPU 관리/조정 및 관리자 라벨링만 업데이트됨.

## 베타 2.1 - 2.2

- 블록 편집 방법론 변경
- 애플리케이션 로그의 가시성 및 사용성 개선
- 수정: 로깅 개편 (Whisper + pyannote) + 파일 내보내기
