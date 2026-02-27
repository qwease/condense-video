#!/usr/bin/env node
/**
 * 精要提炼工作流 - 主入口（统一版本）
 *
 * 从视频课程中智能提取核心内容，生成带 AI 配音的精要视频
 *
 * 用法: node run.js <video_path> [options]
 *
 * 选项:
 *   --skip-transcribe    跳过转录
 *   --skip-ocr           跳过 OCR
 *   --tts-engine=...     TTS 引擎: dashscope (默认) | edgetts
 *   --voice=...          音色名称
 *   --concurrency=N      并发数
 */

const path = require('path');
const fs = require('fs');
const { execSync } = require('child_process');

const { createWorkflowPaths, ensureDirectories, printPathSummary, STEP_NUMBERS } = require('./lib/path-config');

// 解析参数
const args = process.argv.slice(2);
const inputVideoPath = args.find(a => !a.startsWith('--'));
const options = {
  skipTranscribe: args.includes('--skip-transcribe'),
  skipOcr: args.includes('--skip-ocr'),
  ttsEngine: 'dashscope',
  voice: null,
  concurrency: 10
};

for (const arg of args) {
  if (arg.startsWith('--tts-engine=')) options.ttsEngine = arg.split('=')[1];
  if (arg.startsWith('--voice=')) options.voice = arg.split('=')[1];
  if (arg.startsWith('--concurrency=')) options.concurrency = parseInt(arg.split('=')[1]);
}

const SCRIPTS_DIR = __dirname;

function showUsage() {
  console.log(`
用法: node run.js <video_path> [options]

选项:
  --skip-transcribe    跳过转录
  --skip-ocr           跳过 OCR
  --tts-engine=dashscope TTS 引擎 (dashscope|edgetts)
  --voice=Cherry       音色名称
  --concurrency=5      并发数

环境变量:
  DASHSCOPE_API_KEY     百炼 API Key

示例:
  node run.js lecture.mp4
  node run.js lecture.mp4 --tts-engine=dashscope --voice=Cherry
  node run.js lecture.mp4 --skip-transcribe
`);
  process.exit(1);
}

if (!inputVideoPath || !fs.existsSync(inputVideoPath)) {
  showUsage();
}

