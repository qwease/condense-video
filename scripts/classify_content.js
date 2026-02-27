#!/usr/bin/env node
/**
 * 内容分类脚本（语音 + PPT 融合）
 *
 * 功能：
 * 1. 加载语音转录结果和 PPT OCR 结果
 * 2. 时间对齐，交叉验证
 * 3. AI 分类（core/explain/interact/chat/transition）
 * 4. 并发处理 + 限流
 * 5. 输出分类结果
 *
 * 用法: node classify_content.js <work_dir> [options]
 * 输入: subtitles_words.json, sentences.txt, slides.json
 * 输出: segments.json, classification.md
 */

const fs = require('fs');
const path = require('path');
const https = require('https');

const DASHSCOPE_BASE = 'dashscope.aliyuncs.com';

// 解析参数
const workDir = process.argv[2] || '.';
const options = {
  concurrency: 10,          // 并发数
  model: 'qwen3.5-flash',       // 分类模型（用文本模型即可）
  resume: true,
};

for (let i = 3; i < process.argv.length; i++) {
  const [key, value] = process.argv[i].split('=');
  if (key && value) {
    options[key] = isNaN(value) ? value : parseFloat(value);
  }
}

// API Key
const apiKey = process.env.DASHSCOPE_API_KEY;
if (!apiKey) {
  console.error('❌ 请设置环境变量 DASHSCOPE_API_KEY');
  process.exit(1);
}

// HTTP POST 请求
function httpPost(hostname, reqPath, headers, body) {
  return new Promise((resolve, reject) => {
    const req = https.request({
      hostname,
      path: reqPath,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...headers
      }
    }, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        if (res.statusCode === 200) {
          resolve(JSON.parse(data));
        } else {
          reject(new Error(`HTTP ${res.statusCode}: ${data}`));
        }
      });
    });

    req.on('error', reject);
    req.write(JSON.stringify(body));
    req.end();
  });
}

// 并发控制器
class ConcurrencyController {
  constructor(limit) {
    this.limit = limit;
    this.active = 0;
    this.queue = [];
  }

  async run(task) {
    while (this.active >= this.limit) {
      await new Promise(resolve => this.queue.push(resolve));
    }
    this.active++;
    try {
      return await task();
    } finally {
      this.active--;
      const next = this.queue.shift();
      if (next) next();
    }
  }
}

// 简单限流
let lastRequestTime = 0;
const MIN_INTERVAL = 100; // 100ms 间隔

async function rateLimitedRequest(task) {
  const now = Date.now();
  const elapsed = now - lastRequestTime;
  if (elapsed < MIN_INTERVAL) {
    await new Promise(r => setTimeout(r, MIN_INTERVAL - elapsed));
  }
  lastRequestTime = Date.now();
  return task();
}

// 加载数据
function loadData(workDir) {
  // 语音转录 - 使用新的 steps/ 结构
  const subtitlesPath = path.join(workDir, 'steps/2_文稿/subtitles_words.json');
  const sentencesPath = path.join(workDir, 'steps/2_文稿/sentences.txt');

  // PPT 数据 - 使用新的 steps/ 结构
  const slidesPath = path.join(workDir, 'steps/5_PPT/frames/slides.json');

  const data = {
    words: [],
    sentences: [],
    slides: []
  };

  // 加载字幕
  if (fs.existsSync(subtitlesPath)) {
    data.words = JSON.parse(fs.readFileSync(subtitlesPath, 'utf8'));
    console.log(`📝 加载 ${data.words.length} 个字幕元素`);
  }

  // 加载句子
  if (fs.existsSync(sentencesPath)) {
    const lines = fs.readFileSync(sentencesPath, 'utf8').split('\n').filter(Boolean);
    data.sentences = lines.map(line => {
      const [idx, range, text] = line.split('|');
      const [start, end] = range.split('-').map(Number);
      return {
        idx: parseInt(idx),
        startIdx: start,
        endIdx: end,
        text: text,
        startTime: data.words[start]?.start || 0,
        endTime: data.words[end]?.end || 0
      };
    });
    console.log(`📝 加载 ${data.sentences.length} 个句子`);
  }

  // 加载 PPT
  if (fs.existsSync(slidesPath)) {
    const slidesData = JSON.parse(fs.readFileSync(slidesPath, 'utf8'));
    data.slides = slidesData.slides || [];
    console.log(`📊 加载 ${data.slides.length} 个 PPT 帧`);
  }

  return data;
}

