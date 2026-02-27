#!/usr/bin/env node
/**
 * PPT OCR 识别脚本（使用百炼 DashScope VL 模型）
 *
 * 功能：
 * 1. 使用 DashScope Qwen-VL 模型进行 OCR
 * 2. 并发处理 + 限流控制
 * 3. 断点续传
 * 4. 结构化输出（标题、公式、术语）
 *
 * 用法: node ocr_slides.js <frames_dir> [options]
 * 输出: ocr_results.json, slides.json
 *
 * 环境变量:
 *   DASHSCOPE_API_KEY=your_api_key
 */

const fs = require('fs');
const path = require('path');
const https = require('https');

// 解析参数
const framesDir = process.argv[2] || './frames';
const framesInfoPath = path.join(framesDir, 'frames_info.json');
const imagesDir = path.join(framesDir, 'images');

const options = {
  concurrency: 5,           // 并发数
  rpm: 60,                  // 每分钟请求数限制
  model: 'qwen3.5-plus',     // VL 模型
  retryTimes: 3,            // 重试次数
  retryDelay: 1000,         // 重试延迟(ms)
  outputDir: path.dirname(framesDir),
  resume: true,             // 断点续传
};

// 解析额外参数
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

// 限流器
class RateLimiter {
  constructor(rpm) {
    this.rpm = rpm;
    this.interval = 60000 / rpm;
    this.lastRequestTime = 0;
    this.queue = [];
    this.processing = false;
  }

  async acquire() {
    return new Promise((resolve) => {
      this.queue.push(resolve);
      this.process();
    });
  }

  async process() {
    if (this.processing || this.queue.length === 0) return;
    this.processing = true;

    while (this.queue.length > 0) {
      const now = Date.now();
      const elapsed = now - this.lastRequestTime;

      if (elapsed < this.interval) {
        await this.sleep(this.interval - elapsed);
      }

      const resolve = this.queue.shift();
      this.lastRequestTime = Date.now();
      resolve();
    }

    this.processing = false;
  }

  sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }
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

