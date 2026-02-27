#!/usr/bin/env node
/**
 * TTS 配音生成脚本
 *
 * 功能:
 * 1. 使用 Edge TTS（免费）或百炼 CosyVoice 生成配音
 * 2. 长文本分段处理
 * 3. 合并音频文件
 * 4. 计算音频时长
 *
 * 用法: node generate_tts.js <work_dir> [options]
 * 输入: condensed_scripts.json
 * 输出: audio/*.${audioFormat}, audio_timing.json
 *
 * 选项:
 *   --edge        使用 Edge TTS
 *   --dashscope   使用 DashScope TTS（默认）
 *
 * 环境变量:
 *   DASHSCOPE_API_KEY    百炼 API Key（使用 DashScope TTS 时需要）
 */

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

// 解析参数
const args = process.argv.slice(2);
const workDir = args.find(a => !a.startsWith('--')) || '.';
const options = {
  model: 'qwen3-tts-flash',     // 千问 TTS 模型
  voice: 'Cherry',              // 千问 TTS 音色 (芊悦 - 阳光积极、亲切自然小姐姐)
  edgeVoice: 'zh-CN-XiaoxiaoNeural',  // Edge TTS 中文女声
  concurrency: 2,
  resume: true,
  maxLength: 250,               // TTS 单次最大字符数 (千问 TTS 限制 600 字符，留安全余量)
  useEdgeTTS: !args.includes('--dashscope'),  // 默认使用 Edge TTS
  // TTS 语速语调调优
  rate: '+20%',                 // Edge TTS 语速 (+20% 稍快)
  pitch: '+5Hz',                // Edge TTS 语调 (微调)
  speechRate: 1.2,              // DashScope 语速 (1.0=正常, 1.2=稍快)
  pitchRate: 1.1                // DashScope 语调 (1.0=正常, 1.1=稍高)
};

// 根据使用的 TTS 引擎设置音频格式
const audioFormat = options.useEdgeTTS ? 'mp3' : 'wav';
const audioCodec = options.useEdgeTTS ? 'libmp3lame' : 'pcm_s16le';

// 解析额外参数
for (const arg of args) {
  if (arg.startsWith('--')) continue;
  const [key, value] = arg.split('=');
  if (key && value) {
    options[key] = isNaN(value) ? value : parseFloat(value);
  }
}

// 路径 - 使用新的统一 steps/ 目录结构
// 解析 --output 参数
let outputDir = path.join(workDir, 'steps/3_音频');
for (const arg of args) {
  if (arg.startsWith('--output=')) {
    outputDir = arg.split('=')[1];
    break;
  }
}

const inputPath = path.join(workDir, 'steps/2_文稿/condensed.json');
const timingPath = path.join(outputDir, 'audio_timing.json');

console.log('🎙️ TTS 配音生成');
console.log('📁 工作目录:', workDir);
console.log(`🔊 TTS 引擎: ${options.useEdgeTTS ? 'Edge TTS (免费)' : 'DashScope'}`);
console.log('⚙️ 配置:', JSON.stringify(options, null, 2));

// 加载数据
function loadJSON(p) {
  if (!fs.existsSync(p)) {
    console.error(`❌ 文件不存在: ${p}`);
    return null;
  }
  return JSON.parse(fs.readFileSync(p, 'utf8'));
}

// 获取音频时长
function getAudioDuration(audioPath) {
  try {
    const cmd = `ffprobe -v error -show_entries format=duration -of csv=p=0 "${audioPath}"`;
    const result = execSync(cmd, { encoding: 'utf8' }).trim();
    return parseFloat(result);
  } catch (err) {
    console.log(`   ⚠️ 无法获取音频时长: ${err.message}`);
    return 0;
  }
}

// ────────────────── 并发控制器 ──────────────────

/**
 * 带并发限制的批量异步执行
 * @param {Array} items - 待处理项目数组
 * @param {number} concurrency - 并发数
 * @param {Function} handler - async (item, index) => result
 * @returns {Array} 按原始顺序的结果
 */
