# AISTATE Web Community — 用户手册

> **版本：** Community（开源）· **版本号：** 3.7.2 beta
>
> Community 版本是 AISTATE Web 的免费全功能版本，适用于个人、教育和研究用途。它包含所有模块：转录、说话人分离、翻译、分析（LLM、AML、GSM、Crypto）、Chat LLM 和报告。

---

## 1. 项目

项目是使用 AISTATE 的核心元素。每个项目存储音频文件、转录结果、说话人分离、翻译、分析和笔记。

### 创建项目
1. 进入侧边栏的 **Projects** 选项卡。
2. 点击 **Create project** 并输入名称（例如 "Interview_2026_01"）。
3. 可选添加音频文件（WAV, MP3, M4A, FLAC, OGG, OPUS, MP4, AAC）。
4. 创建后，项目变为活动状态——它会显示在顶部栏中。

### 打开和管理
- 点击项目卡片以打开并将其设为活动状态。
- 将项目导出为 `.aistate` 文件（卡片上的上下文菜单）——可传输到其他计算机。
- 导入 `.aistate` 文件以从其他实例添加项目。

### 删除
- 从卡片的上下文菜单中删除项目。您可以选择文件覆写方式（快速 / 伪随机 / HMG IS5 / Gutmann）。

---

## 2. 转录

语音转文字模块。

### 使用方法
1. 确保您有一个包含音频文件的活动项目（或使用工具栏按钮添加一个）。
2. 选择 **ASR engine**（Whisper 或 NeMo）和 **model**（例如 `large-v3`）。
3. 选择录音 **language**（或 `auto` 进行自动检测）。
4. 点击 **Transcribe** 按钮（AI 图标）。

### 结果
- 文本以带有时间戳的块形式显示（`[00:00:05.120 - 00:00:08.340]`）。
- **点击** 一个块以播放该音频片段。
- **右键点击** 一个块以打开内联编辑器——修改文本和说话人名称。
- 所有更改会自动保存。

### 声音检测
- 如果您安装了声音检测模型（YAMNet, PANNs, BEATs），请在工具栏中启用 **Sound detection** 选项。
- 检测到的声音（咳嗽、笑声、音乐、警报等）将作为标记显示在文本中。

### 文本校对
- 使用 **Proofread** 功能通过 LLM 模型（例如 Bielik, PLLuM, Qwen3）自动校正转录结果。
- 在并排差异视图中比较原始文本和校正后的文本。

### 笔记
- **Notes** 面板（右侧）允许您添加全局笔记和各个块的笔记。
- 每个块旁边的笔记图标指示该块是否有关联的笔记。

### 报告
- 在工具栏中选择格式（HTML, DOC, TXT）并点击 **Save**——报告将保存到项目文件夹。

---

## 3. 说话人分离

说话人识别模块——"谁在何时说话"。

### 使用方法
1. 您需要一个包含音频文件的活动项目。
2. 选择 **diarization engine**：pyannote (audio) 或 NeMo diarization。
3. 可选设置说话人数量（或保持自动）。
4. 点击 **Diarize**。

### 结果
- 每个块都有一个说话人标签（例如 `SPEAKER_00`, `SPEAKER_01`）。
- **说话人映射**：将标签替换为姓名（例如 `SPEAKER_00` → "John Smith"）。
- 在字段中输入姓名 → 点击 **Apply mapping** → 标签将被替换。
- 映射保存在 `project.json` 中——重新打开项目时会自动加载。

### 编辑
- 右键点击一个块以打开编辑器：修改文本、说话人，播放片段。
- 笔记功能与转录模块中相同。

### 报告
- 从工具栏导出结果为 HTML / DOC / TXT。

---

## 4. 翻译

基于 NLLB 模型 (Meta) 的多语言翻译模块。

### 使用方法
1. 进入 **Translation** 选项卡。
2. 选择一个 **NLLB model**（必须在 NLLB Settings 中安装）。
3. 粘贴文本或导入文档（TXT, DOCX, PDF, SRT）。
4. 选择 **source language** 和 **target languages**（可以选择多个）。
5. 点击 **Generate**。

### 模式
- **Fast (NLLB)** — 较小的模型，翻译速度更快。
- **Accurate (NLLB)** — 较大的模型，翻译质量更好。

