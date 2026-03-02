"""
PPT 关键帧提取任务

从视频中提取 PPT 关键帧，使用感知哈希方法（支持并发分段处理）。

功能：
1. 按固定间隔采样视频帧
2. 使用 phash 感知哈希检测帧差异
3. 只保留差异超过阈值的帧
4. 过滤非 PPT 内容（如黑屏、对话框等）
5. 对长视频自动分段并发处理，短视频保留单线程
"""

import json
import tempfile
import shutil
from pathlib import Path
from typing import Any
from concurrent.futures import ThreadPoolExecutor, as_completed
import multiprocessing

import cv2
from PIL import Image
import imagehash

from celery import shared_task
from core.config import settings
from core.exceptions import VideoProcessingException
from core.logging import setup_logging
from core.progress import ProgressStep
from services.redis_client import update_progress

logger = setup_logging()


class PPTExtractError(VideoProcessingException):
    """PPT 提取错误"""
    pass


# ────────────────────────────── 默认配置 ──────────────────────────────

DEFAULT_CONFIG = {
    'sample_interval_sec': settings.sample_interval_sec,      # 采样间隔（秒）
    'phash_size': settings.phash_size,                # phash 哈希大小
    'similarity_threshold': settings.similarity_threshold,      # phash 差异阈值
    'max_frames': settings.max_frames,               # 最大帧数
    'min_content_ratio': settings.min_content_ratio,       # 最小内容比例（过滤黑屏等）
    'output_width': settings.output_width,            # 输出图片宽度
    'output_quality': settings.output_quality,            # JPEG 质量
    'enable_slide_filter': settings.enable_slide_filter,     # 启用PPT内容过滤
    'enable_stability_check': settings.enable_stability_check, # 稳定性检测（较慢，按需开启）
    'stability_seconds': settings.stability_seconds,        # 稳定性检测窗口（秒）
    'min_frames_for_parallel': settings.min_frames_for_parallel, # 总帧数低于此值时使用单线程
    'num_workers': settings.num_workers,             # None = min(cpu_count, 8)
    'segments': None,                # None = 自动等于 num_workers
}


# ────────────────────────────── 工具函数 ──────────────────────────────

def _is_content_frame(frame, min_ratio=settings.min_content_ratio):
    """检查帧是否包含有效内容（非黑屏、非纯色等）"""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    non_black = cv2.countNonZero(gray)
    total = gray.shape[0] * gray.shape[1]
    return (non_black / total) >= min_ratio


def _compute_phash(frame_bgr, hash_size=settings.phash_size):
    """从 BGR numpy 数组计算 imagehash.ImageHash"""
    pil_image = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
    return imagehash.phash(pil_image, hash_size=hash_size)


def _save_frame(frame_bgr, filepath, output_width, orig_width, orig_height, quality):
    """缩放并用 PIL 保存 JPEG"""
    if output_width and output_width < orig_width:
        scale = output_width / orig_width
        new_h = int(orig_height * scale)
        frame_bgr = cv2.resize(frame_bgr, (output_width, new_h))
    pil_img = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
    pil_img.save(str(filepath), quality=quality, optimize=True)


def _calc_frame_interval(fps, sample_interval_sec):
    """根据实际帧率计算采样间隔帧数"""
    interval = max(1, int(round(fps * sample_interval_sec)))
    return interval


def _is_slide_frame(frame, config):
    """
    综合判断：这一帧是否像 PPT 幻灯片
    过滤掉：摄像头画面、过渡动画、弹窗对话框等
    """
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # 1. 过滤高频内容帧（摄像头/视频画面边缘多，PPT边缘少）
    edges = cv2.Canny(gray, 50, 150)
    edge_ratio = cv2.countNonZero(edges) / (h * w)
    if edge_ratio > 0.15:
        return False

    # 2. 过滤低信息量帧（纯色、渐变、黑屏白屏）
    std_dev = gray.std()
    if std_dev < 15:
        return False

    # 3. 过滤小窗口/对话框帧（PPT通常占满屏幕）
    border_size = int(min(h, w) * 0.05)
    borders = [
        gray[:border_size, :],
        gray[-border_size:, :],
        gray[:, :border_size],
        gray[:, -border_size:],
    ]
    uniform_borders = sum(1 for b in borders if b.std() < 10)
    if uniform_borders >= 3:
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
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = 25.0

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

    interval = _calc_frame_interval(fps, config['sample_interval_sec'])
    threshold = config['similarity_threshold']
    phash_size = config['phash_size']
    min_ratio = config['min_content_ratio']
    out_width = config['output_width']
    quality = config['output_quality']
    max_frames = config['max_frames']
    enable_slide_filter = config.get('enable_slide_filter', True)
    enable_stability_check = config.get('enable_stability_check', True)
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
            if _is_content_frame(frame, min_ratio):
                try:
                    if enable_slide_filter and not _is_slide_frame(frame, config):
                        frame_idx += 1
                        continue

                    current_hash = _compute_phash(frame, phash_size)

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
                        tmp_path = Path(tmp_dir) / tmp_filename
                        _save_frame(frame, tmp_path, out_width, width, height, quality)

                        results.append({
                            'frameNumber': frame_idx,
                            'timestamp': round(timestamp, 3),
                            'tmp_path': str(tmp_path),
                            'phash_hex': str(current_hash),
                        })

                        second_last_hash = last_hash
                        last_hash = current_hash

                        if max_frames > 0 and len(results) >= max_frames:
                            break
                except Exception:
                    pass

        frame_idx += 1

    cap.release()
    return results


