---
name: condense-video
description: 课程视频内容提炼。结合语音转录和PPT OCR分析，从长视频中提取核心知识，排除课堂互动和闲聊，生成精要版本和课程大纲。触发词：精要提炼、课程浓缩、内容总结、提取干货
---

<!--
input: 视频文件 (*.mp4)
output: 精要视频、课程大纲、章节摘要
pos: 完整的内容提炼流程（包含转录）

架构守护者：一旦我被修改，请同步更新：
1. ../README.md 的 Skill 清单
2. /CLAUDE.md 路由表
-->

# 精要提炼 v2

> 从课程视频中提取核心知识，结合语音和PPT内容分析

## 环境准备

### 前置依赖

- **Node.js** 22 (运行 JS 脚本)
- **Python 3.11+** (运行 PPT 提取脚本)
- **FFmpeg** (视频/音频处理)
- **Edge TTS** (可选，用于免费 TTS)
- **DashScope API Key** (用于 ASR、OCR、AI 分类、TTS)

### 安装依赖

```bash
cd scripts/

# Node.js 依赖（当前无外部依赖）
npm install ws axios form-data

# Python 虚拟环境
python -m venv venv

# Windows 激活虚拟环境
venv\Scripts\activate
# Linux/Mac 激活虚拟环境
# source venv/bin/activate

# 安装 Python 依赖
pip install -r requirements.txt
```

**requirements.txt 内容**：
```
opencv-python>=0.4.0
Pillow>=9.0.0
imagehash>=4.3.0
```

### 环境变量

```bash
# 阿里云 DashScope API Key（用于 ASR、OCR、AI 分类、TTS）
export DASHSCOPE_API_KEY=sk-xxx

# 或在 scripts/.env 文件中配置
echo "DASHSCOPE_API_KEY=sk-xxx" > scripts/.env
```

### 可选工具

```bash
# Edge TTS (免费 TTS，无需 API Key)
pip install edge-tts
```

## 快速使用

```bash
# 完整运行（转录 → 分类 → 浓缩 → TTS → 合成）
node run.js lecture.mp4

# 指定 TTS 引擎和音色
node run.js lecture.mp4 --tts-engine=dashscope --voice=Cherry
node run.js lecture.mp4 --tts-engine=edgetts --voice=zh-CN-XiaoxiaoNeural

# 跳过已有步骤
node run.js lecture.mp4 --skip-transcribe --skip-ocr
```

**TTS 引擎说明**：
- `dashscope` (默认)：阿里云千问 TTS，音色自然，支持 Cherry/Serena/Ethan 等音色
- `edgetts`：Edge TTS，完全免费，音色丰富

### 方式二：分步执行

```
用户: 帮我提炼这个课程视频
用户: 把这个视频浓缩成干货
用户: 提取这个视频的核心内容
```

## 输出目录结构

```
output/
└── YYYY-MM-DD_视频名/
    └── 精要提炼/
        └── steps/                  # 统一的步骤目录
            ├── 1_转录/             # 语音转录
            ├── 2_文稿/             # 文稿处理（分类、章节、浓缩）
            ├── 3_音频/             # TTS 音频
            ├── 4_视频/             # 最终输出视频
            │   └── condensed_course.mp4   # 带配音的精要视频
            └── 5_PPT/              # PPT 关键帧和 OCR
```

**最终输出**: `steps/4_视频/condensed_course.mp4` - 带 AI 配音的精要视频

**注意**: 旧版本的多级目录结构 (0_PPT/, 1_转录/, 1_分类/, 2_结构/, 3_总结/, 4_输出/) 仍然兼容，但新运行将使用统一的 `steps/` 目录。

## 完整流程

```
0. 创建输出目录
    ↓
1. 提取音频 (ffmpeg)
    ↓
2. 上传音频获取公网 URL (uguu.se)
    ↓
3. DashScope ASR 转录（paraformer-v2）
    ↓
4. 转录结果格式转换 + 智能分句
    ↓
5. PPT 关键帧提取 (ffmpeg scene detect)
    ↓
6. PPT OCR 识别 (DashScope VL)
    ↓
7. 内容分类（语音 + PPT 融合）
    ↓
8. 章节切分（基于 PPT 切换）
    ↓
9. 内容总结（核心要点提取）
    ↓
10. 文本浓缩（AI 生成精要文本）
    ↓
11. TTS 配音（DashScope CosyVoice）
    ↓
12. 智能剪辑（删除非核心内容）
    ↓
13. 生成精要版视频 + 配音版 + 课程大纲
```

## 执行步骤

### 步骤 0: 创建输出目录