async function runWithConcurrency(items, concurrency, handler) {
  const results = new Array(items.length);
  let nextIndex = 0;

  async function worker() {
    while (true) {
      const i = nextIndex++;
      if (i >= items.length) break;
      results[i] = await handler(items[i], i);
    }
  }

  const workers = Array.from(
    { length: Math.min(concurrency, items.length) },
    () => worker()
  );
  await Promise.all(workers);
  return results;
}

/**
 * 创建带互斥保护的进度保存器
 * @param {string} timingPath - 进度文件路径
 * @param {object} timing - 进度对象
 * @param {object} options - 配置选项
 * @returns {Function} saveProgress(newSegment) 保存进度函数
 */
function createProgressSaver(timingPath, timing, options) {
  let saving = false;

  return async function saveProgress(newSegment) {
    timing.segments.push(newSegment);

    // 简单互斥：跳过正在保存的情况
    if (saving) return;
    saving = true;

    try {
      const data = {
        generatedAt: new Date().toISOString(),
        voiceModel: options.useEdgeTTS ? 'edge-tts' : 'cosyvoice-v1',
        voiceId: options.useEdgeTTS ? options.edgeVoice : options.voice,
        totalDuration: timing.segments.reduce((sum, s) => sum + s.duration, 0),
        segments: timing.segments
      };
      fs.writeFileSync(timingPath, JSON.stringify(data, null, 2));
    } finally {
      saving = false;
    }
  };
}

// Edge TTS 合成（免费，无需 API）
async function edgeTTSSynthesize(text, outputPath, voice = 'zh-CN-XiaoxiaoNeural', rate = '+20%', pitch = '+5Hz') {
  // 使用临时文件存储文本，避免命令行转义问题
  const tempTextPath = outputPath + '.txt';

  try {
    // 写入临时文本文件
    fs.writeFileSync(tempTextPath, text, 'utf8');

    // 使用 edge-tts 命令行工具，从文件读取文本，添加语速语调参数
    const cmd = `edge-tts --voice "${voice}" --file "${tempTextPath}" --write-media "${outputPath}" --rate="${rate}" --pitch="${pitch}"`;
    execSync(cmd, { stdio: 'pipe', timeout: 60000 });

    // 清理临时文件
    try { fs.unlinkSync(tempTextPath); } catch (e) { /* ignore */ }

    return true;
  } catch (err) {
    // 尝试使用 Python 模块
    try {
      const pyCmd = `python -m edge_tts --voice "${voice}" --file "${tempTextPath}" --write-media "${outputPath}" --rate="${rate}" --pitch="${pitch}"`;
      execSync(pyCmd, { stdio: 'pipe', timeout: 60000 });

      // 清理临时文件
      try { fs.unlinkSync(tempTextPath); } catch (e) { /* ignore */ }

      return true;
    } catch (pyErr) {
      console.error(`   ❌ Edge TTS 失败: ${pyErr.message}`);
      console.log('   💡 提示: 请安装 edge-tts: pip install edge-tts');

      // 清理临时文件
      try { fs.unlinkSync(tempTextPath); } catch (e) { /* ignore */ }

      return false;
    }
  }
}

// DashScope TTS 客户端
let dashscopeClient = null;
function getDashScopeClient() {
  if (!dashscopeClient) {
    const { DashScopeClient } = require('./lib/dashscope');
    const apiKey = process.env.DASHSCOPE_API_KEY;
    if (!apiKey) {
      throw new Error('请设置环境变量 DASHSCOPE_API_KEY');
    }
    dashscopeClient = new DashScopeClient(apiKey);
  }
  return dashscopeClient;
}

