"""auth.py - STS AssumeRole pakai credentials dari environment variables"""
import os, boto3, logging

logger = logging.getLogger(__name__)


def get_sts_session():
    ak = (os.getenv("AWS_ACCESS_KEY_ID_STS") or os.getenv("AWS_ACCESS_KEY_ID", "")).strip()
    sk = (os.getenv("AWS_SECRET_ACCESS_KEY_STS") or os.getenv("AWS_SECRET_ACCESS_KEY", "")).strip()
    if ak and sk:
        return boto3.Session(aws_access_key_id=ak, aws_secret_access_key=sk)
    return boto3.Session()


def assume_role(account_id, role_name, region):
    role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"
    logger.info(f"Assume role ke {role_arn}")
    try:
        base = get_sts_session()
        sts = base.client("sts", region_name=region)
        creds = sts.assume_role(RoleArn=role_arn, RoleSessionName="report-api", DurationSeconds=3600)["Credentials"]
        return boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
            region_name=region,
        )
    except Exception as e:
        logger.error(f"Gagal assume role: {e}")
        return None