```bash
# 变量设置
VIDEO_PATH="/path/to/视频.mp4"
VIDEO_NAME=$(basename "$VIDEO_PATH" .mp4)
DATE=$(date +%Y-%m-%d)
BASE_DIR="output/${DATE}_${VIDEO_NAME}/精要提炼"

# 创建子目录
mkdir -p "$BASE_DIR/0_PPT/frames/images"
mkdir -p "$BASE_DIR/1_转录"
mkdir -p "$BASE_DIR/1_分类"
mkdir -p "$BASE_DIR/2_结构"
mkdir -p "$BASE_DIR/3_总结"
mkdir -p "$BASE_DIR/4_输出"
mkdir -p "$BASE_DIR/配文"

# 在script下创建虚拟环境
cd "$SKILL_DIR/scripts"
python -m venv venv
"./venv/Scripts/pip.exe" install opencv-python Pillow imagehash
```

### 步骤 1-3: 语音转录

#### 1.1 提取音频

```bash
cd 1_转录

# 提取音频（文件名有冒号需加 file: 前缀）
ffmpeg -i "file:$VIDEO_PATH" -vn -acodec libmp3lame -y audio.mp3
```

#### 1.2 上传获取公网 URL

```bash
# 使用 uguu.se 获取公网 URL（免费，无需注册）
curl -s -F "files[]=@audio.mp3" https://uguu.se/upload
# 返回: {"success":true,"files":[{"url":"https://h.uguu.se/xxx.mp3"}]}
```

#### 1.3 DashScope ASR 转录

```bash
# 设置 API Key（需要申请阿里云 DashScope）
export DASHSCOPE_API_KEY=your-key-here

# 调用转录脚本
node "$SKILL_DIR/dashscope_transcribe.js" "https://h.uguu.se/xxx.mp3"
# 输出: result.json
```

**⚠️ DashScope ASR 重要说明**：

DashScope paraformer-v2 API **不支持直接的分句参数**。API 返回的是：
- 单个长 utterance（整个音频）
- 字级别时间戳 (`word_timestamp: true`)
- 标点符号恢复 (`punctuation: true`)

**解决方案**：使用后处理的智能分句（见步骤 4）

### 步骤 4: 转录结果转换 + 智能分句

```bash
cd ../1_分类

# 运行转换脚本（包含智能分句）
node "$SKILL_DIR/lib/convert_transcript.js" \
    "../1_转录" \
    "."
```

**智能分句规则**：
1. **标点符号分句**：遇到 `。！？.!?` 时分句
2. **长静音分句**：间隔 > 0.5 秒时分句
3. **输出格式**：
   - `subtitles_words.json`: 字级别字幕 + 静音标记
   - `sentences.txt`: 句子列表（idx|startIdx-endIdx|text）

**分句示例**：
```
原始: 92分钟单个utterance
     ↓ 智能分句
结果: ~200个句子（基于标点和静音）
```

### 步骤 5: PPT 关键帧提取

```bash
cd ../0_PPT

# 使用 Python 脚本（更精确）
python "$SKILL_DIR/extract_frames.py" \
    --input "$VIDEO_PATH" \
    --output frames/images \
    --threshold 0.4
```

### 步骤 6: PPT OCR 识别

```bash
# 使用 DashScope VL 识别
python "$SKILL_DIR/ocr_slides.py" \
    --input frames/images \
    --output ocr_results.json \
    --structure
```

**PPT 数据结构**：
```json
{
  "slides": [
    {
      "frameId": 0,
      "framePath": "frames/images/frame_00000.jpg",
      "timestamp": 0.0,
      "ocrText": "第三章 控制系统的时域分析\n3.1 时域分析基础",
      "structure": {
        "title": "控制系统的时域分析",
        "subtitles": ["3.1 时域分析基础"],
        "formulas": [],
        "keyTerms": ["时域分析", "控制系统"]
      }
    }
  ]
}
```

### 步骤 7: 内容分类（语音 + PPT 融合）

```bash
cd ../1_分类

# 运行分类脚本
node "$SKILL_DIR/classify_content.js" ".."
```

**分类标签**：

| 标签 | 说明 | 处理 | 信号来源 |
|------|------|------|----------|
| `core` | 核心知识、定义、公式 | 必留 | PPT + 语音 |
| `explain` | 解释说明、举例 | 可选 | 语音 |
| `interact` | 课堂互动、提问 | 建议删 | 语音 |
| `chat` | 闲聊、跑题 | 必删 | 语音 |
| `transition` | 过渡语 | 可删 | 语音 |

**融合策略**：
1. **时间对齐**：将 PPT 内容与对应时间段的语音对齐
2. **交叉验证**：
   - 语音 + PPT 有对应标题 → `core` (高置信度)
   - 语音说"作业/考试" + PPT 无相关 → `chat`
   - 语音提问/点名 → `interact`