### 附加功能
- **Preserve formatting** — 保留段落和换行符。
- **Terminology glossary** — 使用专业术语词汇表。
- **TTS (Reader)** — 收听源文本和翻译结果（需要安装 TTS 引擎）。
- **Presets** — 预设配置（商务文档、科研论文、音频转录）。

### 报告
- 导出结果为 HTML / DOC / TXT。

---

## 5. Chat LLM

与本地 LLM 模型的聊天界面（通过 Ollama）。

### 使用方法
1. 进入 **Chat LLM**。
2. 从列表中选择一个 **model**（必须在 Ollama 中安装）。
3. 输入消息并点击 **Send**。

### 选项
- **System prompt** — 定义助手的角色（例如 "You are a lawyer specializing in Polish law"）。
- **Temperature** — 控制回复的创造性（0 = 确定性，1.5 = 非常有创造性）。
- **History** — 对话会自动保存。从侧边栏返回之前的对话。

---

## 6. 分析

分析选项卡包含四个模块：LLM、AML、GSM 和 Crypto。使用顶部的标签页在它们之间切换。

### 6.1 LLM 分析

使用 LLM 模型的内容分析模块。

1. 在侧边栏面板中选择 **data sources**（转录、说话人分离、笔记、文档）。
2. 选择 **prompts** — 模板或创建自定义提示词。
3. 点击 **Generate**（工具栏中的 AI 图标）。

#### 快速分析
- 转录完成后触发的自动轻量级分析。
- 使用较小的模型（在 LLM Settings 中配置）。

#### 深度分析
- 从选定的数据源和提示词进行完整分析。
- 支持自定义提示词：在 "Custom prompt" 字段中输入指令（例如 "Create meeting minutes with decisions"）。

### 6.2 AML 分析（反洗钱）

银行账单的金融分析模块。

1. 上传银行账单（PDF 或 MT940）——系统自动检测银行并解析交易。
2. 查看 **statement information**、已识别的账户和银行卡。
3. 对交易进行分类：neutral / legitimate / suspicious / monitoring。
4. 查看 **charts**：余额变化趋势、类别、渠道、月度趋势、每日活动、主要交易对手。
5. **ML Anomalies** — Isolation Forest 算法检测异常交易。
6. **Flow graph** — 交易对手关系可视化（布局：flow, amount, timeline）。
7. 向 LLM 模型提出有关金融数据的问题（"Question / instruction for analysis" 部分）。
8. 下载包含分析结果的 **HTML report**。

#### 分析师面板（AML）
- 左侧面板包含搜索、全局笔记和条目笔记。
- **Ctrl+M** — 快速为当前元素添加笔记。
- 标签：neutral, legitimate, suspicious, monitoring + 4 个自定义标签（双击重命名）。

### 6.3 GSM / BTS 分析

GSM 计费数据分析模块。

1. 加载计费数据（CSV, XLSX, PDF, ZIP 含多个文件）。
2. 查看 **summary**：记录数量、时间段、设备（IMEI/IMSI）。
3. **Anomalies** — 检测异常模式（夜间活动、漫游、双 SIM 卡等）。
4. **Special numbers** — 识别紧急号码、服务号码等。
5. **Contact graph** — 最频繁联系人的可视化（Top 5/10/15/20）。
6. **Records** — 所有记录的表格，支持筛选、搜索和列管理。
7. **Activity charts** — 每小时分布热力图、夜间和周末活动。
8. **BTS Map** — 交互式地图，支持多种视图：
   - All points, path, clusters, trips, border, BTS coverage, heatmap, timeline。
   - **Overlays**：军事基地、民用机场、外交机构。
   - **KML/KMZ import** — 来自 Google Earth 的自定义图层。
   - **Offline maps** — MBTiles 支持（raster + vector PBF）。
   - **Area selection** — 圆形 / 矩形空间查询。
9. **Detected locations** — 最频繁位置的聚类。
10. **Border crossings** — 出境行程检测。
11. **Overnight stays** — 过夜位置分析。
12. **Narrative analysis (LLM)** — 使用 Ollama 模型生成 GSM 分析报告。
13. **Reports** — 导出为 HTML / DOCX / TXT。分析笔记 DOCX 含图表。

#### 章节布局
- 分析师面板中的 **Customize layout** 按钮允许您更改各章节的顺序和可见性（拖拽 / 勾选取消勾选）。

#### 分析师面板（GSM）
- 左侧面板包含搜索、全局笔记和条目笔记。
- **Ctrl+M** — 快速为当前记录添加笔记。