// 合并音频文件
function mergeAudioFiles(audioFiles, outputPath) {
  if (audioFiles.length === 0) return false;
  if (audioFiles.length === 1) {
    fs.copyFileSync(audioFiles[0], outputPath);
    return true;
  }

  // 生成 concat 文件（使用绝对路径，并将反斜杠转换为正斜杠）
  const concatPath = outputPath + '.txt';
  const concatContent = audioFiles.map(f => {
    // 转换为绝对路径，并将反斜杠转换为正斜杠（Windows 兼容 FFmpeg concat）
    const absPath = path.resolve(f).replace(/\\/g, '/');
    return `file '${absPath}'`;
  }).join('\n');
  fs.writeFileSync(concatPath, concatContent);

  // 使用 shell 方式调用 FFmpeg（Windows 兼容）
  try {
    // 使用绝对路径并转换反斜杠为正斜杠
    const absOutputPath = path.resolve(outputPath).replace(/\\/g, '/');
    const absConcatPath = path.resolve(concatPath).replace(/\\/g, '/');
    execSync(`ffmpeg -y -f concat -safe 0 -i "${absConcatPath}" -c copy "${absOutputPath}"`, {
      stdio: 'pipe',
      shell: true
    });
    fs.unlinkSync(concatPath);
    return true;
  } catch (err) {
    console.error(`   ❌ 合并音频失败: ${err.message}`);
    // 打印 concat 文件内容用于调试
    console.error(`   Concat 文件内容:\n${concatContent}`);
    return false;
  }
}

// 分段文本用于 TTS（修复版：处理超长句子）
function splitTextForTTS(text, maxLength = 250) {
  const chunks = [];

  // 按句子分割
  const sentences = text.match(/[^。！？.!?]+[。！？.!?]+/g) || [text];
  let current = '';

  for (const sentence of sentences) {
    // 如果单个句子本身超过 maxLength，强制按字符分割
    if (sentence.length > maxLength) {
      // 先保存当前累积的内容
      if (current) {
        chunks.push(current.trim());
        current = '';
      }
      // 强制分割长句
      for (let i = 0; i < sentence.length; i += maxLength) {
        chunks.push(sentence.slice(i, i + maxLength));
      }
    } else if (current.length + sentence.length > maxLength) {
      chunks.push(current.trim());
      current = sentence;
    } else {
      current += sentence;
    }
  }

  if (current.trim()) chunks.push(current.trim());

  // 二次检查：确保没有段落超限（防御性编程）
  const safeChunks = [];
  for (const chunk of chunks) {
    if (chunk.length > maxLength) {
      // 如果还是超限，强制分割
      for (let i = 0; i < chunk.length; i += maxLength) {
        safeChunks.push(chunk.slice(i, i + maxLength));
      }
    } else {
      safeChunks.push(chunk);
    }
  }

  return safeChunks;
}

// 生成单章配音
async function generateChapterAudio(script, outputDir) {
  const chapterDir = path.join(outputDir, `chapter_${script.chapterId}`);
  fs.mkdirSync(chapterDir, { recursive: true });

  // 分段文本
  const chunks = splitTextForTTS(script.script, options.maxLength);
  const segmentFiles = [];

  console.log(`   📝 分 ${chunks.length} 段处理`);

  for (let i = 0; i < chunks.length; i++) {
    const chunk = chunks[i];
    const segmentPath = path.join(chapterDir, `segment_${i}.${audioFormat}`);

    // 检查是否已存在
    if (options.resume && fs.existsSync(segmentPath)) {
      console.log(`   ⏭️ 跳过已存在: segment_${i}`);
      segmentFiles.push(segmentPath);
      continue;
    }

    try {
      console.log(`   🎙️ 生成 segment_${i}/${chunks.length} (${chunk.length}字)...`);

      let success = false;

      // 优先使用 Edge TTS
      if (options.useEdgeTTS) {
        success = await edgeTTSSynthesize(chunk, segmentPath, options.edgeVoice, options.rate, options.pitch);
      }

      // Edge TTS 失败时尝试 DashScope
      if (!success && !options.useEdgeTTS) {
        try {
          const client = getDashScopeClient();
          const audioBuffer = await client.synthesizeSpeech(chunk, {
            voice: options.voice,
            speech_rate: options.speechRate,
            pitch_rate: options.pitchRate
          });
          fs.writeFileSync(segmentPath, audioBuffer);
          success = true;
        } catch (dsErr) {
          console.error(`   ❌ DashScope TTS 失败: ${dsErr.message}`);
        }
      }

      if (success) {
        segmentFiles.push(segmentPath);
      }

      // 延迟避免限流
      await new Promise(r => setTimeout(r, 300));
    } catch (err) {
      console.error(`   ❌ segment_${i} 生成失败: ${err.message}`);
    }
  }

  // 合并音频
  const finalPath = path.join(outputDir, `chapter_${script.chapterId}.${audioFormat}`);
  if (segmentFiles.length > 0) {
    mergeAudioFiles(segmentFiles, finalPath);

    // 清理分段文件（带延迟和重试）
    await new Promise(r => setTimeout(r, 500));
    for (const f of segmentFiles) {
      try {
        if (fs.existsSync(f)) fs.unlinkSync(f);
      } catch (e) {
        // 忽略删除失败
      }
    }
    try {
      fs.rmSync(chapterDir, { recursive: true, force: true });
    } catch (e) {
      // 忽略删除失败
    }

    return finalPath;
  }

  return null;
}