3. **快速预判**（基于规则）：
   - 短句 "哈啊嗯" → `chat`
   - "谁来说/举手" → `interact`
   - PPT 术语匹配 → `core`

### 步骤 8: 章节切分（基于 PPT 切换）

```bash
cd ../2_结构

# 运行章节切分脚本
node "$SKILL_DIR/refine_course.js" ".."
```

**章节识别规则**：

1. **PPT 切换点**（最可靠）
   - 场景切换检测 → 新 PPT
   - 每次新 PPT = 潜在新章节

2. **PPT 标题识别**
   - OCR 提取的大号字体、居中文字
   - "第X章"、"第X节"等显式标记

3. **语音辅助判断**
   - "下面我们讲"、"接下来"等过渡语
   - 主题关键词聚类

**输出格式**：
```json
{
  "chapters": [
    {
      "id": 1,
      "title": "典型环节与传递函数",
      "pptSlides": [1, 2, 3],
      "startTime": 0.0,
      "endTime": 120.5,
      "duration": 120.5,
      "coreSentences": 25,
      "keyFormulas": ["G(s) = 1/(Ts+1)"]
    }
  ]
}
```

### 步骤 9: 内容总结

```bash
cd ../3_总结

# 基于分类结果和章节结构生成总结
node "$SKILL_DIR/condense_content.js" ".."
```

**总结生成策略**：

1. **公式提取优先级**：
   - PPT OCR 识别的公式（最准确）
   - 语音中描述的公式（辅助验证）

2. **概念定义优先级**：
   - PPT 中的定义性文字
   - 语音中的"XXX是XXX"句式

3. **章节摘要模板**：
```markdown
### 第一章：[PPT标题]

**PPT 内容**：
- 标题：控制系统的时域分析
- 公式：`G(s) = Y(s)/R(s)`
- 关键术语：传递函数、增益、转角频率

**语音讲解要点**：
- 传递函数的标准形式化简方法
- 增益的计算步骤
```

**输出文件**：
- `summary.md` - 完整课程总结
- `key_points.md` - 核心要点列表

### 步骤 10: 文本浓缩（AI 生成精要文本）

```bash
cd ../配文

# 基于分类结果，只保留 core 和 explain 内容
# 生成适合 TTS 的精要文本
node "$SKILL_DIR/condense_content.js" \
    --mode essential \
    --output condensed.txt
```

**浓缩规则**：
- 只保留 `core` 和 `explain` 标签的句子
- 删除 `interact`、`chat`、`transition`
- 保持逻辑连贯性，添加必要的过渡

### 步骤 11: TTS 配音

```bash
# 使用 DashScope 千问 TTS（默认）
node "$SKILL_DIR/generate_tts.js" \
    --input condensed.json \
    --output tts_audio/ \
    --engine dashscope \
    --voice Cherry \
    --concurrency 3

# 或使用 Edge TTS（完全免费）
node "$SKILL_DIR/generate_tts.js" \
    --input condensed.json \
    --output tts_audio/ \
    --engine edgetts \
    --voice zh-CN-XiaoxiaoNeural
```

**DashScope 千问 TTS 可用音色**：
- `Cherry` (芊悦) - 阳光积极、亲切自然小姐姐（推荐）
- `Serena` (苏瑶) - 温柔知性、富有亲和力的女性声音
- `Ethan` (晨煦) - 阳光开朗、富有朝气的男性声音

**Edge TTS 常用音色**：
- `zh-CN-XiaoxiaoNeural` - 晓晓（女声，温柔）
- `zh-CN-YunxiNeural` - 云希（男声，阳光）
- `zh-CN-XiaoyiNeural` - 晓伊（女声，亲切）

**TTS 参数**：
```javascript
{
  engine: 'dashscope',      // 引擎：dashscope | edgetts
  voice: 'Cherry',          // 音色名称
  model: 'qwen3-tts-flash', // DashScope 模型
  maxLength: 300,           // 单段最大字数（DashScope 限制 600）
  concurrency: 3            // 并发数
}
```

### 步骤 12-13: 智能剪辑 + 最终输出

```bash
cd 4_输出

# 生成精要版（仅保留核心知识）
node "$SKILL_DIR/smart_cut.js" ".." "$VIDEO_PATH" "essential"
```

**剪辑模式**：

| 模式 | 保留 | 删除 | 节省 |
|------|------|------|------|
| `essential` | core | interact/chat/transition | ~35% |

## 配置

### API Keys

