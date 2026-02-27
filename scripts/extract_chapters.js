#!/usr/bin/env node
/**
 * 章节提取脚本（改进版）
 *
 * 功能:
 * 1. 按时间戳关联 PPT 和语音内容
 * 2. 过滤非 PPT 内容（如 Windows 对话框）
 * 3. 合并同一 PPT 下的多个语音片段
 * 4. 处理空 PPT 内容，用语音推断标题
 *
 * 用法: node extract_chapters.js <work_dir>
 * 输入: slides.json, segments.json, frames_info.json
 * 输出: chapters.json
 */

const fs = require('fs');
const path = require('path');

// 解析参数
const workDir = process.argv[2] || '.';

// 提取输出目录参数
let outputDir = workDir;
for (let i = 3; i < process.argv.length; i++) {
  if (process.argv[i].startsWith('--output=')) {
    outputDir = process.argv[i].split('=')[1];
    break;
  }
}

// 使用新的统一 steps/ 目录结构
// slides.json 现在直接在 steps/5_PPT/ 目录下
const slidesPath = path.join(workDir, 'steps/5_PPT/slides.json');
const segmentsPath = path.join(workDir, 'steps/2_文稿/segments.json');
const framesInfoPath = path.join(workDir, 'steps/5_PPT/frames/frames_info.json');

// 输出目录
const chaptersOutputPath = path.join(outputDir, 'chapters.json');

console.log('📚 章节提取（改进版）');
console.log('📁 工作目录:', workDir);
console.log('📁 输出目录:', outputDir);
console.log('📁 输出路径:', chaptersOutputPath);

// 加载数据
function loadJSON(p) {
  if (!fs.existsSync(p)) {
    console.error(`❌ 文件不存在: ${p}`);
    return null;
  }
  return JSON.parse(fs.readFileSync(p, 'utf8'));
}

// 检查是否是有效的 PPT 内容
function isValidPPTContent(slide) {
  if (!slide) return false;

  // 检查 OCR 内容 - 支持多种格式:
  // 1. body[0][0].text (嵌套对象数组)
  // 2. body[0].text (对象数组)
  // 3. body[0] 直接是字符串
  const bodyFirstItem = slide.structure?.body?.[0];
  let bodyText = '';

  if (typeof bodyFirstItem === 'string') {
    bodyText = bodyFirstItem;
  } else if (bodyFirstItem?.text) {
    bodyText = bodyFirstItem.text;
  } else if (Array.isArray(bodyFirstItem) && bodyFirstItem[0]?.text) {
    bodyText = bodyFirstItem[0].text;
  }

  const jsonMatch = bodyText.match(/```json\s*([\s\S]*?)\s*```/);

  if (jsonMatch) {
    try {
      const parsed = JSON.parse(jsonMatch[1]);

      // 过滤 Windows 系统对话框
      if (parsed.title?.includes('Windows') ||
          parsed.title?.includes('关闭') ||
          parsed.title?.includes('等待')) {
        return false;
      }

      // 至少要有标题或内容
      if (parsed.title || (parsed.body && parsed.body.length > 0)) {
        return true;
      }
    } catch (e) {
      // 解析失败，检查原始文本
      return bodyText.length > 50;
    }
  }

  // 检查是否有足够的 OCR 文本
  return bodyText.length > 50;
}

// 解析 PPT 内容
function parseSlideContent(slide) {
  // 首先检查 structure 是否已经包含解析好的内容
  if (slide?.structure?.title && typeof slide.structure.title === 'string') {
    return {
      title: slide.structure.title || '',
      body: slide.structure.body || [],
      formulas: slide.structure.formulas || [],
      keyTerms: slide.structure.keyTerms || []
    };
  }

  // 支持多种格式:
  // 1. body[0][0].text (嵌套对象数组)
  // 2. body[0].text (对象数组)
  // 3. body[0] 直接是字符串
  const bodyFirstItem = slide?.structure?.body?.[0];
  let bodyText = '';

  if (typeof bodyFirstItem === 'string') {
    bodyText = bodyFirstItem;
  } else if (bodyFirstItem?.text) {
    bodyText = bodyFirstItem.text;
  } else if (Array.isArray(bodyFirstItem) && bodyFirstItem[0]?.text) {
    bodyText = bodyFirstItem[0].text;
  }

  // 尝试解析 JSON 代码块
  const jsonMatch = bodyText.match(/```json\s*([\s\S]*?)\s*```/);
  if (jsonMatch) {
    try {
      const parsed = JSON.parse(jsonMatch[1]);
      return {
        title: parsed.title || '',
        body: parsed.body || [],
        formulas: parsed.formulas || [],
        keyTerms: parsed.keyTerms || []
      };
    } catch (e) {
      // 解析失败
    }
  }

  // 尝试直接解析 JSON（没有代码块）
  if (bodyText.startsWith('{')) {
    try {
      const parsed = JSON.parse(bodyText);
      return {
        title: parsed.title || '',
        body: parsed.body || [],
        formulas: parsed.formulas || [],
        keyTerms: parsed.keyTerms || []
      };
    } catch (e) {
      // 解析失败
    }
  }

  return {
    title: '',
    body: [],
    formulas: [],
    keyTerms: []
  };
}

