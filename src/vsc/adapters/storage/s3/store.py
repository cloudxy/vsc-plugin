"""S3/MinIO replica adapter; credentials are resolved by the SDK environment."""
import hashlib
from io import BytesIO

from vsc.assets.resource_service import ResourceError


class S3Storage:
    def __init__(self, bucket, client=None, endpoint_url=None, prefix="vsc/"):
        if client is None:
            import boto3
            client = boto3.client("s3", endpoint_url=endpoint_url)
        self.client, self.bucket, self.prefix = client, bucket, prefix.strip("/") + "/"

    def put(self, content):
        sha = hashlib.sha256(content).hexdigest()
        key = self.prefix + "blobs/" + sha[:2] + "/" + sha
        self.client.put_object(Bucket=self.bucket, Key=key, Body=content, Metadata={"sha256": sha})
        self.verify(key, sha)
        return {"storage": "s3", "object_key": key, "sha256": sha, "size_bytes": len(content)}

    def read(self, object_key, expected_sha):
        if not object_key.startswith(self.prefix) or ".." in object_key.split("/"):
            raise ResourceError("对象键越界", "unsafe_location")
        response = self.client.get_object(Bucket=self.bucket, Key=object_key)
        body = response["Body"]
        try:
            content = body.read()
        finally:
            body.close()
        if hashlib.sha256(content).hexdigest() != expected_sha:
            raise ResourceError("对象存储字节摘要不符", "media_unavailable")
        return content

    def verify(self, object_key, expected_sha):
        self.read(object_key, expected_sha)
        return True
