from __future__ import annotations

from pathlib import Path

from google.cloud import storage

from app.v2.providers.step_01_interfaces import ObjectStorageProvider


def parse_gcs_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("gs://"):
        raise ValueError("GCS URI must start with gs://")
    bucket, _, prefix = uri.removeprefix("gs://").partition("/")
    if not bucket:
        raise ValueError("GCS URI is missing a bucket.")
    return bucket, prefix.strip("/")


class GCSObjectStorageProvider(ObjectStorageProvider):
    def __init__(self, root_uri: str) -> None:
        bucket_name, self.prefix = parse_gcs_uri(root_uri)
        self.client = storage.Client()
        self.bucket = self.client.bucket(bucket_name)

    def put(self, source: Path, key: str) -> str:
        object_name = "/".join(part for part in (self.prefix, key.strip("/")) if part)
        blob = self.bucket.blob(object_name)
        blob.upload_from_filename(str(source))
        return f"gs://{self.bucket.name}/{object_name}"

    def get(self, uri: str, destination: Path) -> Path:
        bucket_name, object_name = parse_gcs_uri(uri)
        if bucket_name != self.bucket.name:
            raise ValueError("Object URI belongs to a different GCS bucket.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.bucket.blob(object_name).download_to_filename(str(destination))
        return destination
