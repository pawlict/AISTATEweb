# AISTATE Web — 信息

**AISTATE Web** (*Artificial Intelligence Speech‑To‑Analysis‑Translation‑Engine*) 是一款用于**语音转录**、**说话人分离**、**翻译**、**GSM/BTS分析**和**AML金融分析**的Web应用程序。

---

## 🚀 功能介绍

- **语音转录** — 音频 → 文本 (Whisper, WhisperX, NeMo)
- **说话人分离** — "谁在什么时候说话" + 说话人片段 (pyannote, NeMo)
- **翻译** — 文本 → 其他语言 (NLLB‑200，完全离线)
- **分析 (LLM / Ollama)** — 摘要、洞察、报告
- **GSM / BTS 分析** — 话单导入、基站地图、路线、聚类、时间线
- **金融分析 (AML)** — 银行账单解析、风险评分、异常检测
- **日志与进度** — 任务监控 + 诊断

---

## 🆕 3.7.1 beta 新功能

### 🔐 加密货币分析 — Binance XLSX
- 扩展了Binance交易所数据分析
- 用户行为画像（10种模式：HODLer、Scalper、Day Trader、Swing Trader、Staker、Whale、Institutional、Alpha Hunter、Meme Trader、Bagholder）
- 18张取证分析卡片：
  - 内部交易对手、Pay C2C、链上地址、资金流转、隐私币、访问日志、支付卡
  - **新增：** 时间维度分析（小时分布、突发活动、休眠期）、代币转换链、结构化/分散交易检测、洗盘交易、法币出入金分析、P2P分析、存取款速度、手续费分析、区块链网络分析、扩展安全分析（VPN/代理检测）

---

## 🆕 3.6 beta 新功能

### 📱 GSM / BTS 分析
- 导入话单数据 (CSV, XLSX, PDF)
- 交互式**基站地图**，支持多种视图：点、路径、聚类、行程、基站覆盖、热力图、时间线
- **离线地图** — MBTiles支持（栅格 PNG/JPG/WebP + 矢量 PBF，通过 MapLibre GL）
- **叠加图层**：军事基地、民用机场、外交机构（内置数据）
- **KML/KMZ导入** — 来自Google Earth和其他GIS工具的自定义图层
- 区域选择（圆形 / 矩形）用于空间查询
- 联系人图谱、活动热力图、常联系人分析
- 带水印的地图截图（在线和离线地图 + 所有叠加图层）

### 💰 金融分析 (AML)
- 银行账单的**反洗钱**分析流程
- 自动银行检测和PDF解析：PKO BP、ING、mBank、Pekao SA、Santander、Millennium、Revolut（+ 通用回退方案）
- MT940 (SWIFT) 账单格式支持
- 交易标准化、基于规则的分类和风险评分
- **异常检测**：统计基线 + 机器学习 (Isolation Forest)
- **图谱分析** — 交易对手网络可视化
- 跨账户分析，支持多账户调查
- 支出分析、行为模式、商户分类
- LLM辅助分析（Ollama模型的提示词构建器）
- 带图表的HTML报告
- 数据匿名化配置，便于安全共享

---

## 🆕 3.5.1 beta 新功能

- **文本校对** — 原文与校正文本的并排对比，模型选择器（Bielik、PLLuM、Qwen3），展开模式。
- **重新设计的项目视图** — 卡片网格布局，团队信息，按卡片邀请。
- 其他界面和稳定性修复。

---

## 🆕 3.2 beta 新功能

- **翻译模块 (NLLB)** — 本地多语言翻译（包括中文/英文/波兰语等）。
- **NLLB设置** — 模型选择、运行时选项、模型缓存可见性。

---

## 📦 模型下载来源

AISTATE Web **不**在代码仓库中附带模型权重。模型按需下载并在本地缓存（取决于模块）：

- **Hugging Face Hub**：pyannote + NLLB（标准HF缓存）。
- **NVIDIA NGC / NeMo**：NeMo ASR/说话人分离模型（NeMo/NGC缓存机制）。
- **Ollama**：由Ollama服务拉取的LLM模型。
---

## 🔐 安全与用户管理

AISTATE Web支持两种部署模式：

- **单用户模式** — 简化版，无需登录（本地/自托管）。
- **多用户模式** — 完整的认证、授权和账户管理（设计支持50-100名并发用户）。