// 时间对齐：找到句子对应的 PPT
function alignWithPPT(sentence, slides) {
  const sentenceTime = sentence.startTime;

  // 找到时间上最近的 PPT
  let matchedSlide = null;
  for (let i = slides.length - 1; i >= 0; i--) {
    if (slides[i].timestamp <= sentenceTime) {
      matchedSlide = slides[i];
      break;
    }
  }

  return matchedSlide;
}

// 计算文本相关性
function calculateRelevance(text1, text2) {
  if (!text1 || !text2) return 0;

  const words1 = new Set(text1.toLowerCase().split(/\s+/));
  const words2 = new Set(text2.toLowerCase().split(/\s+/));

  let intersection = 0;
  for (const word of words1) {
    if (words2.has(word)) intersection++;
  }

  return intersection / Math.max(words1.size, 1);
}

// AI 分类
async function classifySentence(sentence, slide, model) {
  const prompt = `分析以下课程内容，判断其类型。

【语音内容】
${sentence.text}

${slide ? `【对应PPT内容】
标题: ${slide.structure?.title || '无'}
关键术语: ${(slide.structure?.keyTerms || []).join(', ')}
公式: ${(slide.structure?.formulas || []).join(', ')}` : '【无PPT内容】'}

分类标准：
- core: 核心知识点、定义、公式、定理、重要概念（PPT有对应内容时优先判断）
- explain: 对核心内容的解释、举例说明
- interact: 师生互动、提问、回答、点名、课堂讨论
- chat: 闲聊、跑题、与课程无关的内容（作业讨论、考试话题、个人轶事）
- transition: 纯过渡语、"那么"、"接下来"、"所以说"等无实质内容

返回 JSON: {"reason": "简短理由", "label": "类型", "confidence": 0.0-1.0}`;

  try {
    const response = await httpPost(
      DASHSCOPE_BASE,
      '/compatible-mode/v1/chat/completions',
      {
        'Authorization': `Bearer ${apiKey}`
      },
      {
        model: model,
        messages: [{ role: 'user', content: prompt }],
        parameters: {
          temperature: 0.3,
          response_format: {"type": "json_object"}
        }
      }
    );

    const content = response.choices?.[0]?.message?.content || response.output?.text || '';

    // 解析 JSON
    const jsonMatch = content.match(/{[\s\S]*}/);
    if (jsonMatch) {
      return JSON.parse(jsonMatch[0]);
    }

    return { label: 'explain', confidence: 0.5, reason: '解析失败' };
  } catch (err) {
    return { label: 'explain', confidence: 0.3, reason: `API错误: ${err.message}` };
  }
}

// 批量分类
async function classifyBatch(sentences, slides, options) {
  const controller = new ConcurrencyController(options.concurrency);
  const results = [];

  let completed = 0;
  const startTime = Date.now();

  const tasks = sentences.map((sentence, index) => {
    return controller.run(async () => {
      return rateLimitedRequest(async () => {
        const slide = alignWithPPT(sentence, slides);

        classification = await classifySentence(sentence, slide, options.model);

        const result = {
          idx: sentence.idx,
          text: sentence.text,
          startIdx: sentence.startIdx,
          endIdx: sentence.endIdx,
          startTime: sentence.startTime,
          endTime: sentence.endTime,
          label: classification.label,
          confidence: classification.confidence,
          reason: classification.reason,
          slideId: slide?.frameId || null,
          slideTitle: slide?.structure?.title || null
        };

        completed++;

        if (completed % 10 === 0) {
          const elapsed = (Date.now() - startTime) / 1000;
          const speed = completed / elapsed;
          const remaining = (sentences.length - completed) / speed;
          console.log(`📊 进度: ${completed}/${sentences.length} (${(completed/sentences.length*100).toFixed(1)}%) - 剩余: ${remaining.toFixed(0)}秒`);
        }

        return result;
      });
    });
  });

  return Promise.all(tasks);
}

