"""
直接调用工作流（无 Redis 依赖）

调试版本，跳过所有 Redis 相关的状态更新。

用法:
    python run_workflow_debug.py merge.mp4
"""

import os
import sys
import time


# 禁用 Redis
os.environ["REDIS_DISABLED"] = "1"


def run_without_redis(
    video_path: str,
    mode: str = "essential",
    tts_engine: str = "dashscope",
) -> dict:
    """
    直接运行工作流（不通过 Celery，不使用 Redis）
    """
    task_id = f"debug-{int(time.time())}"

    print(f"""
╔════════════════════════════════════════════════════════════╗
║          直接调用工作流 (无 Redis)                         ║
╠════════════════════════════════════════════════════════════╣
║  task_id     : {task_id}
║  video_path  : {video_path}
║  mode        : {mode}
║  tts_engine  : {tts_engine}
╚════════════════════════════════════════════════════════════╝
""")

    # 导入并打补丁 Redis 函数
    from services import redis_client

    # Mock Redis 函数
    def mock_progress(*args, **kwargs):
        pass

    def mock_get_redis():
        return None

    redis_client.update_progress = mock_progress
    redis_client.set_task_status = mock_progress
    redis_client.get_redis = mock_get_redis

    # 导入工作流
    from tasks.workflows import process_video_workflow

    # 直接调用内部函数（绕过 Celery）
    if hasattr(process_video_workflow, '__wrapped__'):
        func = process_video_workflow.__wrapped__
    elif hasattr(process_video_workflow, 'run'):
        func = process_video_workflow.run
    else:
        func = process_video_workflow

    try:
        result = func(
            task_id=task_id,
            video_path=video_path,
            mode=mode,
            tts_engine=tts_engine,
        )

        print(f"\n{'='*60}")
        print("✓ 工作流完成")
        print(f"{'='*60}")

        # 打印结果文件
        if result and result.get("success"):
            files = result.get("files", {})
            stats = result.get("statistics", {})

            print("\n📁 输出文件:")
            for name, path in files.items():
                print(f"  {name:20} : {path}")

            if stats:
                print("\n📊 统计信息:")
                print(f"  {stats}")

        return result

    except Exception as e:
        print(f"\n❌ 工作流失败: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    video_path = sys.argv[1] if len(sys.argv) > 1 else "merge.mp4"

    run_without_redis(video_path)
