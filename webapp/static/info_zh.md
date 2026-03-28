# AISTATE Web — 信息

**AISTATE Web**（*Artificial Intelligence Speech‑To‑Analysis‑Translation‑Engine*）是一款用于**语音转录**、**说话人分离**、**翻译**、**GSM/BTS 分析**和**AML 金融分析**的网页应用程序。

---

## 🚀 功能简介

- **语音转录** — 音频 → 文本（Whisper、WhisperX、NeMo）
- **说话人分离** — "谁在何时说话" + 说话人片段（pyannote、NeMo）
- **翻译** — 文本 → 其他语言（NLLB‑200，完全离线）
- **分析（LLM / Ollama）** — 摘要、洞察、报告
- **GSM / BTS 分析** — 话单导入、基站地图、路线、聚类、时间线
- **金融分析（AML）** — 银行对账单解析、风险评分、异常检测
- **日志与进度** — 任务监控 + 诊断

---

## 🆕 3.7.1 beta 新功能

### 🔐 加密货币分析 — Binance XLSX
- 扩展了 Binance 交易所数据分析
- 用户行为画像（10 种模式：HODLer、Scalper、Day Trader、Swing Trader、Staker、Whale、Institutional、Alpha Hunter、Meme Trader、Bagholder）
- 18 张取证分析卡片：
  - 内部交易对手、Pay C2C、链上地址、资金穿透流、隐私币、访问日志、支付卡
  - **新增：** 时间分析（小时分布、突发活动、休眠期）、代币转换链、分拆/蚂蚁搬家检测、洗售交易、法币出入金分析、P2P 分析、存取款速度、手续费分析、区块链网络分析、扩展安全分析（VPN/代理检测）

---

## 🆕 3.6 beta 新功能

### 📱 GSM / BTS 分析
- 导入话单数据（CSV、XLSX、PDF）
- 交互式**基站地图**，提供多种视图：点位、路径、聚类、出行、基站覆盖、热力图、时间线
- **离线地图** — MBTiles 支持（栅格 PNG/JPG/WebP + 矢量 PBF，通过 MapLibre GL）
- **叠加图层**：军事基地、民用机场、外交驻地（内置数据）
- **KML/KMZ 导入** — 来自 Google Earth 及其他 GIS 工具的自定义图层
- 区域选择（圆形 / 矩形）用于空间查询
- 联系人图谱、活动热力图、热门联系人分析
- 地图截图，带水印（在线和离线地图 + 所有叠加图层）

### 💰 金融分析（AML）
- 针对银行对账单的**反洗钱**分析管道
- 自动银行识别和 PDF 解析：PKO BP、ING、mBank、Pekao SA、Santander、Millennium、Revolut（+ 通用回退）
- MT940（SWIFT）对账单格式支持
- 交易标准化、基于规则的分类和风险评分
- **异常检测**：统计基线 + 机器学习（Isolation Forest）
- **图谱分析** — 交易对手网络可视化
- 跨账户分析，用于多账户调查
- 支出分析、行为模式、商户分类
- LLM 辅助分析（为 Ollama 模型提供提示构建器）
- 带图表的 HTML 报告
- 数据匿名化配置，用于安全共享

---

## 🆕 3.5.1 beta 新功能

- **文本校对** — 原文与校正文本的并排差异对比，模型选择器（Bielik、PLLuM、Qwen3），展开模式。
- **重新设计的项目视图** — 卡片网格布局、团队信息、逐卡邀请。
- 其他 UI 和稳定性修复。

---

## 🆕 3.2 beta 新功能

- **翻译模块（NLLB）** — 本地多语言翻译（包括中文/波兰语/英语等）。
- **NLLB 设置** — 模型选择、运行时选项、模型缓存可见性。

---

## 📦 模型下载来源

AISTATE Web **不会**在代码仓库中附带模型权重。模型按需下载并在本地缓存（取决于模块）：

- **Hugging Face Hub**：pyannote + NLLB（标准 HF 缓存）。
- **NVIDIA NGC / NeMo**：NeMo ASR/说话人分离模型（NeMo/NGC 缓存机制）。
- **Ollama**：由 Ollama 服务拉取的 LLM 模型。
---

## 🔐 安全与用户管理

AISTATE Web 支持两种部署模式：

- **单用户模式** — 简化版，无需登录（本地 / 自托管）。
- **多用户模式** — 完整的身份验证、授权和账户管理（设计支持 50–100 并发用户）。

