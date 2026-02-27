#!/usr/bin/env node
/**
 * 内容浓缩脚本
 *
 * 功能:
 * 1. 使用百炼 Qwen-Plus 浓缩章节内容
 * 2. 保持教师语言风格
 * 3. 分段生成，自然衔接
 * 4. 输出精讲文稿
 *
 * 用法: node condense_content.js <work_dir> [options]
 * 输入: chapters.json
 * 输出: condensed_scripts.json
 *
 * 环境变量:
 *   DASHSCOPE_API_KEY    百炼 API Key
 */

const fs = require('fs');
const path = require('path');
const { DashScopeClient } = require('./lib/dashscope');
const { buildCondensationPrompt, formatSlideContent } = require('./lib/prompts');

// 解析参数
const workDir = process.argv[2] || '.';
const options = {
  targetDuration: 150,  // 每章目标时长（秒）
  concurrency: 3,       // 并发数
  resume: true
};

// 解析额外参数
for (let i = 3; i < process.argv.length; i++) {
  const [key, value] = process.argv[i].split('=');
  if (key && value) {
    options[key] = isNaN(value) ? value : parseFloat(value);
  }
  if (key === '--output') {
    options.outputDir = value;
  }
}

// 使用新的统一 steps/ 目录结构
const scriptDir = options.outputDir || path.join(workDir, 'steps/2_文稿');
const inputPath = path.join(scriptDir, 'chapters.json');
const outputPath = path.join(scriptDir, 'condensed.json');

// API Key
const apiKey = process.env.DASHSCOPE_API_KEY;
if (!apiKey) {
  console.error('❌ 请设置环境变量 DASHSCOPE_API_KEY');
  process.exit(1);
}

const client = new DashScopeClient(apiKey);

console.log('✍️ 内容浓缩');
console.log('📁 工作目录:', workDir);
console.log('⚙️ 配置:', JSON.stringify(options, null, 2));

// 加载数据
function loadJSON(p) {
  if (!fs.existsSync(p)) {
    console.error(`❌ 文件不存在: ${p}`);
    return null;
  }
  return JSON.parse(fs.readFileSync(p, 'utf8'));
}

// 解析 LLM 响应
function parseScriptResponse(response, chapter) {
  try {
    // 尝试提取 JSON
    const jsonMatch = response.match(/\{[\s\S]*\}/);
    if (jsonMatch) {
      const parsed = JSON.parse(jsonMatch[0]);
      return {
        chapterId: chapter.id,
        title: chapter.title,
        script: parsed.script || '',
        keyPoints: parsed.keyPoints || [],
        transitionOut: parsed.transitionOut || '',
        targetDuration: options.targetDuration,
        wordCount: (parsed.script || '').length
      };
    }
  } catch (e) {
    console.log(`   ⚠️ JSON 解析失败，使用原始文本`);
  }

  // 降级: 使用原始文本
  return {
    chapterId: chapter.id,
    title: chapter.title,
    script: response,
    keyPoints: [],
    transitionOut: '',
    targetDuration: options.targetDuration,
    wordCount: response.length
  };
}

// 生成单章精讲文稿
async function generateChapterScript(chapter, previousTransition = '') {
  const slideContent = formatSlideContent(chapter.slideContent);

  const prompt = buildCondensationPrompt({
    chapterTitle: chapter.title,
    slideContent,
    coreSpeech: chapter.coreSpeech,
    previousPPTSummary: previousTransition,
    targetDuration: options.targetDuration
  });

  try {
    const response = await client.generateText(prompt, {
      maxTokens: 2048,
      temperature: 0.4
    });

    return parseScriptResponse(response, chapter);
  } catch (err) {
    console.error(`   ❌ 章节 ${chapter.id} 生成失败:`, err.message);
    return {
      chapterId: chapter.id,
      title: chapter.title,
      script: chapter.coreSpeech,  // 降级: 使用原始语音
      keyPoints: [],
      transitionOut: '',
      targetDuration: options.targetDuration,
      wordCount: chapter.coreSpeech.length,
      error: err.message
    };
  }
}

// 主流程
async function main() {
  // 加载章节
  const chaptersData = loadJSON(inputPath);
  if (!chaptersData || !chaptersData.chapters) {
    console.error('❌ 请先运行 extract_chapters.js');
    process.exit(1);
  }

  const chapters = chaptersData.chapters;
  console.log(`📚 加载 ${chapters.length} 个章节`);

  // 检查断点续传
  let scripts = [];
  let processedIds = new Set();

  if (options.resume && fs.existsSync(outputPath)) {
    const existing = loadJSON(outputPath);
    if (existing && existing.scripts) {
      scripts = existing.scripts;
      processedIds = new Set(scripts.map(s => s.chapterId));
      console.log(`📂 已加载 ${scripts.length} 个已完成的文稿`);
    }
  }

  // 待处理章节
  const pending = chapters.filter(ch => !processedIds.has(ch.id));
  console.log(`📊 待处理: ${pending.length} 个章节`);

  if (pending.length === 0) {
    console.log('✅ 所有章节已处理完成');
    return;
  }

  // 生成文稿
  const startTime = Date.now();
  let previousTransition = scripts.length > 0
    ? scripts[scripts.length - 1].transitionOut
    : '';

  for (let i = 0; i < pending.length; i++) {
    const chapter = pending[i];
    console.log(`\n📝 [${i + 1}/${pending.length}] 处理章节 ${chapter.id}: ${chapter.title.substring(0, 30)}...`);

    const script = await generateChapterScript(chapter, previousTransition);
    scripts.push(script);
    previousTransition = script.transitionOut;

    console.log(`   ✅ 生成完成: ${script.wordCount} 字`);

    // 每 3 章保存一次
    if ((i + 1) % 3 === 0 || i === pending.length - 1) {
      const output = {
        generatedAt: new Date().toISOString(),
        modelUsed: 'qwen-plus',
        totalDuration: scripts.reduce((sum, s) => sum + s.targetDuration, 0),
        scripts
      };
      fs.mkdirSync(scriptDir, { recursive: true });
      fs.writeFileSync(outputPath, JSON.stringify(output, null, 2));
    }
  }

  const elapsed = ((Date.now() - startTime) / 1000).toFixed(2);
  const totalWords = scripts.reduce((sum, s) => sum + s.wordCount, 0);

  console.log(`\n✅ 浓缩完成！`);
  console.log(`   总章节数: ${scripts.length}`);
  console.log(`   总字数: ${totalWords}`);
  console.log(`   预计时长: ${(scripts.length * options.targetDuration / 60).toFixed(1)} 分钟`);
  console.log(`   耗时: ${elapsed} 秒`);
  console.log(`📁 输出: ${outputPath}`);
}

main().catch(err => {
  console.error('❌ 错误:', err.message);
  process.exit(1);
});