// 从语音内容推断标题
function inferTitleFromSpeech(speech) {
  if (!speech) return '';

  // 提取前100个字符中的关键信息
  const text = speech.substring(0, 200);

  // 常见的章节开头模式
  const patterns = [
    /第[一二三四五六七八九十]+[章节讲]/,
    /今天我们[学讲看]/,
    /下面我们[来开始]/,
    /这个[叫是]什么/,
    /什么[叫是]/,
  ];

  for (const pattern of patterns) {
    const match = text.match(pattern);
    if (match) {
      // 提取匹配后的内容作为标题
      const idx = text.indexOf(match[0]);
      const after = text.substring(idx, idx + 30).replace(/\n/g, ' ').trim();
      return after.substring(0, 20) + (after.length > 20 ? '...' : '');
    }
  }

  // 使用前20个字符作为标题
  return text.substring(0, 20).replace(/\n/g, ' ').trim() + '...';
}

// 按时间戳找到对应的 PPT
function findSlideByTime(timestamp, slides) {
  if (!slides || slides.length === 0) return null;

  // 找到时间戳之前最近的 PPT
  let matched = null;
  for (let i = slides.length - 1; i >= 0; i--) {
    if (slides[i].timestamp <= timestamp) {
      matched = slides[i];
      break;
    }
  }

  return matched;
}

// 合并同一 PPT 下的语音片段
function mergeSegmentsBySlide(segments, slides) {
  const chapters = [];
  const chapterMap = new Map();

  for (const seg of segments) {
    // 找到对应的 PPT
    const slide = findSlideByTime(seg.startTime, slides);

    if (!slide) continue;

    const slideKey = slide.frameId;

    if (!chapterMap.has(slideKey)) {
      chapterMap.set(slideKey, {
        slide: slide,
        segments: [],
        startTime: seg.startTime,
        endTime: seg.endTime
      });
    }

    const chapter = chapterMap.get(slideKey);
    chapter.segments.push(seg);
    chapter.endTime = Math.max(chapter.endTime, seg.endTime);
  }

  // 转换为数组
  for (const [slideKey, chapter] of chapterMap) {
    chapters.push(chapter);
  }

  // 按时间排序
  chapters.sort((a, b) => a.startTime - b.startTime);

  return chapters;
}

/**
 * 合并小章节（核心语音字数不足阈值的章节合并到相邻章节）
 * @param {Array} chapters - 原始章节列表
 * @param {number} minChars - 最小字数阈值
 * @returns {Array} - 合并后的章节列表
 */
function mergeSmallChapters(chapters, minChars = 500) {
  if (chapters.length === 0) return chapters;

  const result = [];
  let current = { ...chapters[0] };

  for (let i = 1; i < chapters.length; i++) {
    const next = chapters[i];

    // 如果当前章节字数不足阈值，合并到下一个章节
    if (current.coreSpeech.length < minChars) {
      // 合并内容
      current = {
        ...current,
        id: current.id,
        title: current.title,
        slideImage: current.slideImage,  // 保留第一个 PPT 图片
        slideContent: current.slideContent,
        coreSpeech: current.coreSpeech + '\n' + next.coreSpeech,
        timeRange: {
          start: current.timeRange.start,
          end: next.timeRange.end,
          duration: next.timeRange.end - current.timeRange.start
        }
      };
    } else {
      // 当前章节足够大，保存并开始新章节
      result.push(current);
      current = { ...next };
    }
  }

  // 添加最后一个章节
  result.push(current);

  // 重新编号
  for (let i = 0; i < result.length; i++) {
    result[i].id = i + 1;
  }

  return result;
}

