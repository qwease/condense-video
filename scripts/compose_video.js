#!/usr/bin/env node
/**
 * 视频合成脚本
 *
 * 功能:
 * 1. PPT 图片作为视频画面
 * 2. TTS 音频作为配音
 * 3. 章节间添加淡入淡出
 * 4. 输出最终视频
 *
 * 用法: node compose_video.js <work_dir> [options]
 * 输入: chapters.json, audio_timing.json
 * 输出: condensed_course.mp4
 */

const fs = require('fs');
const path = require('path');
const { execSync, exec } = require('child_process');
const { promisify } = require('util');

const execAsync = promisify(exec);

// 解析参数 - 支持新的调用方式: node compose_video.js <workDir> <pptDir> <audioDir> <outputPath>
const args = process.argv.slice(2);

// 将相对路径转换为绝对路径（相对于当前工作目录，而非脚本目录）
function resolveCwd(p) {
  if (path.isAbsolute(p)) return p;
  return path.resolve(process.cwd(), p);
}

const workDir = resolveCwd(args[0] || '.');
const pptDir = args[1] ? resolveCwd(args[1]) : path.join(workDir, 'steps/5_PPT/frames/images');
const audioDir = args[2] ? resolveCwd(args[2]) : path.join(workDir, 'steps/3_音频');
const outputPath = args[3] ? resolveCwd(args[3]) : path.join(workDir, 'steps/4_视频/condensed_course.mp4');

const options = {
  fps: 30,
  resolution: '1920x1080',
  transitionDuration: 0.5,  // 过渡时长（秒）
  fadeDuration: 0.3,        // 淡入淡出时长
  concurrency: 4            // 并发处理章节数
};

// 解析额外参数
for (let i = 4; i < args.length; i++) {
  const [key, value] = args[i].split('=');
  if (key && value) {
    options[key] = isNaN(value) ? value : parseFloat(value);
  }
}

// 路径 - 使用新的统一 steps/ 目录结构
const chaptersPath = path.join(workDir, 'steps/2_文稿/chapters.json');
const timingPath = path.join(audioDir, 'audio_timing.json');
const outputDir = path.dirname(outputPath);

console.log('🎬 视频合成');
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

