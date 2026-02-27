"""
视频处理路由

处理视频处理任务的创建、结果查询和文件下载。
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from fastapi import Path as FastAPIPath
from fastapi.responses import FileResponse, StreamingResponse

from api.schemas.common import ErrorCode, ProcessingMode, TaskStatus, TTSEngine
from api.schemas.requests import ProcessVideoRequest
from api.schemas.responses import (
    ErrorResponse,
    TaskSubmitResponse,
    VideoProcessResult,
    VideoResultResponse,
)
from services.redis_client import set_task_status

router = APIRouter(prefix="/api/v1/videos", tags=["videos"])


# ==================== 视频处理 ====================


@router.post("/process", response_model=TaskSubmitResponse, status_code=status.HTTP_202_ACCEPTED, summary="提交视频处理任务")
async def process_video(
    video_url: str | None = Form(default=None, description="视频 URL"),
    video_file: UploadFile | None = File(default=None, description="视频文件"),
    video_name: str = Form(default="video", description="视频名称"),
    mode: ProcessingMode = Form(default=ProcessingMode.ESSENTIAL, description="处理模式"),
    tts_engine: TTSEngine = Form(default=TTSEngine.DASHSCOPE, description="TTS 引擎"),
    voice: str = Form(default="Cherry", description="TTS 音色"),
    skip_transcribe: bool = Form(default=False, description="跳过转录"),
    skip_ocr: bool = Form(default=False, description="跳过 OCR"),
    options: str | None = Form(default=None, description="其他选项 (JSON)"),
) -> TaskSubmitResponse:
    """
    提交视频处理任务

    支持两种方式提交视频：
    1. **video_url**: 提供视频的 HTTP(S) URL，服务端下载
    2. **video_file**: 直接上传视频文件

    处理模式：
    - **essential**: 精要版，仅保留核心知识内容
    - **complete**: 完整版，保留核心和解释内容

    TTS 引擎：
    - **dashscope**: 使用阿里云 CosyVoice (需要 API Key)
    - **edgetts**: 使用微软 Edge TTS (免费)
    """
    # 验证输入
    if not video_url and not video_file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(
                error={
                    "code": ErrorCode.INVALID_REQUEST,
                    "message": "Either video_url or video_file must be provided",
                    "details": {},
                }
            ).model_dump(),
        )

    if video_url and video_file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(
                error={
                    "code": ErrorCode.INVALID_REQUEST,
                    "message": "Only one of video_url or video_file should be provided",
                    "details": {},
                }
            ).model_dump(),
        )

    # 生成任务 ID
    task_id = str(uuid.uuid4())
    now = datetime.now()

    # 解析选项
    options_dict: dict[str, Any] = {}
    if options:
        try:
            options_dict = json.loads(options)
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ErrorResponse(
                    error={
                        "code": ErrorCode.INVALID_REQUEST,
                        "message": "Invalid JSON in options parameter",
                        "details": {},
                    }
                ).model_dump(),
            )

    # 准备工作流参数
    workflow_params = {
        "task_id": task_id,
        "video_name": video_name,
        "mode": mode.value,
        "tts_engine": tts_engine.value,
        "tts_voice": voice,
        "skip_transcribe": skip_transcribe,
        "skip_ocr": skip_ocr,
        "options": options_dict,
    }

    # 提交 Celery 任务
    try:
        from tasks.workflows import process_video_workflow

        if video_file:
            # 保存上传的文件到临时位置
            import tempfile

            suffix = Path(video_file.filename).suffix or ".mp4"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                content = await video_file.read()
                tmp.write(content)
                video_path = tmp.name

            # 使用本地文件工作流
            process_video_workflow(
                video_path=video_path,
                **workflow_params,
            )
        else:
            # 使用 URL 下载工作流
            process_video_workflow(
                video_url=video_url,
                **workflow_params,
            )

        # 初始化任务状态
        set_task_status(
            task_id=task_id,
            status="pending",
            progress=0.0,
            message="任务已提交，等待处理",
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ErrorResponse(
                error={
                    "code": ErrorCode.INTERNAL_ERROR,
                    "message": f"Failed to submit task: {str(e)}",
                    "details": {},
                }
            ).model_dump(),
        )

    return TaskSubmitResponse(
        task_id=task_id,
        status=TaskStatus.PENDING,
        progress=0.0,
        current_step=None,
        message="任务已提交，等待处理",
        created_at=now,
        updated_at=now,
    )


@router.get("/{video_id}", response_model=VideoResultResponse, summary="获取视频处理结果")
async def get_video_result(video_id: str) -> VideoResultResponse:
    """
    获取视频的处理结果

    - **video_id**: 视频 ID (等同于 task_id)
    - 返回完整的处理结果，包括：
      - 浓缩视频 URL
      - 文稿信息 (分类、大纲、总结)
      - 各步骤输出文件
      - 统计信息
    """
    # video_id 就是 task_id
    task_id = video_id

    from services.redis_client import get_result, get_task_status

    # 获取任务状态
    task_data = get_task_status(task_id)

    if not task_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(
                error={
                    "code": ErrorCode.TASK_NOT_FOUND,
                    "message": f"Video {video_id} not found",
                    "details": {"video_id": video_id},
                }
            ).model_dump(),
        )

    try:
        task_status = TaskStatus(task_data["status"])
    except ValueError:
        task_status = TaskStatus.PENDING

    # 获取结果
    result_data = task_data.get("result")
    if task_status == TaskStatus.SUCCESS and not result_data:
        result_data = get_result(task_id)

    if not result_data:
        return VideoResultResponse(
            video_id=video_id,
            task_id=task_id,
            status=task_status,
            result=None,
        )

    # 构建响应
    process_result = _build_process_result(result_data)

    return VideoResultResponse(
        video_id=video_id,
        task_id=task_id,
        status=task_status,
        result=process_result,
    )


@router.get("/{video_id}/download", summary="下载处理后的视频")
async def download_video_file(
    video_id: str,
    type: str = Query(default="tts", description="视频类型: condensed (浓缩视频) | tts (带 TTS 的浓缩视频)"),
):
    """
    下载处理后的视频文件

    - **video_id**: 视频 ID
    - **type**: 下载类型
      - `condensed`: 纯浓缩视频
      - `tts`: 带 TTS 配音的浓缩视频 (默认)
    """
    from services.redis_client import get_result, get_task_status

    task_id = video_id
    task_data = get_task_status(task_id)

    if not task_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(
                error={
                    "code": ErrorCode.TASK_NOT_FOUND,
                    "message": f"Video {video_id} not found",
                    "details": {"video_id": video_id},
                }
            ).model_dump(),
        )

    result_data = task_data.get("result")
    if not result_data:
        result_data = get_result(task_id)

    if not result_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(
                error={
                    "code": ErrorCode.TASK_NOT_FOUND,
                    "message": f"Video result not found for {video_id}",
                    "details": {"video_id": video_id},
                }
            ).model_dump(),
        )

    # 确定文件路径
    files = result_data.get("files", {})

    if type == "tts":
        file_path = files.get("tts_audio")
    elif type == "condensed":
        # TODO: 实现纯浓缩视频生成
        file_path = files.get("condensed_video")
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(
                error={
                    "code": ErrorCode.INVALID_REQUEST,
                    "message": f"Invalid type: {type}",
                    "details": {},
                }
            ).model_dump(),
        )

    if not file_path or not Path(file_path).exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(
                error={
                    "code": ErrorCode.TASK_NOT_FOUND,
                    "message": f"Video file not found",
                    "details": {"type": type, "path": file_path},
                }
            ).model_dump(),
        )

    # 返回文件
    filename = Path(file_path).name
    return FileResponse(
        path=file_path,
        media_type="video/mp4",
        filename=filename,
    )


@router.get("/{video_id}/file/{file_type}", summary="下载特定文件")
async def download_file(
    video_id: str,
    file_type: str = FastAPIPath(description="文件类型"),
):
    """
    下载特定的输出文件

    支持的文件类型：
    - `transcript`: 转录结果 (JSON)
    - `classification_json`: 分类结果 (JSON)
    - `classification_md`: 分类报告 (MD)
    - `outline_json`: 章节大纲 (JSON)
    - `outline_md`: 章节大纲 (MD)
    - `summary`: 课程总结 (MD)
    - `key_points`: 核心要点 (MD)
    - `condensed_text`: 浓缩文本 (TXT)
    - `tts_audio`: TTS 音频 (MP3)
    """
    from services.redis_client import get_result, get_task_status

    task_id = video_id
    task_data = get_task_status(task_id)

    if not task_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(
                error={
                    "code": ErrorCode.TASK_NOT_FOUND,
                    "message": f"Video {video_id} not found",
                    "details": {"video_id": video_id},
                }
            ).model_dump(),
        )

    result_data = task_data.get("result")
    if not result_data:
        result_data = get_result(task_id)

    if not result_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(
                error={
                    "code": ErrorCode.TASK_NOT_FOUND,
                    "message": f"Video result not found for {video_id}",
                    "details": {"video_id": video_id},
                }
            ).model_dump(),
        )

    # 文件类型映射
    file_mapping: dict[str, tuple[str, str]] = {
        "transcript": ("transcript", "application/json"),
        "classification_json": ("classification", "application/json"),
        "classification_md": ("classification", "text/markdown"),
        "outline_json": ("outline", "application/json"),
        "outline_md": ("outline_md", "text/markdown"),
        "summary": ("summary", "text/markdown"),
        "key_points": ("key_points", "text/markdown"),
        "condensed_text": ("condensed", "text/plain"),
        "tts_audio": ("tts_audio", "audio/mpeg"),
    }

    if file_type not in file_mapping:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(
                error={
                    "code": ErrorCode.INVALID_REQUEST,
                    "message": f"Invalid file_type: {file_type}",
                    "details": {"valid_types": list(file_mapping.keys())},
                }
            ).model_dump(),
        )

    key, media_type = file_mapping[file_type]
    files = result_data.get("files", {})
    file_path = files.get(key)

    if not file_path or not Path(file_path).exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(
                error={
                    "code": ErrorCode.TASK_NOT_FOUND,
                    "message": f"File not found: {file_type}",
                    "details": {"file_type": file_type, "path": file_path},
                }
            ).model_dump(),
        )

    # 返回文件
    filename = Path(file_path).name
    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=filename,
    )


# ==================== 辅助函数 ====================


def _build_process_result(result_data: dict) -> VideoProcessResult:
    """从 Redis 结果数据构建 VideoProcessResult"""
    from api.schemas.responses import (
        ChapterInfo,
        ScriptFileInfo,
        Statistics,
        StepFileInfo,
    )

    files = result_data.get("files", {})
    stats = result_data.get("statistics", {})

    # 构建文稿文件信息
    script = ScriptFileInfo(
        transcript_converted=_make_file_info(files.get("transcript")),
        classification=_make_file_info(files.get("classification")),
        outline=_make_file_info(files.get("outline")),
        condensed_text=_make_file_info(files.get("condensed")),
        summary=_make_file_info(files.get("summary")),
        key_points=_make_file_info(files.get("key_points")),
    )

    # 构建步骤文件信息
    steps = StepFileInfo(
        transcribe={
            "audio_url": files.get("audio"),
            "transcript_url": files.get("transcript"),
        },
        ppt={
            "frames_dir": files.get("ppt_frames"),
            "ocr_result_url": files.get("ppt_ocr"),
        },
        audio={
            "tts_segments_dir": None,
            "audio_timing_url": None,
            "tts_audio_url": files.get("tts_audio"),
        },
    )

    # 统计信息
    statistics = Statistics(
        duration=stats.get("duration"),
        sentences=stats.get("statistics", {}).get("sentences"),
        chapters_count=stats.get("chapter_count"),
    )

    # 章节信息 (从 outline.json 读取)
    chapters = []
    outline_path = files.get("outline")
    if outline_path and Path(outline_path).exists():
        try:
            with open(outline_path, "r", encoding="utf-8") as f:
                outline_data = json.load(f)
                for ch in outline_data.get("chapters", []):
                    chapters.append(
                        ChapterInfo(
                            id=ch.get("id", 0),
                            title=ch.get("title", ""),
                            start_time=ch.get("start_time", 0.0),
                            end_time=ch.get("end_time", 0.0),
                            duration=ch.get("duration", 0.0),
                            core_sentences=ch.get("core_sentences", 0),
                            keywords=ch.get("keywords", []),
                            key_formulas=ch.get("key_formulas", []),
                        )
                    )
        except Exception:
            pass

    return VideoProcessResult(
        condensed_video_url=None,  # TODO: 实现视频剪辑后添加
        condensed_video_tts_url=files.get("tts_audio"),
        script=script,
        steps=steps,
        statistics=statistics,
        chapters=chapters,
    )


def _make_file_info(file_path: str | None) -> dict | None:
    """创建文件信息字典"""
    if not file_path:
        return None

    path = Path(file_path)
    if not path.exists():
        return None

    return {
        "url": file_path,
        "filename": path.name,
        "size": path.stat().st_size,
    }
