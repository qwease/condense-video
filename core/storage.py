"""
存储抽象层

支持多种存储后端：
- local: 本地文件系统
- minio: MinIO 对象存储
- s3: AWS S3 兼容存储
"""

import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from core.config import settings
from core.exceptions import StorageException


class StorageBackend(ABC):
    """
    存储后端抽象接口

    所有存储后端必须实现这些方法。
    """

    @abstractmethod
    async def upload(self, file_path: str, object_name: str) -> str:
        """
        上传文件

        Args:
            file_path: 本地文件路径
            object_name: 存储对象名称

        Returns:
            文件的访问 URL

        Raises:
            StorageException: 上传失败
        """
        pass

    @abstractmethod
    async def download(self, object_name: str, local_path: str) -> None:
        """
        下载文件

        Args:
            object_name: 存储对象名称
            local_path: 本地保存路径

        Raises:
            StorageException: 下载失败
        """
        pass

    @abstractmethod
    async def get_url(self, object_name: str) -> str:
        """
        获取文件访问 URL

        Args:
            object_name: 存储对象名称

        Returns:
            文件的访问 URL
        """
        pass

    @abstractmethod
    async def delete(self, object_name: str) -> None:
        """
        删除文件

        Args:
            object_name: 存储对象名称

        Raises:
            StorageException: 删除失败
        """
        pass

    @abstractmethod
    async def exists(self, object_name: str) -> bool:
        """
        检查文件是否存在

        Args:
            object_name: 存储对象名称

        Returns:
            文件是否存在
        """
        pass


