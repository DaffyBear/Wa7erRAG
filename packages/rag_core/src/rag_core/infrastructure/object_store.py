from __future__ import annotations

import shutil
from pathlib import Path


class LocalObjectStore:
    def __init__(self, root: Path, public_base_url: str = "/assets") -> None:
        self.root = root
        self.public_base_url = public_base_url.rstrip("/")
        self.root.mkdir(parents=True, exist_ok=True)

    async def upload(self, local_path: Path, object_name: str) -> str:
        target = self.root / object_name
        target.parent.mkdir(parents=True, exist_ok=True)
        if local_path.resolve() != target.resolve():
            shutil.copy2(local_path, target)
        return self.resolve_url(object_name)

    def resolve_url(self, object_name: str) -> str:
        return f"{self.public_base_url}/{object_name.replace(chr(92), '/')}"


class MinioObjectStore:
    def __init__(
        self, endpoint: str, access_key: str, secret_key: str, bucket: str, secure: bool = False
    ) -> None:
        from minio import Minio

        self.client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
        self.bucket = bucket
        self.scheme = "https" if secure else "http"
        self.endpoint = endpoint
        if not self.client.bucket_exists(bucket):
            self.client.make_bucket(bucket)

    async def upload(self, local_path: Path, object_name: str) -> str:
        self.client.fput_object(self.bucket, object_name, str(local_path))
        return self.resolve_url(object_name)

    def resolve_url(self, object_name: str) -> str:
        return f"{self.scheme}://{self.endpoint}/{self.bucket}/{object_name}"