```bash
# 阿里云 DashScope（ASR + AI 分类）
export DASHSCOPE_API_KEY=sk-xxx

# 或创建 .env 文件
cat > ~/.claude/skills/videocut/.env << EOF
DASHSCOPE_API_KEY=sk-xxx
EOF
```

### 分类规则

自定义内容分类规则，编辑 `规则/` 目录下的 markdown 文件：

```
规则/
├── 1-内容分类.md      # 各类型内容的判断标准（core/explain/interact/chat/transition）
├── 2-结构提取.md      # 章节识别规则（基于PPT切换）
├── 3-总结生成.md      # 摘要生成模板
└── 4-PPT分析.md       # PPT OCR 和结构化规则
```

**规则文件格式**：
```markdown
# 1-内容分类.md

## core（核心知识）

### 判断标准
- PPT 有对应标题或公式
- 包含定义性句式（"XXX是XXX"、"XXX定义为"）
- 语音讲解 PPT 内容

### 示例
- "传递函数的定义是零初始条件下输出与输入之比"
- PPT标题: "传递函数定义"
```

### 分类配置

```javascript
// classify_content.js 中的配置
{
  concurrency: 10,      // 并发数
  batchSize: 50,        // 批处理大小
  model: 'qwen-plus',   // 分类模型
  resume: true          // 断点续传
}
```

## 依赖

| 依赖 | 用途 | 安装方式 |
|------|------|----------|
| FFmpeg | 音频提取、关键帧、视频剪辑 | `brew install ffmpeg` |
| Node.js | 脚本运行 | nodejs.org |

## 关键脚本说明

| 脚本 | 功能 | 输入 | 输出 |
|------|------|------|------|
| `dashscope_transcribe.js` | ASR 转录 | audio URL | result.json |
| `lib/convert_transcript.js` | 格式转换+智能分句 | result.json | subtitles_words.json, sentences.txt |
| `extract_frames.py` | PPT 关键帧提取 | video.mp4 | frames/*.jpg |
| `ocr_slides.js` | PPT OCR 识别 | frames/*.jpg | ocr_results.json, slides.json |
| `classify_content.js` | 内容分类（语音+PPT融合） | sentences.txt, slides.json | segments.json, classification.md |
| `refine_course.js` | 章节切分（基于PPT） | segments.json, slides.json | chapters.json, 大纲.md |
| `condense_content.js` | 文本浓缩 | segments.json | condensed.txt, summary.md |
| `generate_tts.js` | TTS 配音生成 | condensed.txt | tts_audio.mp3 |
| `smart_cut.js` | 智能剪辑 | segments.json, video.mp4 | 精要版.mp4, 大纲.md, cut_info.json |
| `lib/dashscope.js` | DashScope API 封装 | - | ASR/TTS/LLM 统一接口 |

## 常见问题

### Q: 如何提高分类准确度？

A: 调整 `classify_content.js` 中的参数：
- 降低 `concurrency` 提高稳定性
- 使用更强的模型（如 `qwen-turbo`）
- 添加用户习惯规则（见 `用户习惯/` 目录）

### Q: TTS 生成的语音如何与视频同步？

A: 使用 FFmpeg 的音视频合成：
```bash
ffmpeg -i "精要版.mp4" -i "tts_audio.mp3" \
  -map 0:v -map 1:a \
  -c:v copy -c:a aac -shortest \
  "配音版.mp4"
```

### Q: 如何选择 TTS 音色？

A: 有两种 TTS 引擎可选：

**DashScope 千问 TTS**（默认，音质更好）：
- `Cherry` (芊悦) - 阳光积极、亲切自然小姐姐（推荐）
- `Serena` (苏瑶) - 温柔知性、富有亲和力的女性声音
- `Ethan` (晨煦) - 阳光开朗、富有朝气的男性声音

**Edge TTS**（完全免费，音色丰富）：
- `zh-CN-XiaoxiaoNeural` - 晓晓（女声，温柔）
- `zh-CN-YunxiNeural` - 云希（男声，阳光）
- `zh-CN-XiaoyiNeural` - 晓伊（女声，亲切）

使用方法：
```bash
# DashScope
node run.js lecture.mp4 --tts-engine=dashscope --voice=Cherry

# Edge TTS
node run.js lecture.mp4 --tts-engine=edgetts --voice=zh-CN-XiaoxiaoNeural
```

### Q: 章节切分不准确的怎么办？

A: 调整 `规则/2-结构提取.md` 中的规则：
1. 增加 PPT 切换检测的灵敏度
2. 添加语音中的过渡词识别
3. 手动指定章节标题关键词

A: 尝试以下方案：
1. 提高关键帧分辨率（`-vf scale=2560:-2`）
2. 使用云端 OCR API（百度/腾讯）
3. 调整场景切换阈值（`--threshold 0.3`）