# ────────────────────── 并发提取 ──────────────────────

def _extract_frames_parallel(video_path: str, output_dir: Path, config: dict, task_id: str) -> list[dict]:
    """并发分段提取关键帧"""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise PPTExtractError(f"无法打开视频: {video_path}")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = 25.0
    # width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    # height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration = total_frames / fps
    cap.release()

    interval = _calc_frame_interval(fps, config['sample_interval_sec'])

    # 决定工作进程数
    cpu = multiprocessing.cpu_count()
    num_workers = config.get('num_workers') or min(cpu, 8)
    num_segments = config.get('segments') or num_workers

    logger.info(f"并发模式: {num_workers} 进程, {num_segments} 段")
    logger.info(f"帧率: {fps:.2f} fps, 采样: 每 {config['sample_interval_sec']}s = 每 {interval} 帧")
    logger.info(f"总帧: {total_frames}, 时长: {duration/60:.1f}分钟")

    # 计算每段的帧范围
    seg_size = total_frames // num_segments
    segments = []
    for i in range(num_segments):
        s = i * seg_size
        e = (i + 1) * seg_size if i < num_segments - 1 else total_frames
        segments.append((s, e))

    images_dir = output_dir / 'images'
    images_dir.mkdir(parents=True, exist_ok=True)

    # 临时目录存放各段产出
    tmp_dir = tempfile.mkdtemp(prefix='frames_tmp_')

    # 提交任务
    all_results = [None] * num_segments
    try:
        with ThreadPoolExecutor(max_workers=num_workers) as pool:
            futures = {}
            for idx, (s, e) in enumerate(segments):
                f = pool.submit(_process_segment, video_path, s, e, config, tmp_dir, idx)
                futures[f] = idx

            for f in as_completed(futures):
                seg_idx = futures[f]
                try:
                    seg_results = f.result()
                    all_results[seg_idx] = seg_results
                    logger.info(f"段 {seg_idx} 完成, 提取 {len(seg_results)} 帧")
                    
                    # 更新进度
                    progress = 0.2 + ((seg_idx + 1) / num_segments) * 0.1
                    update_progress(task_id, ProgressStep.PPT_EXTRACT, progress, 
                                  f"提取关键帧: 段 {seg_idx+1}/{num_segments}")
                except Exception as exc:
                    logger.error(f"段 {seg_idx} 异常: {exc}")
                    all_results[seg_idx] = []
    except KeyboardInterrupt:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise PPTExtractError("用户中断")

    # 段间去重合并
    logger.info("段间去重合并...")
    merged = []
    threshold = config['similarity_threshold']
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
    if config['max_frames'] > 0 and len(merged) > config['max_frames']:
        logger.info(f"合并后 {len(merged)} 帧, 截断到 {config['max_frames']}")
        merged = merged[:config['max_frames']]

    # 重新编号 & 移动文件到最终目录
    frames_info = []
    for new_idx, item in enumerate(merged):
        filename = f"frame_{new_idx:05d}.jpg"
        dst = images_dir / filename
        try:
            shutil.move(item['tmp_path'], str(dst))
        except Exception as e:
            logger.warning(f"移动文件失败: {e}")
            continue
        frames_info.append({
            'index': new_idx,
            'filename': filename,
            'path': str(dst.resolve()),
            'timestamp': item['timestamp'],
            'frameNumber': item['frameNumber'],
        })

    # 清理临时目录
    shutil.rmtree(tmp_dir, ignore_errors=True)
    
    logger.info(f"并发提取完成: {len(frames_info)} 帧")
    return frames_info


# ────────────────────── 单线程提取 ──────────────────────