class LocalStorage(StorageBackend):
    """
    本地文件系统存储

    适用于开发环境。
    """

    def __init__(self, base_path: str | None = None):
        """
        初始化本地存储

        Args:
            base_path: 存储根路径，默认从配置读取
        """
        self.base_path = Path(base_path or settings.storage_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _get_full_path(self, object_name: str) -> Path:
        """获取文件的完整路径"""
        return self.base_path / object_name

    async def upload(self, file_path: str, object_name: str) -> str:
        """
        上传文件 (复制到存储目录)

        Args:
            file_path: 源文件路径
            object_name: 目标对象名称

        Returns:
            文件访问 URL
        """
        source = Path(file_path)
        target = self._get_full_path(object_name)

        # 创建目标目录
        target.parent.mkdir(parents=True, exist_ok=True)

        # 复制文件
        shutil.copy2(source, target)

        # 返回 URL (这里简化，实际需要配置静态文件服务)
        return f"/static/{object_name}"

    async def download(self, object_name: str, local_path: str) -> None:
        """
        下载文件 (从存储目录复制)

        Args:
            object_name: 存储对象名称
            local_path: 本地保存路径
        """
        source = self._get_full_path(object_name)
        target = Path(local_path)

        if not source.exists():
            raise StorageException(f"File not found: {object_name}")

        # 创建目标目录
        target.parent.mkdir(parents=True, exist_ok=True)

        shutil.copy2(source, target)

    async def get_url(self, object_name: str) -> str:
        """
        获取文件访问 URL

        Args:
            object_name: 存储对象名称

        Returns:
            文件访问 URL
        """
        return f"/static/{object_name}"

    async def delete(self, object_name: str) -> None:
        """
        删除文件

        Args:
            object_name: 存储对象名称
        """
        target = self._get_full_path(object_name)
        if target.exists():
            target.unlink()

    async def exists(self, object_name: str) -> bool:
        """
        检查文件是否存在

        Args:
            object_name: 存储对象名称

        Returns:
            文件是否存在
        """
        return self._get_full_path(object_name).exists()

    def health_check(self) -> bool:
        """
        检查存储健康状态

        Returns:
            是否健康
        """
        return self.base_path.exists() and self.base_path.is_dir()


class MinIOStorage(StorageBackend):
    """
    MinIO 对象存储

    兼容 S3 API 的自托管对象存储。
    """

    def __init__(self):
        """初始化 MinIO 客户端"""
        try:
            from minio import Minio

            self.client = Minio(
                settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure,
            )
            self.bucket = settings.minio_bucket

            # 确保存储桶存在
            self._ensure_bucket()
        except ImportError as e:
            raise StorageException("minio package is required for MinIO storage") from e

    def _ensure_bucket(self) -> None:
        """确保存储桶存在"""
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    async def upload(self, file_path: str, object_name: str) -> str:
        """
        上传文件到 MinIO

        Args:
            file_path: 本地文件路径
            object_name: 存储对象名称

        Returns:
            文件访问 URL
        """
        try:
            self.client.fput_object(self.bucket, object_name, file_path)
            return f"{settings.minio_endpoint}/{self.bucket}/{object_name}"
        except Exception as e:
            raise StorageException(f"MinIO upload failed: {e}") from e

    async def download(self, object_name: str, local_path: str) -> None:
        """
        从 MinIO 下载文件

        Args:
            object_name: 存储对象名称
            local_path: 本地保存路径
        """
        try:
            self.client.fget_object(self.bucket, object_name, local_path)
        except Exception as e:
            raise StorageException(f"MinIO download failed: {e}") from e

    async def get_url(self, object_name: str) -> str:
        """
        获取文件访问 URL

        Args:
            object_name: 存储对象名称

        Returns:
            文件访问 URL
        """
        # MinIO 默认的公开访问 URL 格式
        protocol = "https" if settings.minio_secure else "http"
        return f"{protocol}://{settings.minio_endpoint}/{self.bucket}/{object_name}"

    async def delete(self, object_name: str) -> None:
        """
        删除文件

        Args:
            object_name: 存储对象名称
        """
        try:
            self.client.remove_object(self.bucket, object_name)
        except Exception as e:
            raise StorageException(f"MinIO delete failed: {e}") from e

    async def exists(self, object_name: str) -> bool:
        """
        检查文件是否存在

        Args:
            object_name: 存储对象名称

        Returns:
            文件是否存在
        """
        try:
            self.client.stat_object(self.bucket, object_name)
            return True
        except Exception:
            return False

    def health_check(self) -> bool:
        """
        检查存储健康状态

        Returns:
            是否健康
        """
        try:
            # 尝试列出 bucket 来检查连接
            self.client.list_buckets()
            return True
        except Exception:
            return False


class S3Storage(StorageBackend):
    """
    AWS S3 兼容存储

    支持 AWS S3、阿里云 OSS 等 S3 兼容服务。
    """

    def __init__(self):
        """初始化 S3 客户端"""
        try:
            import boto3

            session = boto3.Session()
            self.client = session.client(
                "s3",
                endpoint_url=settings.s3_endpoint,
                aws_access_key_id=settings.s3_access_key_id,
                aws_secret_access_key=settings.s3_secret_access_key,
                region_name=settings.s3_region or "us-east-1",
            )
            self.bucket = settings.s3_bucket

            if not self.bucket:
                raise StorageException("S3_BUCKET is required for S3 storage")

        except ImportError as e:
            raise StorageException("boto3 package is required for S3 storage") from e

    async def upload(self, file_path: str, object_name: str) -> str:
        """
        上传文件到 S3

        Args:
            file_path: 本地文件路径
            object_name: 存储对象名称

        Returns:
            文件访问 URL
        """
        try:
            self.client.upload_file(file_path, self.bucket, object_name)
            # 构建公开访问 URL
            endpoint = settings.s3_endpoint or f"https://s3.{settings.s3_region or 'us-east-1'}.amazonaws.com"
            return f"{endpoint}/{self.bucket}/{object_name}"
        except Exception as e:
            raise StorageException(f"S3 upload failed: {e}") from e

    async def download(self, object_name: str, local_path: str) -> None:
        """
        从 S3 下载文件

        Args:
            object_name: 存储对象名称
            local_path: 本地保存路径
        """
        try:
            self.client.download_file(self.bucket, object_name, local_path)
        except Exception as e:
            raise StorageException(f"S3 download failed: {e}") from e

    async def get_url(self, object_name: str) -> str:
        """
        获取文件访问 URL

        Args:
            object_name: 存储对象名称

        Returns:
            文件访问 URL
        """
        endpoint = settings.s3_endpoint or f"https://s3.{settings.s3_region or 'us-east-1'}.amazonaws.com"
        return f"{endpoint}/{self.bucket}/{object_name}"

    async def delete(self, object_name: str) -> None:
        """
        删除文件

        Args:
            object_name: 存储对象名称
        """
        try:
            self.client.delete_object(Bucket=self.bucket, Key=object_name)
        except Exception as e:
            raise StorageException(f"S3 delete failed: {e}") from e

    async def exists(self, object_name: str) -> bool:
        """
        检查文件是否存在

        Args:
            object_name: 存储对象名称

        Returns:
            文件是否存在
        """
        try:
            self.client.head_object(Bucket=self.bucket, Key=object_name)
            return True
        except self.client.exceptions.ClientError:
            return False

    def health_check(self) -> bool:
        """
        检查存储健康状态

        Returns:
            是否健康
        """
        try:
            # 尝试列出对象来检查连接
            self.client.list_objects_v2(Bucket=self.bucket, MaxKeys=1)
            return True
        except Exception:
            return False


# 存储后端工厂
_storage_backend: StorageBackend | None = None


def get_storage() -> StorageBackend:
    """
    获取存储后端实例 (单例)

    Returns:
        配置的存储后端实例

    Raises:
        StorageException: 不支持的存储类型
    """
    global _storage_backend

    if _storage_backend is None:
        backend_type = settings.storage_backend

        backends: dict[str, type[StorageBackend]] = {
            "local": LocalStorage,
            "minio": MinIOStorage,
            "s3": S3Storage,
        }

        backend_class = backends.get(backend_type)
        if not backend_class:
            raise StorageException(f"Unsupported storage backend: {backend_type}")

        _storage_backend = backend_class()

    return _storage_backend


def reset_storage() -> None:
    """重置存储后端 (主要用于测试)"""
    global _storage_backend
    _storage_backend = None