### 👥 角色与权限

**用户角色**（模块访问权限）：
- Transkryptor, Lingwista, Analityk, Dialogista, Strateg, Mistrz Sesji

**管理角色：**
- **Architekt Funkcji** — 应用程序设置管理
- **Strażnik Dostępu** — 用户账户管理（创建、审批、封禁、重置密码）
- **Główny Opiekun（超级管理员）** — 对所有模块和管理功能拥有完全访问权限

### 🔑 安全机制

- **密码哈希**：PBKDF2-HMAC-SHA256（260,000次迭代）
- **密码策略**：可配置（无 / 基础 / 中等 / 强）；管理员始终要求强密码（12+字符，大小写混合，数字，特殊字符）
- **密码黑名单**：内置 + 管理员自定义列表
- **密码过期**：可配置（X天后强制更改）
- **账户锁定**：可配置的失败次数后锁定（默认5次），15分钟后自动解锁
- **速率限制**：登录和注册限流（每个IP每分钟5次）
- **会话**：安全令牌（secrets模块），HTTPOnly + SameSite=Lax cookie，可配置超时（默认8小时）
- **恢复短语**：12个单词的BIP-39助记词（约132位熵），用于自助密码恢复
- **用户封禁**：永久或临时，附带原因
- **安全头**：X-Content-Type-Options, X-Frame-Options, X-XSS-Protection, Referrer-Policy

### 📝 审计与日志

- 完整事件日志：登录、失败尝试、密码更改、账户创建/删除、封禁、解锁
- IP地址和浏览器指纹记录
- 基于文件的日志，按小时轮转 + SQLite数据库
- 用户登录历史 + 管理员完整审计追踪

### 📋 注册与审批

- 自助注册需管理员审批（Strażnik Dostępu角色）
- 首次登录时强制更改密码
- 恢复短语仅生成和显示一次

---

## ⚖️ 许可证

### 应用许可证

- **AISTATE Web**：**MIT License**（按原样提供）。

### 引擎/库（代码许可证）

- **OpenAI Whisper**：**MIT**。
- **pyannote.audio**：**MIT**。
- **WhisperX**：**MIT**（封装器/对齐器 — 取决于包版本）。
- **NVIDIA NeMo Toolkit**：**Apache 2.0**。
- **Ollama（服务端/CLI仓库）**：**MIT**。

### 模型许可证（权重/检查点）

> 模型权重的许可证与代码**分开**授权。请务必核实模型卡片/供应商条款。

- **Meta NLLB‑200 (NLLB)**：**CC‑BY‑NC 4.0**（非商业限制）。
- **pyannote管道 (HF)**：取决于具体模型；部分模型是**门控**的，需要在模型页面接受条款。
- **NeMo模型 (NGC/HF)**：取决于具体模型；部分检查点以**CC‑BY‑4.0**等许可证发布，而某些NGC模型声明受NeMo Toolkit许可证覆盖 — 请查看每个模型页面。
- **通过Ollama使用的LLM**：取决于具体模型，例如：
  - **Meta Llama 3**：**Meta Llama 3 Community License**（再分发/署名 + AUP）。
  - **Mistral 7B**：**Apache 2.0**。
  - **Google Gemma**：**Gemma Terms of Use**（合同条款 + 政策）。

### 地图与地理数据

- **Leaflet**（地图引擎）：**BSD‑2‑Clause** — https://leafletjs.com
- **MapLibre GL JS**（PBF矢量渲染）：**BSD‑3‑Clause** — https://maplibre.org
- **OpenStreetMap**（在线地图瓦片）：地图数据 © OpenStreetMap贡献者，**ODbL 1.0** — 需要署名
- **OpenMapTiles**（PBF瓦片方案）：**BSD‑3‑Clause**（方案）；数据使用ODbL
- **html2canvas**（截图）：**MIT**

### 重要提示

- 本页面为摘要。完整列表请参见代码仓库中的**THIRD_PARTY_NOTICES.md**。
- 用于商业/组织用途时，请特别注意**NLLB (CC‑BY‑NC)** 和您选择的LLM模型许可证。

---

## 💬 反馈/支持

问题、建议、功能请求：**pawlict@proton.me**
