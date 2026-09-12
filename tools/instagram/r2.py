"""Upload rendered images to Cloudflare R2.

Instagram fetches the image over HTTP at container-creation time, so the
object must be publicly readable at a stable URL — R2 is S3-compatible, so
boto3 talks to it directly.
"""
from __future__ import annotations

import mimetypes
from pathlib import Path

import boto3
from botocore.config import Config

import config


def client():
    account = config.require("SCIG_R2_ACCOUNT_ID")
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
        aws_access_key_id=config.require("SCIG_R2_ACCESS_KEY_ID"),
        aws_secret_access_key=config.require("SCIG_R2_SECRET_ACCESS_KEY"),
        region_name="auto",
        config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
    )


def upload(path: Path, key: str) -> str:
    """Put the object and return its public URL."""
    bucket = config.require("SCIG_R2_BUCKET")
    base = config.require("SCIG_R2_PUBLIC_BASE").rstrip("/")
    content_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    client().upload_file(
        str(path), bucket, key,
        ExtraArgs={"ContentType": content_type, "CacheControl": "public, max-age=31536000"},
    )
    return f"{base}/{key}"


def delete(key: str) -> None:
    client().delete_object(Bucket=config.require("SCIG_R2_BUCKET"), Key=key)