// 检测编码器
function detectEncoder() {
  const platform = process.platform;
  const encoders = [];

  if (platform === 'win32') {
    encoders.push({ name: 'h264_nvenc', args: '-preset p4 -cq 20' });
    encoders.push({ name: 'h264_qsv', args: '-global_quality 20' });
    encoders.push({ name: 'h264_amf', args: '-quality balanced' });
  } else if (platform === 'darwin') {
    encoders.push({ name: 'h264_videotoolbox', args: '-q:v 60' });
  }

  encoders.push({ name: 'libx264', args: '-preset fast -crf 18' });

  for (const enc of encoders) {
    try {
      execSync(`ffmpeg -hide_banner -encoders 2>&1 | grep ${enc.name}`, { stdio: 'pipe' });
      console.log(`🎯 使用编码器: ${enc.name}`);
      return enc;
    } catch (e) {
      // 继续尝试下一个
    }
  }

  return { name: 'libx264', args: '-preset fast -crf 18' };
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

// 创建单章幻灯片视频（使用统一编码参数，确保 stream copy 兼容）
async function createSlideVideo(imagePath, audioPath, outputPath, duration, baseDir = workDir) {
  // 转换为绝对路径（相对路径优先相对于 baseDir 解析）
  const resolvePath = (p) => {
    if (path.isAbsolute(p)) return p.replace(/\\/g, '/');
    return path.resolve(baseDir, p).replace(/\\/g, '/');
  };

  const absImagePath = resolvePath(imagePath);
  const absAudioPath = resolvePath(audioPath);
  const absOutputPath = resolvePath(outputPath);

  // 解析分辨率 (1920x1080 -> width: 1920, height: 1080)
  const [width, height] = options.resolution.split('x');

  // 使用固定的编码参数，确保所有章节视频完全一致，以便合并时可用 -c copy
  // 关键：分辨率、帧率、编码预设、音频采样率必须完全相同
  const cmd = [
    'ffmpeg', '-y',
    '-loop', '1',
    '-i', `"${absImagePath}"`,
    '-i', `"${absAudioPath}"`,
    '-vf', `scale=${width}:${height}:force_original_aspect_ratio=decrease,pad=${width}:${height}:(ow-iw)/2:(oh-ih)/2`,
    '-r', options.fps.toString(),              // 固定帧率
    '-c:v', 'libx264',
    '-preset', 'fast',                        // 固定编码预设
    '-tune', 'stillimage',
    '-pix_fmt', 'yuv420p',
    '-c:a', 'aac',
    '-b:a', '192k',
    '-ar', '44100',                           // 固定音频采样率
    '-ac', '2',                               // 固定声道数
    '-t', duration.toString(),
    '-shortest',
    `"${absOutputPath}"`
  ].join(' ');

  try {
    await execAsync(cmd, { shell: true });
    return true;
  } catch (err) {
    console.error(`❌ 创建幻灯片视频失败: ${err.message}`);
    return false;
  }
}

// 合并视频（带过渡）
function mergeVideosWithTransition(videoFiles, outputPath, encoder) {
  if (videoFiles.length === 0) return false;
  if (videoFiles.length === 1) {
    fs.copyFileSync(videoFiles[0], outputPath);
    return true;
  }

  // 生成 concat 文件（使用绝对路径避免相对路径解析问题）
  const concatPath = outputPath + '.txt';
  const concatContent = videoFiles.map(f => {
    // 转换为绝对路径
    const absPath = path.resolve(f);
    return `file '${absPath}'`;
  }).join('\n');
  fs.writeFileSync(concatPath, concatContent);

  // 优先使用 stream copy（-c copy），无需重新编码，速度快 10-50 倍
  const streamCopyCmd = [
    'ffmpeg', '-y',
    '-f', 'concat',
    '-safe', '0',
    '-i', `"${concatPath}"`,
    '-c', 'copy',
    `"${outputPath}"`
  ].join(' ');

  try {
    execSync(streamCopyCmd, { stdio: 'inherit' });
    fs.unlinkSync(concatPath);
    return true;
  } catch (err) {
    console.log(`⚠️ stream copy 失败: ${err.message}`);
    console.log(`🔄 降级到重新编码模式...`);

    // 降级方案：重新编码（兼容性更好，但速度慢）
    const reencodeCmd = [
      'ffmpeg', '-y',
      '-f', 'concat',
      '-safe', '0',
      '-i', `"${concatPath}"`,
      '-c:v', encoder.name,
      ...encoder.args.split(' '),
      '-c:a', 'aac',
      '-b:a', '192k',
      `"${outputPath}"`
    ].join(' ');

    try {
      execSync(reencodeCmd, { stdio: 'inherit' });
      fs.unlinkSync(concatPath);
      return true;
    } catch (reencodeErr) {
      console.error(`❌ 合并视频失败: ${reencodeErr.message}`);
      return false;
    }
  }
}

// 主流程
async function main() {
  // 加载数据
  const chaptersData = loadJSON(chaptersPath);
  const timingData = loadJSON(timingPath);

  if (!chaptersData || !timingData) {
    console.error('❌ 请先运行 extract_chapters.js 和 generate_tts.js');
    process.exit(1);
  }

  // 支持两种格式: { chapters: [...] } 或直接数组 [...]
  const chapters = Array.isArray(chaptersData) ? chaptersData : chaptersData.chapters;
  const segments = timingData.segments;

  console.log(`📚 加载 ${chapters.length} 个章节`);
  console.log(`🎙️ 加载 ${segments.length} 个音频`);

  // 创建输出目录
  fs.mkdirSync(outputDir, { recursive: true });

  // 临时目录
  const tempDir = path.join(outputDir, 'temp');
  fs.mkdirSync(tempDir, { recursive: true });

  const encoder = detectEncoder();

  // 获取 PPT 帧列表
  const pptFrames = fs.readdirSync(pptDir)
    .filter(f => f.endsWith('.jpg') || f.endsWith('.png'))
    .sort();

  console.log(`📷 发现 ${pptFrames.length} 个 PPT 帧`);

  // 根据章节时间选择对应的 PPT 帧
  function getSlideImageForChapter(chapter) {
    if (chapter.slideImage) {
      return chapter.slideImage;
    }

    // 根据章节开始时间选择 PPT 帧
    // 使用 frames_info.json 中的时间戳
    const framesInfoPath = path.join(workDir, 'steps/5_PPT/frames/frames_info.json');
    if (fs.existsSync(framesInfoPath)) {
      const framesInfo = JSON.parse(fs.readFileSync(framesInfoPath, 'utf8'));
      if (framesInfo.frames && framesInfo.frames.length > 0) {
        // 找到最接近章节开始时间的帧
        const closestFrame = framesInfo.frames
          .filter(f => f.timestamp <= chapter.startTime)
          .pop() || framesInfo.frames[0];

        if (closestFrame && closestFrame.path) {
          return closestFrame.path;
        }
      }
    }

    // 降级：使用第一个 PPT 帧
    if (pptFrames.length > 0) {
      return path.join(pptDir, pptFrames[0]);
    }

    return null;
  }

  // 创建每章视频
  console.log('\n🎬 创建章节视频...');

  // 按 chapterId 排序，确保章节顺序正确（处理并发 TTS 产生的乱序问题）
  const sortedSegments = [...segments].sort((a, b) => {
    const idA = parseInt(String(a.chapterId).replace(/\D/g, '')) || a.chapterId;
    const idB = parseInt(String(b.chapterId).replace(/\D/g, '')) || b.chapterId;
    return idA - idB;
  });

  console.log(`⚡ 并发数: ${options.concurrency}`);

  // 并发创建章节视频
  const results = await runWithConcurrency(
    sortedSegments,
    options.concurrency,
    async (segment, i) => {
      if (!segment.audioPath) {
        console.log(`   ⚠️ [${i + 1}/${sortedSegments.length}] 章节 ${segment.chapterId} 无音频，跳过`);
        return null;
      }

      const chapter = chapters.find(c => c.id === segment.chapterId);
      if (!chapter) {
        console.log(`   ⚠️ [${i + 1}/${sortedSegments.length}] 章节 ${segment.chapterId} 不存在，跳过`);
        return null;
      }

      const slideImage = getSlideImageForChapter(chapter);
      if (!slideImage) {
        console.log(`   ⚠️ [${i + 1}/${sortedSegments.length}] 章节 ${segment.chapterId} 无图片，跳过`);
        return null;
      }

      console.log(`   📹 [${i + 1}/${sortedSegments.length}] 章节 ${segment.chapterId}: ${segment.title.substring(0, 30)}...`);

      const videoPath = path.join(tempDir, `chapter_${segment.chapterId}.mp4`);

      if (await createSlideVideo(slideImage, segment.audioPath, videoPath, segment.duration)) {
        console.log(`      ✅ [${i + 1}/${sortedSegments.length}] ${(segment.duration / 60).toFixed(2)} 分钟`);
        return videoPath;
      } else {
        console.log(`      ❌ [${i + 1}/${sortedSegments.length}] 失败`);
        return null;
      }
    }
  );

  // 过滤成功的视频并保持顺序
  const chapterVideos = results.filter(v => v !== null);

  if (chapterVideos.length === 0) {
    console.error('❌ 没有成功创建任何章节视频');
    process.exit(1);
  }

  // 合并视频
  console.log(`\n🎬 合并 ${chapterVideos.length} 个章节视频...`);

  if (mergeVideosWithTransition(chapterVideos, outputPath, encoder)) {
    // 获取最终视频信息
    const durationCmd = `ffprobe -v error -show_entries format=duration -of csv=p=0 "${outputPath}"`;
    const duration = parseFloat(execSync(durationCmd, { encoding: 'utf8' }).trim());

    console.log(`\n✅ 视频合成完成！`);
    console.log(`   输出: ${outputPath}`);
    console.log(`   时长: ${(duration / 60).toFixed(2)} 分钟`);
    console.log(`   章节数: ${chapterVideos.length}`);

    // 清理临时文件
    console.log('\n🧹 清理临时文件...');
    fs.rmSync(tempDir, { recursive: true, force: true });

    // 保存视频信息
    const videoInfo = {
      generatedAt: new Date().toISOString(),
      outputPath,
      duration,
      chapterCount: chapterVideos.length,
      options
    };
    fs.writeFileSync(path.join(outputDir, 'video_info.json'), JSON.stringify(videoInfo, null, 2));
  }
}

main().catch(err => {
  console.error('❌ 错误:', err.message);
  process.exit(1);
});