// 主流程
async function main() {
  // 加载文稿
  const scriptsData = loadJSON(inputPath);
  if (!scriptsData || !scriptsData.scripts) {
    console.error('❌ 请先运行 condense_content.js');
    process.exit(1);
  }

  const scripts = scriptsData.scripts;
  console.log(`📝 加载 ${scripts.length} 个文稿`);

  // 创建输出目录
  fs.mkdirSync(outputDir, { recursive: true });

  // 检查断点续传
  let timing = { segments: [] };
  if (options.resume && fs.existsSync(timingPath)) {
    timing = loadJSON(timingPath);
    console.log(`📂 已加载 ${timing.segments.length} 个已完成的音频`);
  }

  const processedIds = new Set(timing.segments.map(s => s.chapterId));
  const pending = scripts.filter(s => !processedIds.has(s.chapterId));

  console.log(`📊 待处理: ${pending.length} 个文稿`);

  if (pending.length === 0) {
    console.log('✅ 所有音频已生成完成');
    return;
  }

  // 生成配音
  const startTime = Date.now();

  // 创建带互斥保护的进度保存器
  const saveProgress = createProgressSaver(timingPath, timing, options);

  console.log(`⚡ 并发数: ${options.concurrency}`);

  // 并发处理所有章节
  await runWithConcurrency(
    pending,
    options.concurrency,
    async (script, i) => {
      console.log(`\n🎙️ [${i + 1}/${pending.length}] 章节 ${script.chapterId}: ${script.title.substring(0, 30)}...`);

      const audioPath = await generateChapterAudio(script, outputDir);

      if (audioPath && fs.existsSync(audioPath)) {
        const duration = getAudioDuration(audioPath);
        console.log(`   ✅ [${i + 1}/${pending.length}] 完成: ${(duration / 60).toFixed(2)} 分钟`);

        const segment = {
          chapterId: script.chapterId,
          title: script.title,
          audioPath,
          duration,
          textLength: script.script.length
        };

        // 每章完成后保存进度（带互斥保护）
        saveProgress(segment);

        return segment;
      } else {
        console.log(`   ❌ [${i + 1}/${pending.length}] 失败`);

        const segment = {
          chapterId: script.chapterId,
          title: script.title,
          audioPath: null,
          duration: 0,
          error: '生成失败'
        };

        // 失败也保存进度
        saveProgress(segment);

        return segment;
      }
    }
  );

  const elapsed = ((Date.now() - startTime) / 1000).toFixed(2);
  const totalDuration = timing.segments.reduce((sum, s) => sum + s.duration, 0);

  console.log(`\n✅ TTS 完成！`);
  console.log(`   成功: ${timing.segments.filter(s => s.audioPath).length} 个`);
  console.log(`   失败: ${timing.segments.filter(s => !s.audioPath).length} 个`);
  console.log(`   总时长: ${(totalDuration / 60).toFixed(2)} 分钟`);
  console.log(`   耗时: ${elapsed} 秒`);
  console.log(`📁 输出: ${outputDir}`);
}

main().catch(err => {
  console.error('❌ 错误:', err.message);
  process.exit(1);
});
