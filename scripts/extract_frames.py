#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
关键帧提取脚本（基于感知哈希） —— 并发分段处理版

功能：
1. 按固定间隔采样视频帧
2. 使用 phash 感知哈希检测帧差异
3. 只保留差异超过阈值的帧
4. 过滤非 PPT 内容（如黑屏、对话框等）
5. 对长视频自动分段并发处理，短视频保留单线程

用法: python extract_frames.py <video_path> [options]
输出: frames/images/*.jpg, frames_info.json
"""

import os
import sys
import json
import cv2
import argparse
import tempfile
import shutil
from PIL import Image
import imagehash
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing

# ────────────────────────────── 默认配置 ──────────────────────────────

DEFAULT_CONFIG = {
    'sample_interval_sec': 3.0,      # 采样间隔（秒），替代固定帧数
    'phash_size': 16,                # phash 哈希大小
    'similarity_threshold': 20,      # phash 差异阈值（提高以减少重复帧）
    'max_frames': 250,                # 最大帧数（降低以减少输出）
    'min_content_ratio': 0.15,       # 最小内容比例（过滤黑屏等）
    'output_width': 1920,            # 输出图片宽度
    'output_quality': 90,            # JPEG 质量
    'enable_slide_filter': True,     # 启用PPT内容过滤
    'enable_stability_check': False, # 稳定性检测（较慢，按需开启）
    'stability_seconds': 1.0,        # 稳定性检测窗口（秒）
    # ---- 并发相关 ----
    'min_frames_for_parallel': 3000,  # 总帧数低于此值时使用单线程
    'num_workers': None,              # None = min(cpu_count, 8)
    'segments': None,                 # None = 自动等于 num_workers
}

# ────────────────────────────── 工具函数 ──────────────────────────────

def is_content_frame(frame, min_ratio=0.1):
    """检查帧是否包含有效内容（非黑屏、非纯色等）"""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    non_black = cv2.countNonZero(gray)
    total = gray.shape[0] * gray.shape[1]
    return (non_black / total) >= min_ratio


def compute_phash(frame_bgr, hash_size=16):
    """从 BGR numpy 数组计算 imagehash.ImageHash"""
    pil_image = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
    return imagehash.phash(pil_image, hash_size=hash_size)


def save_frame(frame_bgr, filepath, output_width, orig_width, orig_height, quality):
    """缩放并用 PIL 保存 JPEG"""
    if output_width and output_width < orig_width:
        scale = output_width / orig_width
        new_h = int(orig_height * scale)
        frame_bgr = cv2.resize(frame_bgr, (output_width, new_h))
    pil_img = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
    pil_img.save(filepath, quality=quality, optimize=True)


def _calc_frame_interval(fps, sample_interval_sec):
    """根据实际帧率计算采样间隔帧数"""
    interval = max(1, int(round(fps * sample_interval_sec)))
    return interval


def is_slide_frame(frame, config):
    """
    综合判断：这一帧是否像 PPT 幻灯片
    过滤掉：摄像头画面、过渡动画、弹窗对话框等
    """
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # ---- 1. 过滤高频内容帧（摄像头/视频画面边缘多，PPT边缘少）----
    edges = cv2.Canny(gray, 50, 150)
    edge_ratio = cv2.countNonZero(edges) / (h * w)
    if edge_ratio > 0.15:   # 边缘占比超过15%，大概率不是PPT
        return False

    # ---- 2. 过滤低信息量帧（纯色、渐变、黑屏白屏）----
    std_dev = gray.std()
    if std_dev < 15:         # 标准差太低 → 接近纯色
        return False

    # ---- 3. 过滤小窗口/对话框帧（PPT通常占满屏幕）----
    #     检查画面四周边缘是否大面积同色（说明内容只占中间小区域）
    border_size = int(min(h, w) * 0.05)  # 取5%边框
    borders = [
        gray[:border_size, :],           # 上
        gray[-border_size:, :],          # 下
        gray[:, :border_size],           # 左
        gray[:, -border_size:],          # 右
    ]
    uniform_borders = sum(1 for b in borders if b.std() < 10)
    if uniform_borders >= 3:
        # 三条以上边框是纯色 → 可能是小窗口浮在背景上
        # 进一步检查中心区域是否有内容
        center = gray[h//4:3*h//4, w//4:3*w//4]
        center_ratio = cv2.countNonZero(center) / center.size
        if center_ratio < 0.2:
            return False

    return True


def is_stable_frame(cap, frame_idx, fps, stability_seconds=1.0,
                    hash_size=16, max_diff=3):
    """
    稳定性检测：检查当前帧前后一段时间内画面是否稳定
    过渡动画/翻页动效期间画面不稳定，自动跳过

    原理：在当前帧前后各取几帧，如果它们之间差异很小 → 画面静止 → 是PPT
    """
    check_offsets = [
        int(-stability_seconds * fps * 0.5),  # 前0.5秒
        int(stability_seconds * fps * 0.5),    # 后0.5秒
    ]

    original_pos = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
    hashes = []

    for offset in [0] + check_offsets:
        target = max(0, frame_idx + offset)
        cap.set(cv2.CAP_PROP_POS_FRAMES, target)
        ret, f = cap.read()
        if ret:
            pil_img = Image.fromarray(cv2.cvtColor(f, cv2.COLOR_BGR2RGB))
            hashes.append(imagehash.phash(pil_img, hash_size=hash_size))

    # 恢复读取位置
    cap.set(cv2.CAP_PROP_POS_FRAMES, original_pos)

    if len(hashes) < 2:
        return True  # 无法判断时默认通过

    # 所有采样帧与当前帧的差异都很小 → 画面稳定
    base = hashes[0]
    return all((h - base) <= max_diff for h in hashes[1:])

# ────────────────────── 单段处理（子进程入口） ──────────────────────

def _process_segment(video_path, start_frame, end_frame, config, tmp_dir, segment_id):
    """
    处理 [start_frame, end_frame) 范围内的帧。
    返回列表 [{frameNumber, timestamp, tmp_path, phash_hex}, ...]
    每个子进程独立打开视频，避免共享 VideoCapture。
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = 25.0  # 无法读取时的安全回退值

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

    # 根据实际fps动态计算帧间隔
    interval = _calc_frame_interval(fps, config['sample_interval_sec'])

    threshold = config['similarity_threshold']
    phash_size = config['phash_size']
    min_ratio = config['min_content_ratio']
    out_width = config['output_width']
    quality = config['output_quality']
    max_frames = config['max_frames']
    enable_slide_filter = config.get('enable_slide_filter', True)
    enable_stability_check = config.get('enable_stability_check', False)
    stability_seconds = config.get('stability_seconds', 1.0)

    results = []
    last_hash = None
    second_last_hash = None
    frame_idx = start_frame

    # 对齐到全局采样网格
    first_sample = start_frame + (interval - start_frame % interval) % interval

    while frame_idx < end_frame:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx >= first_sample and (frame_idx - first_sample) % interval == 0:
            if is_content_frame(frame, min_ratio):
                try:
                    # PPT内容过滤
                    if enable_slide_filter and not is_slide_frame(frame, config):
                        frame_idx += 1
                        continue

                    current_hash = compute_phash(frame, phash_size)

                    # 双重去重（与前两帧都比较）
                    is_duplicate = False
                    if last_hash is not None:
                        diff_last = current_hash - last_hash
                        if diff_last <= threshold:
                            is_duplicate = True
                    if not is_duplicate and second_last_hash is not None:
                        diff_second = current_hash - second_last_hash
                        if diff_second <= threshold:
                            is_duplicate = True

                    if not is_duplicate:
                        # 稳定性检测（可选）
                        if enable_stability_check:
                            if not is_stable_frame(cap, frame_idx, fps,
                                                    stability_seconds, phash_size):
                                frame_idx += 1
                                continue
                            # 重新seek回来（稳定性检测会移动指针）
                            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx + 1)

                        timestamp = frame_idx / fps
                        tmp_filename = f"seg{segment_id}_{len(results):05d}.jpg"
                        tmp_path = os.path.join(tmp_dir, tmp_filename)
                        save_frame(frame, tmp_path, out_width, width, height, quality)

                        results.append({
                            'frameNumber': frame_idx,
                            'timestamp': round(timestamp, 3),
                            'tmp_path': tmp_path,
                            'phash_hex': str(current_hash),
                        })

                        second_last_hash = last_hash
                        last_hash = current_hash

                        if len(results) >= max_frames:
                            break
                except Exception:
                    pass

        frame_idx += 1

    cap.release()
    return results

# ────────────────────── 并发调度 + 段间去重 ──────────────────────

def extract_frames_parallel(video_path, output_dir, config):
    """并发分段提取关键帧"""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"[!] 无法打开视频: {video_path}")
        return []

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = 25.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration = total_frames / fps
    cap.release()

    # 根据实际fps动态计算帧间隔
    interval = _calc_frame_interval(fps, config['sample_interval_sec'])

    # 决定工作进程数
    cpu = multiprocessing.cpu_count()
    num_workers = config.get('num_workers') or min(cpu, 8)
    num_segments = config.get('segments') or num_workers

    print(f"\n[*] 并发模式: {num_workers} 进程, {num_segments} 段")
    print(f"    帧率: {fps:.2f} fps")
    print(f"    采样: 每 {config['sample_interval_sec']}s = 每 {interval} 帧")
    print(f"    总帧: {total_frames}  时长: {duration/60:.1f}分钟")

    # 计算每段的帧范围
    seg_size = total_frames // num_segments
    segments = []
    for i in range(num_segments):
        s = i * seg_size
        e = (i + 1) * seg_size if i < num_segments - 1 else total_frames
        segments.append((s, e))

    images_dir = os.path.join(output_dir, 'images')
    os.makedirs(images_dir, exist_ok=True)

    # 临时目录存放各段产出
    tmp_dir = tempfile.mkdtemp(prefix='frames_tmp_')

    # ---- 提交任务 ----
    all_results = [None] * num_segments
    try:
        with ProcessPoolExecutor(max_workers=num_workers) as pool:
            futures = {}
            for idx, (s, e) in enumerate(segments):
                f = pool.submit(_process_segment, video_path, s, e, config, tmp_dir, idx)
                futures[f] = idx

            for f in as_completed(futures):
                seg_idx = futures[f]
                try:
                    seg_results = f.result()
                    all_results[seg_idx] = seg_results
                    print(f"    段 {seg_idx} 完成, 提取 {len(seg_results)} 帧"
                          f" (范围 {segments[seg_idx][0]}-{segments[seg_idx][1]})")
                except Exception as exc:
                    print(f"    [!] 段 {seg_idx} 异常: {exc}")
                    all_results[seg_idx] = []
    except KeyboardInterrupt:
        print("\n[!] 用户中断")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        sys.exit(1)

    # ---- 段间去重合并 ----
    print("\n[*] 段间去重合并...")
    merged = []
    threshold = config['similarity_threshold']
    phash_size = config['phash_size']
    last_hash = None

    for seg_frames in all_results:
        if not seg_frames:
            continue
        for item in seg_frames:
            current_hash = imagehash.hex_to_hash(item['phash_hex'])
            if last_hash is None or (current_hash - last_hash) > threshold:
                merged.append(item)
                last_hash = current_hash

    # 截断到 max_frames
    if len(merged) > config['max_frames']:
        print(f"    [!] 合并后 {len(merged)} 帧, 截断到 {config['max_frames']}")
        merged = merged[:config['max_frames']]

    # ---- 重新编号 & 移动文件到最终目录 ----
    frames_info = []
    for new_idx, item in enumerate(merged):
        filename = f"frame_{new_idx:05d}.jpg"
        dst = os.path.join(images_dir, filename)
        try:
            shutil.move(item['tmp_path'], dst)
        except Exception as e:
            print(f"    [!] 移动文件失败: {e}")
            continue
        frames_info.append({
            'index': new_idx,
            'filename': filename,
            'path': os.path.abspath(dst),
            'timestamp': item['timestamp'],
            'frameNumber': item['frameNumber'],
        })

    # 清理临时目录
    shutil.rmtree(tmp_dir, ignore_errors=True)

    print(f"\n[+] 并发提取完成！")
    print(f"    提取帧数: {len(frames_info)}")
    print(f"    保存目录: {images_dir}")

    # ---- 保存 JSON ----
    info_path = os.path.join(output_dir, 'frames_info.json')
    output_data = {
        'videoPath': os.path.abspath(video_path),
        'videoInfo': {
            'width': width, 'height': height,
            'fps': fps, 'duration': duration,
            'totalFrames': total_frames,
        },
        'extractedAt': datetime.now().isoformat(),
        'config': {k: v for k, v in config.items()
                   if k not in ('num_workers', 'segments', 'min_frames_for_parallel')},
        'actualFrameInterval': interval,
        'parallelInfo': {
            'workers': num_workers,
            'segments': num_segments,
            'segmentRanges': segments,
        },
        'totalFrames': len(frames_info),
        'frames': frames_info,
    }
    with open(info_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    print(f"    帧信息: {info_path}")

    return frames_info

# ────────────────────── 单线程提取（保留原版逻辑） ──────────────────────

def extract_frames_single(video_path, output_dir, config):
    """单线程提取关键帧（短视频或用户显式指定时使用）"""
    print("[*] 单线程模式")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"[!] 无法打开视频: {video_path}")
        return []

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = 25.0

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration = total_frames / fps

    # 根据实际fps动态计算帧间隔
    interval = _calc_frame_interval(fps, config['sample_interval_sec'])

    print(f"    分辨率: {width}x{height}")
    print(f"    帧率: {fps:.2f} fps")
    print(f"    时长: {duration/60:.1f} 分钟")
    print(f"    采样: 每 {config['sample_interval_sec']}s = 每 {interval} 帧")

    images_dir = os.path.join(output_dir, 'images')
    os.makedirs(images_dir, exist_ok=True)

    frames_info = []
    frame_idx = 0
    saved_idx = 0
    last_hash = None
    second_last_hash = None

    threshold = config['similarity_threshold']
    phash_size = config['phash_size']
    min_ratio = config['min_content_ratio']
    out_width = config['output_width']
    quality = config['output_quality']
    max_frames = config['max_frames']
    enable_slide_filter = config.get('enable_slide_filter', True)

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % interval == 0:
            if is_content_frame(frame, min_ratio):
                try:
                    if enable_slide_filter and not is_slide_frame(frame, config):
                        frame_idx += 1
                        continue

                    current_hash = compute_phash(frame, phash_size)

                    is_duplicate = False
                    if last_hash is not None and (current_hash - last_hash) <= threshold:
                        is_duplicate = True
                    if not is_duplicate and second_last_hash is not None \
                       and (current_hash - second_last_hash) <= threshold:
                        is_duplicate = True

                    if not is_duplicate:
                        timestamp = frame_idx / fps
                        filename = f"frame_{saved_idx:05d}.jpg"
                        filepath = os.path.join(images_dir, filename)
                        save_frame(frame, filepath, out_width, width, height, quality)

                        frames_info.append({
                            'index': saved_idx,
                            'filename': filename,
                            'path': os.path.abspath(filepath),
                            'timestamp': round(timestamp, 3),
                            'frameNumber': frame_idx,
                        })

                        second_last_hash = last_hash
                        last_hash = current_hash
                        saved_idx += 1

                        if saved_idx % 10 == 0:
                            print(f"    已提取: {saved_idx} 帧 ({frame_idx}/{total_frames})")
                        if saved_idx >= max_frames:
                            print(f"    [!] 达到上限: {max_frames}")
                            break
                except Exception as e:
                    print(f"    [!] 异常 (frame {frame_idx}): {e}")

        frame_idx += 1
        if frame_idx % 1000 == 0:
            print(f"    扫描: {frame_idx/total_frames*100:.1f}%")

    cap.release()
    print(f"\n[+] 完成: {saved_idx} 帧")

    # 保存 JSON
    info_path = os.path.join(output_dir, 'frames_info.json')
    output_data = {
        'videoPath': os.path.abspath(video_path),
        'videoInfo': {
            'width': width, 'height': height,
            'fps': fps, 'duration': duration,
            'totalFrames': total_frames,
        },
        'extractedAt': datetime.now().isoformat(),
        'config': config,
        'actualFrameInterval': interval,
        'totalFrames': saved_idx,
        'frames': frames_info,
    }
    with open(info_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    print(f"    帧信息: {info_path}")
    return frames_info

# ────────────────────── 统一入口 ──────────────────────

def extract_frames(video_path, output_dir, config):
    """
    统一入口：根据视频长度自动选择单线程或并发模式。
    """
    print(f"[*] 关键帧提取")
    print(f"    视频: {video_path}")
    print(f"    输出: {output_dir}")

    # 快速获取总帧数
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"[!] 无法打开视频: {video_path}")
        return []
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    min_for_parallel = config.get('min_frames_for_parallel',
                                   DEFAULT_CONFIG['min_frames_for_parallel'])

    if total_frames < min_for_parallel:
        print(f"    总帧数 {total_frames} < {min_for_parallel}, 使用单线程")
        return extract_frames_single(video_path, output_dir, config)
    else:
        print(f"    总帧数 {total_frames} >= {min_for_parallel}, 使用并发")
        return extract_frames_parallel(video_path, output_dir, config)

# ────────────────────── CLI ──────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='关键帧提取（基于感知哈希，支持并发分段处理）')
    parser.add_argument('video', help='视频文件路径')
    parser.add_argument('--output', '-o', help='输出目录')
    parser.add_argument('--interval', '-i', type=float, default=DEFAULT_CONFIG['sample_interval_sec'],
                        help=f'采样间隔（秒，默认 {DEFAULT_CONFIG["sample_interval_sec"]}）')
    parser.add_argument('--threshold', '-t', type=int, default=DEFAULT_CONFIG['similarity_threshold'],
                        help=f'phash 差异阈值（默认 {DEFAULT_CONFIG["similarity_threshold"]}）')
    parser.add_argument('--max-frames', '-m', type=int, default=DEFAULT_CONFIG['max_frames'],
                        help=f'最大帧数（默认 {DEFAULT_CONFIG["max_frames"]}）')
    parser.add_argument('--phash-size', '-p', type=int, default=DEFAULT_CONFIG['phash_size'],
                        help=f'phash 哈希大小（默认 {DEFAULT_CONFIG["phash_size"]}）')
    parser.add_argument('--workers', '-w', type=int, default=None,
                        help=f'并发进程数（默认 min(CPU, 8)）')
    parser.add_argument('--segments', '-s', type=int, default=None,
                        help=f'视频分段数（默认 = workers）')
    parser.add_argument('--min-parallel', type=int, default=DEFAULT_CONFIG['min_frames_for_parallel'],
                        help=f'启用并发的最小帧数阈值（默认 {DEFAULT_CONFIG["min_frames_for_parallel"]}）')
    parser.add_argument('--force-single', action='store_true',
                        help='强制单线程模式')
    parser.add_argument('--no-slide-filter', action='store_true',
                        help='禁用PPT内容过滤')
    parser.add_argument('--stability-check', action='store_true',
                        help='启用稳定性检测（更精准但更慢）')

    args = parser.parse_args()

    if not os.path.exists(args.video):
        print(f"[!] 视频文件不存在: {args.video}")
        sys.exit(1)

    # 确定输出目录
    video_name = os.path.splitext(os.path.basename(args.video))[0]
    date_str = datetime.now().strftime('%Y-%m-%d')

    if args.output:
        output_dir = args.output
    else:
        video_dir = os.path.dirname(os.path.abspath(args.video))
        output_dir = os.path.join(video_dir, 'output',
                                  f'{date_str}_{video_name}', 'frames')

    # 组装配置
    config = {
        'sample_interval_sec': args.interval,
        'phash_size': args.phash_size,
        'similarity_threshold': args.threshold,
        'max_frames': args.max_frames,
        'min_content_ratio': DEFAULT_CONFIG['min_content_ratio'],
        'output_width': DEFAULT_CONFIG['output_width'],
        'output_quality': DEFAULT_CONFIG['output_quality'],
        'enable_slide_filter': not args.no_slide_filter,
        'enable_stability_check': args.stability_check,
        'stability_seconds': DEFAULT_CONFIG['stability_seconds'],
        'min_frames_for_parallel': args.min_parallel,
        'num_workers': args.workers,
        'segments': args.segments,
    }

    if args.force_single:
        config['min_frames_for_parallel'] = float('inf')

    extract_frames(args.video, output_dir, config)


if __name__ == '__main__':
    # Windows 上 ProcessPoolExecutor 需要
    multiprocessing.freeze_support()
    main()