#### 独立地图
- 无需计费数据即可打开地图（工具栏中的地图按钮）。
- 编辑模式——添加点、多边形、用户图层。

### 6.4 Crypto 分析 *（实验性）*

离线加密货币交易分析模块（BTC / ETH）及交易所数据。

#### 数据导入
1. 进入分析模块中的 **Crypto** 选项卡。
2. 点击 **Load data** 并选择 CSV 或 JSON 文件。
3. 系统自动检测格式：
   - **Blockchain**：WalletExplorer.com, Etherscan
   - **Exchanges**：Binance, Kraken, Coinbase, Revolut 等（16+ 种格式）
4. 加载后显示数据信息：交易数量、时间段、代币组合。

#### 数据视图
- **Exchange mode** — 交易所交易表格，包含类型（deposit, withdraw, swap, staking 等）。
- **Blockchain mode** — 链上交易表格，包含地址和金额。
- **Token portfolio** — 代币列表，包含描述、分类（known / unknown）和价值。
- **Transaction type dictionary** — 将鼠标悬停在类型上查看其描述（tooltip）。

#### 分类和审查
- 对交易进行分类：neutral / legitimate / suspicious / monitoring。
- 系统根据模式自动对部分交易进行分类。

#### 异常检测
- **ML anomaly detection** — 算法检测异常交易（大额交易、异常时间、可疑模式）。
- 异常类型：peel chain, dust attack, round-trip, smurfing, structuring。
- **OFAC** 受制裁地址数据库和已知 DeFi 合约查询。

#### 图表
- **Balance timeline** — 余额随时间的变化（支持对数归一化）。
- **Monthly volume** — 按月统计的交易总额。
- **Daily activity** — 按星期分布的交易量。
- **Counterparty ranking** — 最频繁的交易对手。

#### 流向图
- 交互式 **transaction graph** (Cytoscape.js) — 地址/交易对手之间的流向可视化。
- 点击节点查看详情。

#### 用户画像（Binance）
- 10 种行为模式：HODLer, Scalper, Day Trader, Swing Trader, Staker, Whale, Institutional, Alpha Hunter, Meme Trader, Bagholder。
- 18 张取证分析卡片（内部交易对手、链上地址、wash trading、P2P、手续费分析等）。

#### 叙事分析（LLM）
- 点击 **Generate analysis** → Ollama 模型将生成包含结论和建议的描述性报告。

#### 报告
- 从工具栏导出结果为 **HTML / DOCX / TXT**。

#### 分析师面板（Crypto）
- 左侧面板包含全局笔记和交易笔记。
- **Ctrl+M** — 快速为当前交易添加笔记。
- 标签：neutral, legitimate, suspicious, monitoring + 4 个自定义标签。

---

## 7. 日志

任务监控与系统诊断。

- 前往 **Logs** 选项卡查看所有任务的状态（转录、说话人分离、分析、翻译）。
- 将日志复制到剪贴板或保存到文件。
- 清除任务列表（不会删除项目）。

---

## 8. 管理面板

### GPU 设置
- 监控 GPU 显卡、显存、活动任务。
- 设置并发限制（每个 GPU 的槽位数、显存占用比例）。
- 查看和管理作业队列。
- 设置任务类型优先级（拖拽排序）。

### ASR 设置
- 安装 Whisper 模型（tiny → large-v3）。
- 安装 NeMo ASR 和说话人分离模型。
- 安装声音检测模型（YAMNet、PANNs、BEATs）。

### LLM 设置
- 浏览和安装 Ollama 模型（快速分析、深度分析、金融、校对、翻译、视觉/OCR）。
- 添加自定义 Ollama 模型。
- 配置令牌（Hugging Face）。

### NLLB 设置
- 安装 NLLB 翻译模型（distilled-600M、distilled-1.3B、base-3.3B）。
- 查看模型信息（大小、质量、要求）。

### TTS 设置
- 安装朗读引擎：Piper（快速，CPU）、MMS（1100+ 种语言）、Kokoro（最高质量）。
- 使用前测试语音效果。

---

## 9. 设置

- **界面语言** — 在 PL / EN / KO 之间切换。
- **Hugging Face 令牌** — pyannote 模型（受限模型）所必需。
- **默认 Whisper 模型** — 新转录任务的首选模型。

---

