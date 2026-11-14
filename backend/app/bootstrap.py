"""Explicit infrastructure initialization; API health checks never create resources."""

from botocore.exceptions import ClientError

from app.config import Settings
from app.infrastructure import s3_client


def ensure_bucket(settings: Settings):
    with s3_client(settings) as client:
        try:
            client.head_bucket(Bucket=settings.s3_bucket)
        except ClientError as error:
            if error.response["ResponseMetadata"]["HTTPStatusCode"] != 404:
                raise
            try:
                client.create_bucket(Bucket=settings.s3_bucket)
            except ClientError as creation_error:
                if creation_error.response["Error"]["Code"] != "BucketAlreadyOwnedByYou":
                    raise


if __name__ == "__main__":
    ensure_bucket(Settings())
    print("Object bucket is ready.")