function loadEnv() {
  const envPaths = [
    path.join(SCRIPTS_DIR, '../../.env'),
    path.join(process.env.USERPROFILE || process.env.HOME || '', '.claude/skills/videocut/.env'),
    path.join(SCRIPTS_DIR, '.env')
  ];

  for (const envPath of envPaths) {
    if (fs.existsSync(envPath)) {
      const envContent = fs.readFileSync(envPath, 'utf8');
      for (const line of envContent.split('\n')) {
        const match = line.match(/^DASHSCOPE_API_KEY\s*=\s*(.+)$/);
        if (match && !process.env.DASHSCOPE_API_KEY) {
          process.env.DASHSCOPE_API_KEY = match[1].trim().replace(/['"]/g, '');
        }
      }
      console.log(`📋 加载环境变量: ${envPath}`);
      break;
    }
  }
}

function runStep(name, cmd, cwd = SCRIPTS_DIR) {
  console.log(`\n${'═'.repeat(50)}`);
  console.log(`📌 ${name}`);
  console.log(`${'═'.repeat(50)}`);

  const startTime = Date.now();

  try {
    execSync(cmd, {
      cwd,
      stdio: 'inherit',
      env: { ...process.env },
      shell: true,
      timeout: 6000000
    });

    const elapsed = ((Date.now() - startTime) / 1000).toFixed(2);
    console.log(`✅ ${name} 完成 (${elapsed}秒)`);
    return true;
  } catch (err) {
    console.error(`❌ ${name} 失败:`, err.message);
    return false;
  }
}

function getPythonCmd() {
  const venvPython = process.platform === 'win32'
    ? path.join(SCRIPTS_DIR, 'venv/Scripts/python.exe')
    : path.join(SCRIPTS_DIR, 'venv/bin/python');
  return fs.existsSync(venvPython) ? venvPython : 'python';
}

async function main() {
  const totalStart = Date.now();

  loadEnv();

  if (!process.env.DASHSCOPE_API_KEY) {
    console.error('❌ 请设置环境变量 DASHSCOPE_API_KEY');
    process.exit(1);
  }

  const paths = createWorkflowPaths(inputVideoPath, '精要提炼');
  ensureDirectories(paths);

  console.log('╔════════════════════════════════════════════╗');
  console.log('║              精要提炼工作流                ║');
  console.log('╚════════════════════════════════════════════╝');
  console.log(`\n📹 视频: ${paths.input.video}`);
  console.log(`🔊 TTS: ${options.ttsEngine}`);
  console.log(`🎙️ 音色: ${options.voice || '默认'}`);

  printPathSummary(paths);

  const pythonCmd = getPythonCmd();

  // ===== 步骤 1: 提取音频 =====
  if (!options.skipTranscribe && !fs.existsSync(paths.transcribe.audio)) {
    const absAudioPath = path.resolve(paths.transcribe.audio).replace(/\\/g, '/');
    const absVideoPath = paths.input.video.replace(/\\/g, '/');
    
    // 关键修复:
    // 1. -fflags +genpts+igndts  : 忽略原始 DTS 并重新生成 PTS
    // 2. -af aresample=async=1   : 音频重采样，修复不连续的时间戳
    // 3. -max_muxing_queue_size  : 加大复用队列，防止队列溢出
    const extractCmd = [
      'ffmpeg -y',
      '-fflags +genpts+igndts',          // 重新生成时间戳，忽略错误 DTS
      `-i "${absVideoPath}"`,
      '-vn',                              // 不要视频
      '-af aresample=async=1',            // 异步重采样，修复音频时间戳间隙
      '-acodec libmp3lame',
      '-q:a 2',
      '-max_muxing_queue_size 9999',      // 防止队列溢出
      `"${absAudioPath}"`
    ].join(' ');
    
    runStep('提取音频', extractCmd);
  }

  // ===== 步骤 2: 提取关键帧 =====
  if (!options.skipOcr) {
    const absFramesDir = path.resolve(paths.ppt.frames).replace(/\\/g, '/');
    const absVideoPath = paths.input.video.replace(/\\/g, '/');
    const frameCmd = `"${pythonCmd}" "${path.join(SCRIPTS_DIR, 'extract_frames.py')}" "${absVideoPath}" --output "${absFramesDir}" -i 5 -t 15 --stability-check`;
    runStep('提取关键帧', frameCmd);
  }

  // ===== 步骤 3: OCR 识别 =====
  if (!options.skipOcr) {
    // 传入 frames 目录（包含 frames_info.json），而不是 images 子目录
    const absFramesDir = path.resolve(paths.ppt.frames).replace(/\\/g, '/');
    const ocrCmd = `node "${path.join(SCRIPTS_DIR, 'ocr_slides.js')}" "${absFramesDir}" concurrency=${options.concurrency}`;
    runStep('OCR 识别', ocrCmd);
  }

  // ===== 步骤 4: 语音转录 =====
  if (!options.skipTranscribe) {
    let audioUrl = null;
    if (fs.existsSync(paths.transcribe.audio)) {
      console.log('\n' + '═'.repeat(50));
      console.log('📌 上传音频');
      console.log('═'.repeat(50));
      try {
        const audioPath = paths.transcribe.audio.replace(/\\/g, '/');
        const uploadCmd = `curl -s -F "files[]=@${audioPath}" https://uguu.se/upload`;
        const uploadResult = execSync(uploadCmd, { encoding: 'utf8' });
        const uploadData = JSON.parse(uploadResult);
        if (uploadData.success && uploadData.files && uploadData.files[0]) {
          audioUrl = uploadData.files[0].url;
          console.log(`✅ 上传成功: ${audioUrl}`);
        }
      } catch (err) {
        console.warn('⚠️ 上传失败，使用本地路径');
      }
    }

    const urlToUse = audioUrl || `file://${paths.transcribe.audio}`;
    const transcribeDir = paths.steps[STEP_NUMBERS.TRANSCRIBE];
    const transcribeCmd = `node "${path.join(SCRIPTS_DIR, 'dashscope_transcribe.js')}" "${urlToUse}" -o "${path.join(transcribeDir, 'result.json')}"`;
    if (!runStep('语音转录', transcribeCmd, transcribeDir)) {
      console.error('❌ 转录失败');
      process.exit(1);
    }

    const convertCmd = `node "${path.join(SCRIPTS_DIR, 'lib/convert_transcript.js')}" "${transcribeDir}" "${paths.steps[STEP_NUMBERS.SCRIPT]}"`;
    runStep('转换格式', convertCmd);
  }

  // ===== 步骤 5: 内容分类 =====
  const classifyCmd = `node "${path.join(SCRIPTS_DIR, 'classify_content.js')}" "${paths.output.root}" concurrency=${options.concurrency}`;
  if (!runStep('内容分类', classifyCmd)) {
    console.error('❌ 分类失败');
    process.exit(1);
  }

  // ===== 步骤 6: 提取章节 =====
  const segmentsFile = path.join(paths.steps[STEP_NUMBERS.SCRIPT], 'segments.json');
  if (fs.existsSync(segmentsFile)) {
    const absWorkDir = path.resolve(paths.output.root).replace(/\\/g, '/');
    const scriptDir = path.resolve(paths.steps[STEP_NUMBERS.SCRIPT]).replace(/\\/g, '/');
    const extractCmd = `node "${path.join(SCRIPTS_DIR, 'extract_chapters.js')}" "${absWorkDir}" --output="${scriptDir}"`;
    runStep('提取章节', extractCmd);
  }

  // ===== 步骤 7: 内容浓缩 =====
  const chaptersFile = path.join(paths.steps[STEP_NUMBERS.SCRIPT], 'chapters.json');
  if (fs.existsSync(chaptersFile)) {
    const absWorkDir = path.resolve(paths.output.root).replace(/\\/g, '/');
    const scriptDir = path.resolve(paths.steps[STEP_NUMBERS.SCRIPT]).replace(/\\/g, '/');
    const condenseCmd = `node "${path.join(SCRIPTS_DIR, 'condense_content.js')}" "${absWorkDir}" --output "${scriptDir}"`;
    if (!runStep('内容浓缩', condenseCmd)) {
      console.error('❌ 浓缩失败');
      process.exit(1);
    }
  }

  // ===== 步骤 8: 生成 TTS 音频 =====
  const condensedFile = path.join(paths.steps[STEP_NUMBERS.SCRIPT], 'condensed.json');
  if (fs.existsSync(condensedFile)) {
    const absWorkDir = path.resolve(paths.output.root).replace(/\\/g, '/');
    const audioDir = path.resolve(paths.audio.dir).replace(/\\/g, '/');
    const ttsCmd = [
      `node "${path.join(SCRIPTS_DIR, 'generate_tts.js')}"`,
      `"${absWorkDir}"`,
      `--output "${audioDir}"`,
      options.ttsEngine === 'edgetts' ? '--edge' : '--dashscope',
      options.voice ? `voice=${options.voice}` : '',
      `concurrency=${Math.min(3, options.concurrency)}`
    ].filter(Boolean).join(' ');

    if (!runStep('生成配音', ttsCmd)) {
      console.error('❌ TTS 失败');
      process.exit(1);
    }
  }

  // ===== 步骤 9: 合成视频 =====
  if (fs.existsSync(condensedFile)) {
    const absWorkDir = path.resolve(paths.output.root).replace(/\\/g, '/');
    const absPptDir = path.resolve(paths.ppt.images).replace(/\\/g, '/');
    const audioDir = path.resolve(paths.audio.dir).replace(/\\/g, '/');
    const absResultVideo = path.resolve(paths.resultVideo).replace(/\\/g, '/');
    const composeCmd = [
      `node "${path.join(SCRIPTS_DIR, 'compose_video.js')}"`,
      `"${absWorkDir}"`,
      `"${absPptDir}"`,
      `"${audioDir}"`,
      `"${absResultVideo}"`
    ].join(' ');

    if (!runStep('合成视频', composeCmd)) {
      console.error('❌ 合成失败');
      process.exit(1);
    }
  }

  const totalElapsed = ((Date.now() - totalStart) / 1000 / 60).toFixed(2);

  console.log('\n╔════════════════════════════════════════════╗');
  console.log('║              ✅ 精要提炼完成！              ║');
  console.log('╚════════════════════════════════════════════╝');
  console.log(`\n⏱️ 总耗时: ${totalElapsed} 分钟`);
  console.log(`📹 视频输出: ${paths.resultVideo}`);
}

main().catch(err => {
  console.error('❌ 错误:', err.message);
  process.exit(1);
});