## 10. 用户管理（多用户模式）

如果启用了多用户模式：
- 管理员可以创建、编辑、封禁和删除用户账户。
- 新用户注册后需等待管理员审批。
- 每个用户被分配一个角色，该角色决定可用的模块。

---

## 11. 项目加密

AISTATE 允许对项目进行加密，以保护数据免受未经授权的访问。

### 配置（管理员）

在 **User Management → Security → Security Policy** 面板中，管理员可配置：

- **项目加密** — 启用/禁用加密功能。
- **加密方法** — 从以下三种方法中选择：

| 级别 | 算法 | 描述 |
|-------|-----------|-------------|
| **Light** | AES-128-GCM | 快速加密，防止随意访问 |
| **Standard** | AES-256-GCM | 默认级别 — 速度与安全性的平衡 |
| **Maximum** | AES-256-GCM + ChaCha20-Poly1305 | 双层加密，适用于敏感数据 |

- **强制加密** — 启用后，用户无法创建未加密的项目。

所选加密级别适用于用户后续创建的所有项目。

### 创建加密项目

创建项目时，会出现 **Encrypt project** 复选框，并显示当前加密方法的信息（例如 "AES-256-GCM"）。如果管理员启用了加密，该复选框默认为选中状态；如果强制加密，则为锁定状态。

### 导出与导入

- **导出**加密项目 — `.aistate` 文件始终是加密的。系统会要求输入**导出密码**（与账户密码不同）。
- **导入** — 系统自动检测 `.aistate` 文件是否已加密。如果是 — 则要求输入密码。导入后，项目将根据管理员当前的策略重新加密。
- 未加密的项目可以无需密码导出，或者选择"加密导出"选项。

### <span style="color:red">⚠ 访问恢复 — 分步操作流程</span>

<span style="color:red">每个加密项目都有一个随机加密密钥（Project Key），该密钥由用户的密钥（从其密码派生）保护。此外，项目密钥还由管理员的 **Master Key** 保护。管理员**无法单独解密项目** — 需要用户的参与。</span>

#### <span style="color:red">场景 1：用户忘记密码（自助恢复）</span>

<span style="color:red">用户拥有其恢复短语（创建账户时收到的 12 个单词）。</span>

<span style="color:red">**用户步骤：**</span>
<span style="color:red">1. 在登录界面，点击 **"Forgot password"**。</span>
<span style="color:red">2. 输入您的**恢复短语**（12 个单词，以空格分隔）。</span>
<span style="color:red">3. 系统验证短语 — 如果正确，将显示新密码表单。</span>
<span style="color:red">4. 设置**新密码**并确认。</span>
<span style="color:red">5. 系统自动使用新密码重新加密您所有加密项目的密钥。</span>
<span style="color:red">6. 使用新密码正常登录。</span>

<span style="color:red">**无需管理员介入** — 整个过程完全自动完成。</span>

#### <span style="color:red">场景 2：用户忘记密码但拥有恢复短语（管理员协助恢复）</span>

<span style="color:red">如果自助重置未成功或被策略禁用：</span>

<span style="color:red">**管理员步骤：**</span>
<span style="color:red">1. 打开 **User Management** → 找到该用户的账户。</span>
<span style="color:red">2. 点击 **"Generate recovery token"** — 系统生成一次性令牌（24 小时内有效）。</span>
<span style="color:red">3. 将令牌交付给用户（当面、电话或其他安全渠道）。</span>

<span style="color:red">**用户步骤：**</span>
<span style="color:red">1. 前往**访问恢复**页面（登录界面上的链接）。</span>
<span style="color:red">2. 输入从管理员处收到的**恢复令牌**。</span>
<span style="color:red">3. 输入您的**恢复短语**（12 个单词）。</span>
<span style="color:red">4. 设置**新密码**。</span>
<span style="color:red">5. 系统使用新密码重新加密项目密钥。</span>
<span style="color:red">6. 令牌使用后即失效。</span>

#### <span style="color:red">场景 3：用户丢失密码和恢复短语（Master Key 恢复）</span>

<span style="color:red">这是唯一需要使用 **Master Key** 的场景。</span>

