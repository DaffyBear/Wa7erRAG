from __future__ import annotations

import hashlib
import hmac
import shutil
from pathlib import Path
from urllib.parse import quote


class LocalObjectStore:
    def __init__(
        self,
        root: Path,
        public_base_url: str = "/api/v1/assets",
        signing_secret: str = "development-only-asset-signing-key",
    ) -> None:
        self.root = root.resolve()
        self.public_base_url = public_base_url.rstrip("/")
        self.signing_secret = signing_secret.encode()
        self.root.mkdir(parents=True, exist_ok=True)

    async def upload(self, local_path: Path, object_name: str) -> str:
        target = self._safe_path(object_name)
        target.parent.mkdir(parents=True, exist_ok=True)
        if local_path.resolve() != target:
            shutil.copy2(local_path, target)
        return self.resolve_url(object_name)

    def resolve_url(self, object_name: str) -> str:
        return _signed_url(self.public_base_url, object_name, self.signing_secret)

    async def read_bytes(self, object_name: str) -> bytes:
        return self._safe_path(object_name).read_bytes()

    def verify_signature(self, object_name: str, signature: str) -> bool:
        return _verify(object_name, signature, self.signing_secret)

    def _safe_path(self, object_name: str) -> Path:
        target = (self.root / object_name).resolve()
        if target != self.root and self.root not in target.parents:
            raise ValueError("Invalid object name")
        return target


class MinioObjectStore:
    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool = False,
        public_base_url: str = "/api/v1/assets",
        signing_secret: str = "development-only-asset-signing-key",
    ) -> None:
        from minio import Minio

        self.client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
        self.bucket = bucket
        self.public_base_url = public_base_url.rstrip("/")
        self.signing_secret = signing_secret.encode()
        if not self.client.bucket_exists(bucket):
            self.client.make_bucket(bucket)

    async def upload(self, local_path: Path, object_name: str) -> str:
        _validate_object_name(object_name)
        self.client.fput_object(self.bucket, object_name, str(local_path))
        return self.resolve_url(object_name)

    def resolve_url(self, object_name: str) -> str:
        return _signed_url(self.public_base_url, object_name, self.signing_secret)

    async def read_bytes(self, object_name: str) -> bytes:
        _validate_object_name(object_name)
        response = self.client.get_object(self.bucket, object_name)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def verify_signature(self, object_name: str, signature: str) -> bool:
        return _verify(object_name, signature, self.signing_secret)


def _signed_url(base_url: str, object_name: str, secret: bytes) -> str:
    _validate_object_name(object_name)
    signature = hmac.new(secret, object_name.encode(), hashlib.sha256).hexdigest()
    encoded_name = quote(object_name.replace("\\", "/"), safe="/")
    return f"{base_url}/{encoded_name}?signature={signature}"


def _verify(object_name: str, signature: str, secret: bytes) -> bool:
    try:
        _validate_object_name(object_name)
    except ValueError:
        return False
    expected = hmac.new(secret, object_name.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _validate_object_name(object_name: str) -> None:
    normalized = object_name.replace("\\", "/")
    if not normalized or normalized.startswith("/") or ".." in normalized.split("/"):
        raise ValueError("Invalid object name")
