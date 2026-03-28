# AISTATEweb Community (3.7.2 beta)

[![English](https://flagcdn.com/24x18/gb.png) English](README.md) | [![Polski](https://flagcdn.com/24x18/pl.png) Polski](README.pl.md) | [![한국어](https://flagcdn.com/24x18/kr.png) 한국어](README.ko.md) | [![Español](https://flagcdn.com/24x18/es.png) Español](README.es.md) | [![Français](https://flagcdn.com/24x18/fr.png) Français](README.fr.md) | [![中文](https://flagcdn.com/24x18/cn.png) 中文](README.zh.md) | [![Українська](https://flagcdn.com/24x18/ua.png) Українська](README.uk.md) | [![Deutsch](https://flagcdn.com/24x18/de.png) Deutsch](README.de.md)

![Version](https://img.shields.io/badge/Version-3.7.2%20beta-orange)
![Edition](https://img.shields.io/badge/Edition-Community-blue)
![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![Platform](https://img.shields.io/badge/Platform-Web-lightgrey)
![License](https://img.shields.io/badge/License-MIT-green)

* * *

AISTATEweb Community 是一款基于 Web 的音频转录、说话人分离、翻译、AI 驱动分析和结构化报告工具——完全离线运行，使用本地硬件。

#### 反馈 / 支持

如果您有任何问题、建议或功能需求，请联系我：**pawlict@proton.me**

* * *

## 🚀 主要功能

### 🎙️ 语音处理
- 使用 **Whisper**、**WhisperX** 和 **NVIDIA NeMo** 进行自动语音识别 (ASR)
- 支持多语言音频（PL / EN / UA / RU / BY 等）
- 离线运行本地模型（无需依赖云端）
- 针对长录音优化的高质量转录

### 🧩 说话人分离
- 使用 **pyannote** 和 **NeMo Diarization** 进行高级说话人分离
- 自动说话人检测与分割
- 支持多人对话（会议、访谈、通话）
- 可配置的分离引擎和模型

### 🌍 多语言翻译
- 基于 **NLLB-200** 的神经机器翻译
- 完全离线翻译流水线
- 灵活的源语言和目标语言选择
- 专为 OSINT 和多语言分析工作流设计

### 🧠 情报与分析
- 使用本地 **LLM 模型** 进行 AI 辅助内容分析
- 将原始语音和文本转化为结构化洞察
- 支持分析报告和情报导向工作流

### 📱 GSM / BTS 分析
- 导入和分析 **GSM 话单数据**（CSV、XLSX、PDF）
- 基于 Leaflet + OpenStreetMap 的 **BTS 位置交互式地图可视化**
- 通过 MBTiles 支持**离线地图**（光栅 PNG/JPG/WebP + 矢量 PBF，使用 MapLibre GL）
- 多种地图视图：全部点位、路径、聚类、行程、BTS 覆盖、热力图、时间线
- **区域选择**（圆形/矩形）用于空间查询
- **叠加图层**：军事基地、民用机场、外交驻地（内置数据）
- **KML/KMZ 导入** — 来自 Google Earth 和其他 GIS 工具的自定义叠加图层
- 带水印的地图截图（在线和离线地图 + 所有叠加图层）
- 联系人图谱、活动热力图、热门联系人分析
- 带月/日动画的时间线播放器

### 💰 AML — 金融分析
- 针对银行对账单的**反洗钱**分析流水线
- 自动银行检测和 PDF 解析，支持波兰银行：
  PKO BP、ING、mBank、Pekao SA、Santander、Millennium、Revolut（+ 通用回退）
- MT940 (SWIFT) 对账单格式支持
- 交易标准化、基于规则的分类和风险评分
- **异常检测**：统计基线 + 基于机器学习（Isolation Forest）
- **图分析** — 交易对手网络可视化
- 跨账户分析，用于多账户调查
- 实体解析和交易对手记忆（持久化标签/备注）
- 消费分析、行为模式、商户分类
- LLM 辅助分析（Ollama 模型的提示构建器）
- HTML 报告生成（含图表）
- 数据匿名化配置，用于安全分享

### 🔗 Crypto — 区块链交易分析 *（实验性）*
- 离线分析 **BTC** 和 **ETH** 加密货币交易
- 从 **WalletExplorer.com** CSV 和多种交易所格式（Binance、Etherscan、Kraken、Coinbase 等）导入
- 基于 CSV 列签名的自动格式检测
- 风险评分与模式检测：剥离链、粉尘攻击、往返交易、分拆交易
- OFAC 制裁地址数据库和已知 DeFi 合约查询
- 基于 Cytoscape.js 的交互式**交易流程图**
- 图表：余额时间线、月交易量、日活跃度、交易对手排名（Chart.js）
- 通过 Ollama 进行 LLM 辅助叙事分析
- *该模块目前处于早期测试阶段——功能和数据格式可能会变更*

### ⚙️ GPU 与资源管理
- 集成 **GPU 资源管理器**
- 自动任务调度和优先级排序（ASR、说话人分离、分析）
- 安全执行并发任务，避免 GPU 过载
- GPU 资源不可用时自动回退至 CPU

### 📂 基于项目的工作流
- 面向项目的数据组织
- 持久化存储音频、转录、翻译和分析结果
- 可复现的分析工作流
- 用户数据与系统进程分离

### 📄 报告与导出
- 导出结果为 **TXT**、**HTML**、**DOC** 和 **PDF**
- 结合转录、说话人分离和分析的结构化报告
- 含图表和风险指标的 AML 金融报告
- 可直接用于研究、文档编制和调查的输出

### 🌐 基于 Web 的界面
- 现代化 Web 用户界面 (**AISTATEweb**)
- 实时任务状态和日志
- 多语言界面（PL / EN）
- 为独立部署和多用户环境设计（即将推出）


* * *

## 系统要求

### 系统（Linux）

安装基础软件包（示例）：
    sudo apt update -y
    sudo apt install -y python3 python3-venv python3-pip git

### Python

推荐：Python 3.11+。

* * *
## pyannote / Hugging Face（说话人分离必需）

说话人分离使用托管在 **Hugging Face Hub** 上的 **pyannote.audio** 流水线。某些 pyannote 模型是**受限访问**的，这意味着您必须：
  * 拥有 Hugging Face 账号，
  * 在模型页面上接受用户条款，
  * 生成一个 **READ** 访问令牌并提供给应用程序。

### 分步说明（令牌 + 权限）

  1. 创建或登录您的 Hugging Face 账号。
  2. 打开所需的 pyannote 模型页面，点击 **"Agree / Accept"**（用户条款）。
     您可能需要接受的典型模型（取决于版本）：
     * `pyannote/segmentation`（或 `pyannote/segmentation-3.0`）
     * `pyannote/speaker-diarization`（或 `pyannote/speaker-diarization-3.1`）
  3. 前往 Hugging Face **Settings → Access Tokens**，创建一个角色为 **READ** 的新令牌。
  4. 将令牌粘贴到 AISTATE Web 设置中（或根据您的配置作为环境变量提供）。
* * *
## 安装（Linux）

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

## 运行
```
python3 AISTATEweb.py
```
示例（uvicorn）：
    python -m uvicorn webapp.server:app --host 0.0.0.0 --port 8000

在浏览器中打开：
    http://127.0.0.1:8000

* * *
# AISTATEweb — Windows (WSL2 + NVIDIA GPU) 安装指南

> **重要提示：** 在 WSL2 中，NVIDIA 驱动程序安装在 **Windows** 上，而不是 Linux 内部。请**不要**在 WSL 发行版中安装 `nvidia-driver-*` 软件包。

---

### 1. Windows 端

1. 启用 WSL2（PowerShell：`wsl --install` 或 Windows 功能）。
2. 安装最新的 **NVIDIA Windows 驱动程序**（Game Ready / Studio）— 这将为 WSL2 提供 GPU 支持。
3. 更新 WSL 并重启：
   ```powershell
   wsl --update
   wsl --shutdown
   ```

### 2. WSL 内部（推荐 Ubuntu）

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git python3 python3-venv python3-pip ffmpeg
```

验证 GPU 是否可见：
```bash
nvidia-smi
```

### 3. 安装 AISTATEweb

```bash
mkdir -p ~/projects && cd ~/projects
git clone https://github.com/pawlict/AISTATEweb.git
cd AISTATEweb

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip setuptools wheel

# 安装带 CUDA 支持的 PyTorch（示例：cu128）
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128

pip install -r requirements.txt
```

验证 GPU 访问：
```bash
python -c "import torch; print('CUDA:', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"
```

### 4. 运行

```bash
python3 AISTATEweb.py
```
在浏览器中打开：http://127.0.0.1:8000

### 故障排除

如果 `nvidia-smi` 在 WSL 中无法工作，请确认您**没有**安装 Linux NVIDIA 软件包。如有，请删除：
```bash
sudo apt purge -y 'nvidia-*' 'libnvidia-*' && sudo apt autoremove --purge -y
```

---

## 参考资料

- [NVIDIA: CUDA on WSL User Guide](https://docs.nvidia.com/cuda/wsl-user-guide/index.html)
- [Microsoft: Install WSL](https://learn.microsoft.com/windows/wsl/install)
- [PyTorch: Get Started](https://pytorch.org/get-started/locally/)
- [pyannote.audio (Hugging Face)](https://huggingface.co/pyannote)
- [Whisper (OpenAI)](https://github.com/openai/whisper)
- [NLLB-200 (Meta)](https://huggingface.co/facebook/nllb-200-distilled-600M)
- [Ollama](https://ollama.com/)

---

"本项目基于 MIT 许可证（按原样提供）。第三方组件单独授权——详见 THIRD_PARTY_NOTICES.md。"

## beta 3.7.2
- **分析师面板** — 新的侧边栏面板，替代转录和说话人分离页面中的笔记侧边栏
- **带标签的块笔记** — 笔记现在可以添加彩色标签，在片段上显示为左侧边框
- **Revolut 加密货币 PDF** — Revolut 加密货币对账单解析器，集成到 AML 流水线
- **代币数据库（TOP 200）** — 用于加密货币分析的已知/未知代币分类
- **改进的报告** — DOCX/HTML 报告支持图表、水印、动态结论和章节描述
- **ARIA 触发器** — 可拖拽的浮动触发器，支持位置持久化和智能 HUD 放置
- 修复翻译卡在 5% 的问题（自动检测模型缓存）
- 修复翻译报告丢失格式的问题（换行符被折叠）
- 修复上传新音频时转录/说话人分离结果过期的问题
- 静态 JS/CSS 文件添加无缓存中间件

## beta 3.7.1
- **加密货币分析 — Binance** — 扩展的 Binance 交易所数据分析
- 用户行为画像（10 种模式：HODLer、Scalper、Day Trader、Swing Trader、Staker、Whale、Institutional、Alpha Hunter、Meme Trader、Bagholder）
- 18 张取证分析卡片：内部交易对手、Pay C2C、链上地址、资金过桥流、隐私币、访问日志、支付卡 + **新增：** 时间分析、代币转换链、分拆/蚂蚁搬家检测、洗盘交易、法币出入金、P2P 分析、存取款速率、手续费分析、区块链网络分析、扩展安全（VPN/代理）
- 移除所有记录限制——完整数据搭配可滚动表格
- 报告下载为文件（HTML、TXT、DOCX）

## beta 3.7
- **加密货币分析** *（实验性）* — 离线区块链交易分析模块（BTC/ETH），CSV 导入（WalletExplorer + 16 种交易所格式），风险评分、模式检测、流程图、Chart.js 图表、LLM 叙事——目前处于深度测试阶段
- 上传文件和粘贴文本时自动检测源语言（翻译模块）
- 多语言导出（同时导出所有已翻译语言）
- 修复 DOCX 导出文件名问题（下划线问题）
- 修复 MMS TTS 波形合成错误
- 修复韩语在翻译结果中缺失的问题

## beta 3.6
- **GSM / BTS 分析** — 完整的 GSM 话单分析模块，包含交互式地图、时间线、聚类、行程、热力图、联系人图谱
- **AML 金融分析** — 反洗钱流水线：PDF 解析（7 家波兰银行 + MT940）、基于规则 + ML 异常检测、图分析、风险评分、LLM 辅助报告
- **地图叠加层** — 军事基地、机场、外交驻地 + 自定义 KML/KMZ 导入
- **离线地图** — MBTiles 支持（光栅 + PBF 矢量，通过 MapLibre GL）
- **地图截图** — 完整地图截取，包括所有瓦片图层、叠加层和 KML 标记
- 修复 KML/KMZ 解析器（ElementTree 假值元素 bug）
- 修复 MapLibre GL 画布截图（preserveDrawingBuffer）
- 修复信息页面语言切换问题

## beta 3.5.1/3
- 修复项目保存/分配问题。
- 改进 ING 银行解析器

## beta 3.5.0 (SQLite)
- JSON -> SQLite 迁移

## beta 3.4.0
- 新增多用户支持

## beta 3.2.3（翻译更新）
- 新增翻译模块
- 新增 NLLB 设置页面
- 新增任务优先级调整功能
- 新增 Chat LLM
- 背景声音分析 *（实验性）*

## beta 3.0 - 3.1
- 引入用于数据分析的 LLM Ollama 模块
- GPU 分配/调度（更新）

此更新在 UI 和内部流程中引入了 **GPU 资源管理器** 概念，以降低 **GPU 密集型工作负载重叠** 的风险（例如同时运行说话人分离 + 转录 + LLM 分析）。

### 此更新解决的问题
当多个 GPU 任务并发启动时，可能导致：
- 突发 VRAM 耗尽 (OOM)，
- 驱动程序重置 / CUDA 错误，
- 因资源争用导致处理极度缓慢，
- 多用户同时触发任务时行为不稳定。

### 向后兼容性
- 现有标签页的功能布局未做更改。
- 仅更新了 GPU 准入/协调和管理标签。

## beta 2.1 - 2.2

- 块编辑方法变更
- 此更新重点改进应用程序日志的可观察性和可用性。
- 修复：日志系统全面重构（Whisper + pyannote）+ 导出到文件
