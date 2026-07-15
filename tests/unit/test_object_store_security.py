from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from rag_core.infrastructure.object_store import LocalObjectStore


@pytest.mark.asyncio
async def test_local_object_store_uses_signed_safe_urls(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(b"image")
    store = LocalObjectStore(tmp_path / "objects", signing_secret="secret")
    url = await store.upload(source, "tenant/document/image.png")
    parsed = urlparse(url)
    signature = parse_qs(parsed.query)["signature"][0]
    assert store.verify_signature("tenant/document/image.png", signature)
    assert not store.verify_signature("other/document/image.png", signature)
    assert await store.read_bytes("tenant/document/image.png") == b"image"
    with pytest.raises(ValueError):
        await store.read_bytes("../secret")