### 👥 角色与权限

**用户角色**（模块访问权限）：
- Transkryptor、Lingwista、Analityk、Dialogista、Strateg、Mistrz Sesji

**管理角色：**
- **Architekt Funkcji** — 应用程序设置管理
- **Strażnik Dostępu** — 用户账户管理（创建、审批、封禁、重置密码）
- **Główny Opiekun（超级管理员）** — 拥有所有模块和管理功能的完整访问权限

### 🔑 安全机制

- **密码哈希**：PBKDF2-HMAC-SHA256（260,000 次迭代）
- **密码策略**：可配置（无 / 基础 / 中等 / 强）；管理员始终要求强密码（12+ 字符，大小写混合、数字、特殊字符）
- **密码黑名单**：内置 + 管理员自定义列表
- **密码过期**：可配置（X 天后强制修改）
- **账户锁定**：可配置的失败尝试次数后锁定（默认 5 次），15 分钟后自动解锁
- **速率限制**：登录和注册限流（每个 IP 每分钟 5 次）
- **会话**：安全令牌（secrets 模块），HTTPOnly + SameSite=Lax Cookie，可配置超时（默认 8 小时）
- **恢复短语**：12 个 BIP-39 助记词（约 132 位熵），用于自助密码恢复
- **用户封禁**：永久或临时，附带原因
- **安全头**：X-Content-Type-Options、X-Frame-Options、X-XSS-Protection、Referrer-Policy

### 📝 审计与日志

- 完整事件日志：登录、失败尝试、密码修改、账户创建/删除、封禁、解锁
- IP 地址和浏览器指纹记录
- 基于文件的日志，按小时轮转 + SQLite 数据库
- 用户登录历史 + 管理员完整审计轨迹

### 📋 注册与审批

- 自助注册，需管理员审批（Strażnik Dostępu 角色）
- 首次登录时强制修改密码
- 恢复短语生成后仅显示一次

---

## ⚖️ 许可协议

### 应用许可

- **AISTATE Web**：**MIT License**（按原样提供）。

### 引擎/库（代码许可）

- **OpenAI Whisper**：**MIT**。
- **pyannote.audio**：**MIT**。
- **WhisperX**：**MIT**（包装器/对齐器 — 依赖于具体版本）。
- **NVIDIA NeMo Toolkit**：**Apache 2.0**。
- **Ollama（服务器/CLI 仓库）**：**MIT**。

### 模型许可（权重/检查点）

> 模型权重的许可与代码**分开**授权。请务必核实模型卡片/提供商条款。

- **Meta NLLB‑200 (NLLB)**：**CC‑BY‑NC 4.0**（非商业限制）。
- **pyannote 管道（HF）**：取决于具体模型；部分为**门控**模型，需在模型页面接受条款。
- **NeMo 模型（NGC/HF）**：取决于具体模型；部分检查点以 **CC‑BY‑4.0** 发布，部分 NGC 模型声明受 NeMo Toolkit 许可覆盖 — 请查看每个模型页面。
- **通过 Ollama 使用的 LLM**：取决于具体模型，例如：
  - **Meta Llama 3**：**Meta Llama 3 Community License**（再分发/署名 + AUP）。
  - **Mistral 7B**：**Apache 2.0**。
  - **Google Gemma**：**Gemma Terms of Use**（合同条款 + 政策）。

### 地图与地理数据

- **Leaflet**（地图引擎）：**BSD‑2‑Clause** — https://leafletjs.com
- **MapLibre GL JS**（PBF 矢量渲染）：**BSD‑3‑Clause** — https://maplibre.org
- **OpenStreetMap**（在线地图瓦片）：地图数据 © OpenStreetMap 贡献者，**ODbL 1.0** — 需注明来源
- **OpenMapTiles**（PBF 瓦片架构）：**BSD‑3‑Clause**（架构）；数据遵循 ODbL
- **html2canvas**（截图）：**MIT**

### 重要说明

- 本页为摘要。完整列表请参阅代码仓库中的 **THIRD_PARTY_NOTICES.md**。
- 商业/组织使用时，请特别注意 **NLLB (CC‑BY‑NC)** 和您所选 LLM 模型的许可协议。

---

## 💬 反馈/支持

问题、建议、功能请求：**pawlict@proton.me**