<span style="color:red">**管理员步骤：**</span>
<span style="color:red">1. 打开 **User Management → Security → Encryption**。</span>
<span style="color:red">2. 输入您的**管理员密码**以解锁 Master Key。</span>
<span style="color:red">3. 选择丢失访问权限的用户账户。</span>
<span style="color:red">4. 点击 **"Emergency recovery"** — 系统使用 Master Key 解密该用户的项目密钥。</span>
<span style="color:red">5. 系统为该用户生成**新的恢复短语**。</span>
<span style="color:red">6. 系统生成**一次性恢复令牌**。</span>
<span style="color:red">7. 将令牌和新恢复短语交付给用户。</span>

<span style="color:red">**用户步骤：**</span>
<span style="color:red">1. 前往**访问恢复**页面。</span>
<span style="color:red">2. 输入管理员提供的**令牌**。</span>
<span style="color:red">3. 输入管理员提供的**新恢复短语**。</span>
<span style="color:red">4. 设置**新密码**。</span>
<span style="color:red">5. 系统使用新密码重新加密项目密钥。</span>

<span style="color:red">**重要：** 新恢复短语必须立即保存并存放在安全的位置！</span>

### <span style="color:red">⚠ Master Key 备份</span>

<span style="color:red">**警告：** 如果用户丢失了密码和恢复短语，且管理员也丢失了 Master Key — **加密项目中的数据将无法恢复**。没有任何"后门"。</span>

<span style="color:red">**管理员职责：**</span>
<span style="color:red">1. 初始化 Master Key 后，在加密面板中点击 **"Backup Master Key"**。</span>
<span style="color:red">2. 输入管理员密码 — 系统以 base64 格式显示密钥。</span>
<span style="color:red">3. **将密钥保存在离线介质上**（U 盘、保险柜中的打印件）— 不要存储在系统中或电子邮件中。</span>
<span style="color:red">4. 定期使用 **"Verify Master Key"** 按钮验证备份。</span>

<span style="color:red">**丢失 Master Key + 用户密码 + 恢复短语 = 永久性数据丢失。**</span>

### <span style="color:red">⚠ 在加密项目中搜索</span>

<span style="color:red">项目列表（名称、创建日期）始终可见。但是，**内容搜索**（转录、笔记、分析结果）需要解密数据，并且**仅在当前打开的（活动）项目中有效**。无法同时跨多个加密项目进行搜索。</span>

---

## 12. A.R.I.A. — AI 助手

浮动的 A.R.I.A. 按钮（右下角）可打开 AI 助手面板。

### 功能
- **AI 聊天** — 针对当前上下文（转录、分析、数据）提问。
- **自动上下文** — 助手自动包含当前打开页面的数据。
- **回复朗读**（TTS）— 收听助手的回复。
- **提示标签** — 针对当前模块量身定制的现成问题。
- **可拖拽** — A.R.I.A. 按钮可拖拽到屏幕任意位置（位置会被记住）。

---

## 13. 音频播放器

当项目包含音频文件时，音频播放器栏会出现在转录和说话人分离页面中。

- **播放 / 暂停** — 播放或停止录音。
- **跳转** ±5 秒（按钮或点击进度条）。
- **播放速度** — 0.5×、0.75×、1×、1.25×、1.5×、2×（保存在浏览器中）。
- **点击文本片段**可播放对应的音频片段。
- **波形图** — 带有片段标记的振幅可视化。

---

## 14. 搜索与片段编辑

### 文本搜索
- 在转录和说话人分离页面中，使用 **Ctrl+F** 或工具栏中的放大镜图标。
- 搜索会高亮匹配项并显示数量。
- 使用 ↑ ↓ 箭头在匹配项之间导航。

### 合并与拆分片段
- **合并片段** — 选择两个相邻的块，然后点击"合并"（工具栏图标）。
- **拆分片段** — 将光标放在某个块中，然后点击"拆分" → 块将在光标位置处被拆分。

---

## 15. 深色 / 浅色模式

- 点击侧边栏中的主题图标（太阳/月亮图标）。
- 选择会被记住在浏览器中。

---

## 键盘快捷键

| 快捷键 | 操作 |
|----------|--------|
| **Esc** | 关闭块编辑器 / 关闭搜索 |
| **Ctrl+F** | 打开文本搜索（转录 / 说话人分离） |
| **Ctrl+Enter** | 保存笔记 |
| **Ctrl+M** | 添加分析师笔记（AML / GSM / Crypto） |
| **右键点击** | 打开块编辑器（转录 / 说话人分离） |
| **点击片段** | 播放音频片段 |
