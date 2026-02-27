#!/usr/bin/env node
/**
 * 阿里云 DashScope 语音识别
 *
 * 用法: node dashscope_transcribe.js <audio_url> [output_file]
 * 输出: result.json (兼容格式)
 *
 * 环境变量:
 *   DASHSCOPE_API_KEY    阿里云 DashScope API Key
 */

const fs = require('fs');
const path = require('path');

// 解析参数
const args = process.argv.slice(2);
const audioUrl = args.find(a => !a.startsWith('--'));
const outputFile = args.find((a, i) => args[i-1] === '-o') || 'result.json';

if (!audioUrl) {
  console.log('❌ 用法: node dashscope_transcribe.js <audio_url> [-o output_file]');
  console.log('');
  console.log('参数:');
  console.log('  audio_url     音频文件 URL (支持 mp3, wav, m4a 等)');
  console.log('  -o file       输出文件名 (默认: result.json)');
  console.log('');
  console.log('环境变量:');
  console.log('  DASHSCOPE_API_KEY   阿里云 DashScope API Key (必需)');
  process.exit(1);
}

// 加载 DashScope 客户端
const { DashScopeClient } = require('./lib/dashscope');

async function main() {
  console.log('🎤 阿里云 DashScope 语音识别');
  console.log('📁 音频 URL:', audioUrl);

  // 检查 API Key
  const apiKey = process.env.DASHSCOPE_API_KEY;
  if (!apiKey) {
    // 尝试从 .env 文件加载
    const envPath = path.join(__dirname, '../../.env');
    if (fs.existsSync(envPath)) {
      const envContent = fs.readFileSync(envPath, 'utf8');
      const match = envContent.match(/DASHSCOPE_API_KEY\s*=\s*(.+)/);
      if (match) {
        process.env.DASHSCOPE_API_KEY = match[1].trim().replace(/['"]/g, '');
      }
    }
  }

  if (!process.env.DASHSCOPE_API_KEY) {
    console.error('❌ 请设置环境变量 DASHSCOPE_API_KEY');
    console.log('💡 提示: 创建 .env 文件并添加 DASHSCOPE_API_KEY=your-key');
    process.exit(1);
  }

  const client = new DashScopeClient();

  console.log('⏳ 提交转录任务...');

  try {
    // 调用 ASR API
    const result = await client.asrTranscribe(audioUrl, {
      language: 'zh',
      model: 'paraformer-v2'
    });

    // 保存结果
    fs.writeFileSync(outputFile, JSON.stringify(result, null, 2));

    // 统计
    const wordCount = result.utterances?.reduce((sum, u) => sum + (u.words?.length || 0), 0) || 0;
    const textLength = result.utterances?.reduce((sum, u) => sum + (u.text?.length || 0), 0) || 0;

    console.log('');
    console.log(`✅ 转录完成，已保存 ${outputFile}`);
    console.log(`📝 识别到 ${result.utterances?.length || 0} 段语音, ${wordCount} 个字`);

  } catch (err) {
    console.error('❌ 转录失败:', err.message);
    process.exit(1);
  }
}

main();