def _extract_frames_single(video_path: str, output_dir: Path, config: dict, task_id: str) -> list[dict]:
    """单线程提取关键帧"""
    logger.info("单线程模式")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise PPTExtractError(f"无法打开视频: {video_path}")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = 25.0

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration = total_frames / fps

    interval = _calc_frame_interval(fps, config['sample_interval_sec'])

    logger.info(f"分辨率: {width}x{height}, 帧率: {fps:.2f} fps")
    logger.info(f"时长: {duration/60:.1f} 分钟, 采样: 每 {config['sample_interval_sec']}s = 每 {interval} 帧")

    images_dir = output_dir / 'images'
    images_dir.mkdir(parents=True, exist_ok=True)

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
            if _is_content_frame(frame, min_ratio):
                try:
                    if enable_slide_filter and not _is_slide_frame(frame, config):
                        frame_idx += 1
                        continue

                    current_hash = _compute_phash(frame, phash_size)

                    is_duplicate = False
                    if last_hash is not None and (current_hash - last_hash) <= threshold:
                        is_duplicate = True
                    if not is_duplicate and second_last_hash is not None \
                       and (current_hash - second_last_hash) <= threshold:
                        is_duplicate = True

                    if not is_duplicate:
                        timestamp = frame_idx / fps
                        filename = f"frame_{saved_idx:05d}.jpg"
                        filepath = images_dir / filename
                        _save_frame(frame, filepath, out_width, width, height, quality)

                        frames_info.append({
                            'index': saved_idx,
                            'filename': filename,
                            'path': str(filepath.resolve()),
                            'timestamp': round(timestamp, 3),
                            'frameNumber': frame_idx,
                        })

                        second_last_hash = last_hash
                        last_hash = current_hash
                        saved_idx += 1

                        if saved_idx % 10 == 0:
                            progress = 0.2 + (frame_idx / total_frames) * 0.1
                            update_progress(task_id, ProgressStep.PPT_EXTRACT, progress,
                                          f"提取关键帧: {saved_idx} 帧")
                        if max_frames > 0 and saved_idx >= max_frames:
                            logger.info(f"达到上限: {max_frames}")
                            break
                except Exception as e:
                    logger.warning(f"异常 (frame {frame_idx}): {e}")

        frame_idx += 1

    cap.release()
    logger.info(f"完成: {saved_idx} 帧")
    return frames_info


# ────────────────────── Celery 任务入口 ──────────────────────

@shared_task(
    name="tasks.ppt.extract_frames",
    bind=True,
    max_retries=2,
)
def extract_ppt_frames(
    self,
    task_id: str,
    video_path: str,
    output_dir: str,
    method: str = "opencv",
    **kwargs
) -> dict[str, Any]:
    """
    提取 PPT 关键帧

    Args:
        self: Celery 任务绑定
        task_id: 任务 ID
        video_path: 视频文件路径
        output_dir: 输出目录
        method: 提取方法 (opencv=感知哈希, ffmpeg=固定帧率)
        **kwargs: 额外配置参数

    Returns:
        提取结果信息
    """
    logger.info(f"开始提取 PPT 关键帧: {video_path}, 方法: {method}")

    update_progress(task_id, ProgressStep.PPT_EXTRACT, 0.2, "正在提取 PPT 关键帧...")

    try:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # 合并配置
        config = DEFAULT_CONFIG.copy()
        config.update(kwargs)

        if method == "opencv":
            # 使用感知哈希方法（自动选择单线程/并发）
            cap = cv2.VideoCapture(video_path)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            cap.release()

            min_for_parallel = config.get('min_frames_for_parallel', 3000)

            if total_frames < min_for_parallel:
                logger.info(f"总帧数 {total_frames} < {min_for_parallel}, 使用单线程")
                frames_info = _extract_frames_single(video_path, output_path, config, task_id)
            else:
                logger.info(f"总帧数 {total_frames} >= {min_for_parallel}, 使用并发")
                frames_info = _extract_frames_parallel(video_path, output_path, config, task_id)

        elif method == "ffmpeg":
            # 使用 FFmpeg 固定帧率采样
            from utils.ffmpeg import extract_frames as ffmpeg_extract

            images_dir = output_path / "images"
            frame_files = ffmpeg_extract(
                video_path=video_path,
                output_dir=str(images_dir),
                pattern="frame_%05d.jpg",
                fps=0.2,
                quality=2,
            )

            # 计算时间戳
            sample_interval_sec = 5.0
            frames_info = []
            for idx, frame_file in enumerate(frame_files):
                frame_file = Path(frame_file)
                timestamp = idx * sample_interval_sec

                frames_info.append({
                    "index": idx,
                    "filename": frame_file.name,
                    "path": str(frame_file.resolve()),
                    "timestamp": round(timestamp, 3),
                })
        else:
            raise PPTExtractError(f"不支持的提取方法: {method}")

        # 获取视频信息
        from utils.ffmpeg import get_video_info
        video_info = get_video_info(video_path)
        
        # 确保 duration 是浮点数
        duration = video_info.get("duration", 0)
        if isinstance(duration, str):
            duration = float(duration)
        video_info["duration"] = float(duration)

        # 保存 frames_info.json
        info_file = output_path / "frames_info.json"
        with open(info_file, "w", encoding="utf-8") as f:
            json.dump({
                "video_info": video_info,
                "frames": frames_info,
            }, f, ensure_ascii=False, indent=2)

        logger.info(f"PPT 关键帧提取完成: {len(frames_info)} 帧")

        update_progress(task_id, ProgressStep.PPT_EXTRACT, 0.3,
                       f"PPT 关键帧提取完成: {len(frames_info)} 帧")

        return {
            "success": True,
            "frames_dir": str(output_path / "images"),
            "info_file": str(info_file),
            "frame_count": len(frames_info),
            "method": method,
        }

    except Exception as e:
        logger.error(f"提取 PPT 关键帧失败: {e}", exc_info=True)
        update_progress(task_id, ProgressStep.PPT_EXTRACT, 0.0, f"PPT 提取失败: {str(e)}")
        raise PPTExtractError(f"提取 PPT 关键帧失败: {e}")