// HTTP POST 请求
function httpPost(hostname, path, headers, body) {
  return new Promise((resolve, reject) => {
    const req = https.request({
      hostname,
      path,
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

// VL 模型 OCR（使用 DashScope HTTP API）
async function ocrWithVL(imagePath, retryTimes = 3) {
  const prompt = `请分析这张 PPT 图片，提取以下信息（JSON 格式）：

1. title: PPT 标题（通常是大号字体、居中的文字）
2. subtitles: 副标题或小节标题
3. body: 主要内容文字（数组，每段一个元素）
4. formulas: 公式（如有，保持原格式）
5. keyTerms: 关键术语或专业词汇

请直接返回 JSON结构体，不要有其他说明文字和Markdown标志。`;

  for (let attempt = 0; attempt < retryTimes; attempt++) {
    try {
      // 读取图片并转为 base64
      const imageBuffer = fs.readFileSync(imagePath);
      const base64Image = imageBuffer.toString('base64');
      const mimeType = imagePath.endsWith('.png') ? 'image/png' : 'image/jpeg';

      // 调用 DashScope VL API（同步模式）
      const response = await httpPost(
        'dashscope.aliyuncs.com',
        '/api/v1/services/aigc/multimodal-generation/generation',
        {
          'Authorization': `Bearer ${apiKey}`
        },
        {
          model: options.model,
          input: {
            messages: [
              {
                role: 'user',
                content: [
                  { image: `data:${mimeType};base64,${base64Image}` },
                  { text: prompt }
                ]
              }
            ]
          }
        }
      );

      // 如果是异步任务，需要轮询获取结果
      if (response.output && response.output.task_id) {
        const result = await pollAsyncResult(response.output.task_id);
        return parseOCRResult(result);
      }

      // 同步返回
      return parseOCRResult(response);

    } catch (err) {
      console.log(`   ⚠️ 尝试 ${attempt + 1}/${retryTimes} 失败: ${err.message}`);
      if (attempt < retryTimes - 1) {
        await new Promise(r => setTimeout(r, options.retryDelay * (attempt + 1)));
      }
    }
  }

  return { error: 'OCR 失败', path: imagePath };
}

// 轮询异步任务结果
async function pollAsyncResult(taskId, maxWait = 60000) {
  const startTime = Date.now();

  while (Date.now() - startTime < maxWait) {
    await new Promise(r => setTimeout(r, 1000));

    try {
      const response = await new Promise((resolve, reject) => {
        const req = https.request({
          hostname: 'dashscope.aliyuncs.com',
          path: `/api/v1/tasks/${taskId}`,
          method: 'GET',
          headers: {
            'Authorization': `Bearer ${apiKey}`
          }
        }, (res) => {
          let data = '';
          res.on('data', chunk => data += chunk);
          res.on('end', () => {
            if (res.statusCode === 200) {
              resolve(JSON.parse(data));
            } else {
              reject(new Error(`HTTP ${res.statusCode}`));
            }
          });
        });
        req.on('error', reject);
        req.end();
      });

      if (response.output && response.output.task_status === 'SUCCEEDED') {
        return response;
      } else if (response.output && response.output.task_status === 'FAILED') {
        throw new Error('Task failed');
      }
    } catch (err) {
      // 继续轮询
    }
  }

  throw new Error('Poll timeout');
}

// 解析 OCR 结果
function parseOCRResult(response) {
  try {
    const content = response.output?.results?.[0]?.output?.text ||
                    response.output?.choices?.[0]?.message?.content ||
                    '';

    // 尝试解析 JSON
    try {
      const jsonMatch = content.match(/```json\s*([\s\S]*?)\s*```/) ||
                       content.match(/{[\s\S]*}/);
      const jsonStr = jsonMatch ? jsonMatch[1] || jsonMatch[0] : content;
      const parsed = JSON.parse(jsonStr);

      return {
        title: parsed.title || '',
        subtitles: parsed.subtitles || [],
        body: parsed.body || [],
        formulas: parsed.formulas || [],
        keyTerms: parsed.keyTerms || [],
        rawText: content,
        parseError: false
      };
    } catch (parseErr) {
      return {
        title: '',
        subtitles: [],
        body: [content],
        formulas: [],
        keyTerms: [],
        rawText: content,
        parseError: true
      };
    }
  } catch (err) {
    return {
      title: '',
      subtitles: [],
      body: [],
      formulas: [],
      keyTerms: [],
      rawText: '',
      error: err.message
    };
  }
}

// 主流程
async function main() {
  console.log('🔍 PPT OCR 识别');
  console.log('📁 帧目录:', framesDir);
  console.log('⚙️ 配置:', JSON.stringify(options, null, 2));

  // 读取帧信息
  let framesInfo = { frames: [] };
  if (fs.existsSync(framesInfoPath)) {
    framesInfo = JSON.parse(fs.readFileSync(framesInfoPath, 'utf8'));
  } else {
    // 直接扫描 images 子目录
    const scanDir = fs.existsSync(imagesDir) ? imagesDir : framesDir;
    const files = fs.readdirSync(scanDir)
      .filter(f => f.endsWith('.jpg') || f.endsWith('.png'))
      .sort();

    framesInfo.frames = files.map((f, i) => ({
      index: i,
      filename: f,
      path: path.join(scanDir, f)
    }));
  }

  const frames = framesInfo.frames;
  console.log(`📊 共 ${frames.length} 帧待处理`);

  if (frames.length === 0) {
    console.log('⚠️ 没有找到帧文件');
    return;
  }

  // 检查断点续传
  const resultsPath = path.join(options.outputDir, 'ocr_results.json');
  let results = { slides: [], errors: [] };

  if (options.resume && fs.existsSync(resultsPath)) {
    results = JSON.parse(fs.readFileSync(resultsPath, 'utf8'));
    console.log(`📂 已加载 ${results.slides.length} 个已完成的结果`);
  }

  const processedPaths = new Set(results.slides.map(s => s.path));
  const pendingFrames = frames.filter(f => !processedPaths.has(f.path));

  console.log(`📊 待处理: ${pendingFrames.length} 帧`);

  if (pendingFrames.length === 0) {
    console.log('✅ 所有帧已处理完成');
    return;
  }

  // 初始化限流器和并发控制器
  const rateLimiter = new RateLimiter(options.rpm);
  const concurrencyController = new ConcurrencyController(options.concurrency);

  // 处理进度
  let completed = 0;
  const startTime = Date.now();
  let batchCount = 0;
  const batchSize = 20;

  const tasks = pendingFrames.map((frame, index) => {
    return concurrencyController.run(async () => {
      await rateLimiter.acquire();

      console.log(`📷 [${index + 1}/${pendingFrames.length}] 处理: ${frame.filename}`);

      const result = await ocrWithVL(frame.path, options.retryTimes);

      completed++;

      if (result.error) {
        results.errors.push({ frame: frame, error: result.error });
      } else {
        results.slides.push({
          frameId: frame.index,
          filename: frame.filename,
          path: frame.path,
          timestamp: frame.timestamp,
          ocrText: result.rawText || JSON.stringify(result),
          structure: {
            title: result.title || '',
            subtitles: result.subtitles || [],
            body: result.body || [],
            formulas: result.formulas || [],
            keyTerms: result.keyTerms || [],
            confidence: result.parseError ? 0.5 : 0.9
          }
        });
      }

      // 显示进度
      const elapsed = (Date.now() - startTime) / 1000;
      const speed = completed / elapsed;
      const remaining = speed > 0 ? (pendingFrames.length - completed) / speed : 0;
      console.log(`   进度: ${completed}/${pendingFrames.length} (${(completed/pendingFrames.length*100).toFixed(1)}%) - 预计剩余: ${remaining.toFixed(0)}秒`);

      // 批量保存
      batchCount++;
      if (batchCount >= batchSize) {
        fs.writeFileSync(resultsPath, JSON.stringify(results, null, 2));
        batchCount = 0;
      }
    });
  });

  await Promise.all(tasks);

  // 统一输出：合并 frames_info + OCR 结果
  // 按 frameId 排序
  results.slides.sort((a, b) => a.frameId - b.frameId);

  // 统一输出格式
  const unifiedOutput = {
    videoInfo: framesInfo.videoInfo || {},
    totalSlides: results.slides.length,
    successCount: results.slides.length,
    errorCount: results.errors.length,
    slides: results.slides,
    errors: results.errors.length > 0 ? results.errors : undefined
  };

  // 移除 undefined 的 errors 字段
  if (!unifiedOutput.errors) {
    delete unifiedOutput.errors;
  }

  // 保存统一输出文件
  const slidesPath = path.join(options.outputDir, 'slides.json');
  fs.writeFileSync(slidesPath, JSON.stringify(unifiedOutput, null, 2));

  // 统计
  const totalTime = ((Date.now() - startTime) / 1000).toFixed(2);
  console.log('\n✅ OCR 完成！');
  console.log(`   成功: ${results.slides.length} 帧`);
  console.log(`   失败: ${results.errors.length} 帧`);
  console.log(`   耗时: ${totalTime} 秒`);
  console.log(`   输出: ${slidesPath}`);
}

main().catch(err => {
  console.error('❌ 错误:', err.message);
  process.exit(1);
});