// 主流程
function main() {
  // 加载数据
  const slidesData = loadJSON(slidesPath);
  const segments = loadJSON(segmentsPath);

  if (!segments || segments.length === 0) {
    console.error('❌ 没有找到分类数据');
    process.exit(1);
  }

  // 过滤有效的 PPT
  const allSlides = slidesData?.slides || [];
  const validSlides = allSlides.filter(isValidPPTContent);

  console.log(`📊 加载 ${allSlides.length} 个 PPT 帧，其中 ${validSlides.length} 个有效`);
  console.log(`📊 加载 ${segments.length} 个分类片段`);

  if (validSlides.length === 0) {
    console.error('❌ 没有找到有效的 PPT 内容');
    process.exit(1);
  }

  // 打印 PPT 时间戳
  console.log('\n📋 PPT 时间轴:');
  for (const slide of validSlides) {
    const content = parseSlideContent(slide);
    const time = (slide.timestamp / 60).toFixed(1);
    console.log(`   ${time}分钟 - ${content.title || '(无标题)'}`);
  }

  // 合并语音片段到对应的 PPT
  const mergedChapters = mergeSegmentsBySlide(segments, validSlides);

  console.log(`\n📖 合并后 ${mergedChapters.length} 个章节`);

  // 构建章节内容
  const chapters = [];
  let globalChapterId = 1;

  for (const merged of mergedChapters) {
    const slide = merged.slide;
    const slideContent = parseSlideContent(slide);

    // 合并核心语音
    const coreSpeech = merged.segments
      .filter(s => s.label === 'core' || s.label === 'explain')
      .map(s => s.text)
      .join('\n');

    if (!coreSpeech.trim()) continue;  // 跳过没有语音内容的章节

    // 推断标题
    let title = slideContent.title;
    if (!title && slideContent.body && slideContent.body.length > 0) {
      // 使用 body 的第一行作为标题
      title = slideContent.body[0];
    }
    if (!title) {
      // 从语音推断
      title = inferTitleFromSpeech(coreSpeech);
    }

    // 计算时长
    const duration = merged.endTime - merged.startTime;

    chapters.push({
      id: globalChapterId++,
      title: title || `第${globalChapterId - 1}节`,
      slideId: slide.frameId,
      slideImage: slide.path,
      slideContent,
      coreSpeech,
      timeRange: {
        start: merged.startTime,
        end: merged.endTime,
        duration
      }
    });
  }

  // 合并小章节（核心语音不足 minChars 字符的章节合并到相邻章节）
  const MIN_CHARS_PER_CHAPTER = 500;
  const mergedSmallChapters = mergeSmallChapters(chapters, MIN_CHARS_PER_CHAPTER);

  // 统计
  const totalDuration = mergedSmallChapters.reduce((sum, ch) => sum + ch.timeRange.duration, 0);
  const totalCoreSpeech = mergedSmallChapters.reduce((sum, ch) => sum + ch.coreSpeech.length, 0);

  console.log(`\n📊 章节统计:`);
  console.log(`   原始章节数: ${chapters.length}`);
  console.log(`   合并后章节数: ${mergedSmallChapters.length}`);
  console.log(`   总时长: ${(totalDuration / 60).toFixed(1)} 分钟`);
  console.log(`   核心语音: ${(totalCoreSpeech / 1000).toFixed(1)} KB`);
  console.log(`   最小章节字数阈值: ${MIN_CHARS_PER_CHAPTER}`);

  // 创建输出目录
  fs.mkdirSync(outputDir, { recursive: true });

  // 输出
  const output = {
    extractedAt: new Date().toISOString(),
    videoInfo: slidesData?.videoInfo || {},
    totalChapters: mergedSmallChapters.length,
    totalDuration: totalDuration,
    chapters: mergedSmallChapters
  };

  fs.writeFileSync(chaptersOutputPath, JSON.stringify(output, null, 2));

  console.log(`\n✅ 提取完成！`);
  console.log(`📁 输出: ${chaptersOutputPath}`);

  // 打印章节摘要
  console.log('\n📖 章节列表:');
  for (const ch of mergedSmallChapters) {
    const duration = (ch.timeRange.duration / 60).toFixed(1);
    const speechLen = ch.coreSpeech.length;
    const title = typeof ch.title === 'string' ? ch.title : JSON.stringify(ch.title);
    const displayTitle = title.length > 30 ? title.substring(0, 30) + '...' : title;
    console.log(`   ${ch.id}. ${displayTitle} (${duration}分钟, ${speechLen}字)`);
  }
}

main();