// 快速预判（基于规则）
function quickClassify(sentence, slide) {
  const text = sentence.text;

  // 短句判断
  if (text.length <= 3) {
    if (/^[哈啊嗯哦]+$/.test(text)) {
      return { label: 'chat', confidence: 0.95, reason: '笑声/语气词' };
    }
    if (/^(那|对|是|好|行)$/.test(text)) {
      return { label: 'transition', confidence: 0.9, reason: '单字过渡' };
    }
  }

  // 互动判断
  if (/谁(来|说|答)|点名|提问|举手|听懂(了|吗)|对不对|是不是/.test(text)) {
    return { label: 'interact', confidence: 0.9, reason: '课堂互动' };
  }

  // 闲聊判断
  if (/作业|考试|平时分|成绩|上次课|下次课/.test(text)) {
    return { label: 'chat', confidence: 0.85, reason: '课堂事务' };
  }

  // 核心内容判断（有PPT支持）
  if (slide && slide.structure) {
    const pptTerms = slide.structure.keyTerms || [];
    const pptTitle = slide.structure.title || '';

    // 语音包含 PPT 关键术语
    for (const term of pptTerms) {
      if (text.includes(term)) {
        return { label: 'core', confidence: 0.85, reason: `匹配PPT术语: ${term}` };
      }
    }

    // 语音包含 PPT 标题
    if (pptTitle && text.includes(pptTitle)) {
      return { label: 'core', confidence: 0.9, reason: '匹配PPT标题' };
    }
  }

  // 定义性语句
  if (/(是|称为|定义为|等于|叫做).{0,5}的/.test(text)) {
    return { label: 'core', confidence: 0.7, reason: '定义性语句' };
  }

  return { label: 'explain', confidence: 0.5, reason: '需要AI判断' };
}

// 生成统计报告
function generateReport(results) {
  const stats = {
    core: 0,
    explain: 0,
    interact: 0,
    chat: 0,
    transition: 0
  };

  let coreDuration = 0;
  let totalDuration = 0;

  for (const r of results) {
    stats[r.label]++;
    const duration = r.endTime - r.startTime;
    totalDuration += duration;
    if (r.label === 'core') coreDuration += duration;
  }

  const total = results.length;

  return `# 内容分类统计

## 概览

| 类型 | 句子数 | 占比 | 说明 |
|------|--------|------|------|
| 核心知识 | ${stats.core} | ${(stats.core/total*100).toFixed(1)}% | 必留 |
| 解释说明 | ${stats.explain} | ${(stats.explain/total*100).toFixed(1)}% | 可选 |
| 课堂互动 | ${stats.interact} | ${(stats.interact/total*100).toFixed(1)}% | 建议删 |
| 闲聊跑题 | ${stats.chat} | ${(stats.chat/total*100).toFixed(1)}% | 必删 |
| 过渡语 | ${stats.transition} | ${(stats.transition/total*100).toFixed(1)}% | 可删 |

## 时长分析

- 总时长: ${(totalDuration/60).toFixed(1)} 分钟
- 核心知识: ${(coreDuration/60).toFixed(1)} 分钟 (${(coreDuration/totalDuration*100).toFixed(1)}%)

## 剪辑建议

**精要版**（仅保留核心知识）：
- 删除互动+闲聊+过渡语
- 可节省约 ${((totalDuration - coreDuration)/60).toFixed(1)} 分钟

**完整版**（保留核心+解释）：
- 删除互动+闲聊
- 可节省约 ${((stats.interact + stats.chat) * 2 / 60).toFixed(1)} 分钟
`;
}

// 主流程
async function main() {
  console.log('🏷️ 内容分类（语音 + PPT 融合）');
  console.log('📁 工作目录:', workDir);

  const outputDir = path.join(workDir, 'steps/2_文稿');
  fs.mkdirSync(outputDir, { recursive: true });

  // 加载数据
  const data = loadData(workDir);

  if (data.sentences.length === 0) {
    console.error('❌ 没有找到句子数据');
    process.exit(1);
  }

  // 检查断点续传
  const resultsPath = path.join(outputDir, 'segments.json');
  let results = [];

  if (options.resume && fs.existsSync(resultsPath)) {
    results = JSON.parse(fs.readFileSync(resultsPath, 'utf8'));
    console.log(`📂 已加载 ${results.length} 个已完成的结果`);

    if (results.length === data.sentences.length) {
      console.log('✅ 所有句子已分类完成');
      return;
    }
  }

  // 分类
  const startTime = Date.now();
  results = await classifyBatch(data.sentences, data.slides, options);

  // 保存结果
  fs.writeFileSync(resultsPath, JSON.stringify(results, null, 2));

  // 生成报告
  const report = generateReport(results);
  fs.writeFileSync(path.join(outputDir, 'classification.md'), report);

  const elapsed = ((Date.now() - startTime) / 1000).toFixed(2);
  console.log(`\n✅ 分类完成！耗时 ${elapsed} 秒`);
  console.log(`📁 输出: ${resultsPath}`);
}

main().catch(err => {
  console.error('❌ 错误:', err.message);
  process.exit(1);
});
