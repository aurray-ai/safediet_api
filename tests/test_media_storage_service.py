from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import UploadFile

from app.core.config import Settings
from app.services.media_storage_service import MediaStorageService


class MediaStorageServiceTests(unittest.TestCase):
    def test_resolve_public_base_url_prefers_configured_public_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = Settings(
                local_media_directory=temp_dir,
                api_public_base_url="https://example-tunnel.ngrok-free.dev",
            )
            service = MediaStorageService(settings)

            resolved = service.resolve_public_base_url(
                request_base_url="http://127.0.0.1:8000"
            )

            self.assertEqual("https://example-tunnel.ngrok-free.dev", resolved)

    def test_upload_image_uses_configured_public_url_for_local_storage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = Settings(
                local_media_directory=temp_dir,
                api_public_base_url="https://example-tunnel.ngrok-free.dev",
            )
            service = MediaStorageService(settings)
            upload = UploadFile(
                file=BytesIO(b"fake-image-bytes"),
                filename="banana.png",
                headers={"content-type": "image/png"},
            )

            stored = asyncio.run(
                service.upload_image(
                    file=upload,
                    folder="products",
                    public_base_url="http://127.0.0.1:8000",
                )
            )

            self.assertTrue(
                stored.url.startswith("https://example-tunnel.ngrok-free.dev/media/products/")
            )
            relative_path = stored.url.replace(
                "https://example-tunnel.ngrok-free.dev/media/",
                "",
                1,
            )
            self.assertTrue((Path(temp_dir) / relative_path).exists())

    def test_upload_image_uses_cloudinary_when_configured(self) -> None:
        class _FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, str]:
                return {
                    "secure_url": "https://res.cloudinary.com/demo/image/upload/v123/safedaet/products/item.png"
                }

        with tempfile.TemporaryDirectory() as temp_dir:
            settings = Settings(
                local_media_directory=temp_dir,
                cloudinary_cloud_name="demo",
                cloudinary_api_key="848378358214332",
                cloudinary_api_secret="test-secret",
                cloudinary_upload_folder_root="safedaet",
            )
            service = MediaStorageService(settings)
            upload = UploadFile(
                file=BytesIO(b"fake-image-bytes"),
                filename="banana.png",
                headers={"content-type": "image/png"},
            )

            with patch("app.services.media_storage_service.httpx.post", return_value=_FakeResponse()) as mock_post:
                stored = asyncio.run(
                    service.upload_image(
                        file=upload,
                        folder="products",
                        public_base_url="http://127.0.0.1:8000",
                    )
                )

            self.assertEqual("cloudinary", stored.storage_backend)
            self.assertEqual(
                "https://res.cloudinary.com/demo/image/upload/v123/safedaet/products/item.png",
                stored.url,
            )
            self.assertEqual("image/png", stored.content_type)

            _, kwargs = mock_post.call_args
            self.assertEqual(
                "https://api.cloudinary.com/v1_1/demo/image/upload",
                mock_post.call_args.args[0],
            )
            self.assertEqual("safedaet/products", kwargs["data"]["folder"])
            self.assertEqual("848378358214332", kwargs["data"]["api_key"])
            self.assertIn("signature", kwargs["data"])
            self.assertIn("timestamp", kwargs["data"])
            self.assertIn("public_id", kwargs["data"])


if __name__ == "__main__":
    unittest.main()
