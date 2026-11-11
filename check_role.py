"""
check_role.py - Cek apakah credentials STS & role di .env valid.

Tidak menampilkan secret. Hanya: prefix key, panjang, dan hasil panggilan STS.

Usage:
    python check_role.py                          # cek 4 akun default
    python check_role.py 204687258328 533267210314
    python check_role.py -r ap-southeast-1 204687258328
    python check_role.py --role bhp.engineer 204687258328
"""
import os
import sys
import argparse

import boto3
from botocore.exceptions import ClientError, EndpointConnectionError
from dotenv import load_dotenv

DEFAULT_ACCOUNTS = {
    "204687258328": "Prod",
    "533267210314": "MPA",
    "741229008145": "SecHub",
    "170608461341": "Aggregator Log",
}


def ok(msg):
    print(f"  [OK]   {msg}")


def fail(msg):
    print(f"  [FAIL] {msg}")


def warn(msg):
    print(f"  [WARN] {msg}")


def err_text(e):
    if isinstance(e, ClientError):
        c = e.response.get("Error", {})
        return f"{c.get('Code')}: {c.get('Message')}"
    return f"{type(e).__name__}: {e}"


def load_keys():
    """Sama seperti auth.get_sts_session(): *_STS dulu, lalu fallback AWS_*."""
    ak_sts = os.getenv("AWS_ACCESS_KEY_ID_STS")
    sk_sts = os.getenv("AWS_SECRET_ACCESS_KEY_STS")
    ak = (ak_sts or os.getenv("AWS_ACCESS_KEY_ID", "")).strip()
    sk = (sk_sts or os.getenv("AWS_SECRET_ACCESS_KEY", "")).strip()
    source = "AWS_*_STS" if ak_sts else ("AWS_ACCESS_KEY_ID (fallback)" if ak else "-")
    return ak, sk, source


def step_credentials(ak, sk, source, region):
    print("\n[1] Credentials dasar")
    if not ak or not sk:
        fail("Access key / secret kosong. Isi AWS_ACCESS_KEY_ID_STS & AWS_SECRET_ACCESS_KEY_STS di .env")
        return False
    print(f"  sumber   : {source}")
    print(f"  key      : {ak[:4]}... (panjang {len(ak)})")
    print(f"  secret   : panjang {len(sk)}")
    if len(ak) != 20:
        warn("Panjang access key normalnya 20. Kemungkinan terpotong / ada karakter tambahan.")
    if len(sk) != 40:
        warn("Panjang secret key normalnya 40. Kemungkinan terpotong / ada karakter tambahan.")
    if ak.startswith("ASIA"):
        fail("Key berawalan ASIA = temporary credentials, butuh session token (tidak didukung auth.py).")
        return False

    good = True
    for r in dict.fromkeys(["us-east-1", region]):
        try:
            sts = boto3.client("sts", aws_access_key_id=ak, aws_secret_access_key=sk, region_name=r)
            who = sts.get_caller_identity()
            ok(f"get_caller_identity di {r}: {who['Arn']} (akun {who['Account']})")
        except Exception as e:
            good = False
            fail(f"get_caller_identity di {r}: {err_text(e)}")
            if r == region and r != "us-east-1":
                warn(f"Jika us-east-1 OK tapi {r} gagal: kemungkinan region opt-in belum aktif.")
    return good


def step_assume(ak, sk, account_id, label, role, region):
    arn = f"arn:aws:iam::{account_id}:role/{role}"
    print(f"\n[2] Assume role -> {label or account_id}")
    print(f"  role arn : {arn}")
    try:
        sts = boto3.client("sts", aws_access_key_id=ak, aws_secret_access_key=sk, region_name=region)
        creds = sts.assume_role(RoleArn=arn, RoleSessionName="check-role", DurationSeconds=3600)["Credentials"]
    except Exception as e:
        fail(f"{err_text(e)}")
        if isinstance(e, ClientError):
            code = e.response["Error"]["Code"]
            if code == "AccessDenied":
                warn("Role tidak ada di akun itu ATAU trust policy tidak mengizinkan user pemilik key.")
            elif code == "InvalidClientTokenId":
                warn("Key dasar tidak valid / region STS belum aktif (lihat langkah [1]).")
        elif isinstance(e, EndpointConnectionError):
            warn("Region tidak valid / tidak bisa dijangkau.")
        return False

    # Pastikan hasilnya benar-benar akun target
    s = boto3.Session(aws_access_key_id=creds["AccessKeyId"],
                      aws_secret_access_key=creds["SecretAccessKey"],
                      aws_session_token=creds["SessionToken"], region_name=region)
    who = s.client("sts").get_caller_identity()
    ok(f"assume role berhasil: {who['Arn']}")

    # Cek akses read-only yang dipakai aplikasi (informasi saja)
    probes = {
        "ec2:DescribeInstances": lambda: s.client("ec2").describe_instances(MaxResults=5),
        "cloudwatch:ListMetrics": lambda: s.client("cloudwatch").list_metrics(),
        "ce:GetCostAndUsage": lambda: s.client("ce", region_name="us-east-1").get_cost_and_usage(
            TimePeriod={"Start": "2026-10-01", "End": "2026-10-02"},
            Granularity="DAILY", Metrics=["UnblendedCost"]),
        "guardduty:ListDetectors": lambda: s.client("guardduty").list_detectors(),
    }
    for name, fn in probes.items():
        try:
            fn()
            ok(f"permission {name}")
        except Exception as e:
            warn(f"permission {name}: {err_text(e)}")
    return True


def main():
    p = argparse.ArgumentParser(description="Cek credentials STS & role di .env")
    p.add_argument("accounts", nargs="*", help="Account ID (default: 4 akun BUMI)")
    p.add_argument("-r", "--region", default="ap-southeast-3")
    p.add_argument("--role", default=None, help="Override DEFAULT_ROLE_NAME")
    p.add_argument("--no-override", action="store_true",
                   help="Jangan timpa env var sistem dengan isi .env (perilaku aplikasi)")
    a = p.parse_args()

    # Aplikasi memakai load_dotenv() tanpa override. Default skrip ini: override,
    # supaya yang dites adalah isi .env. Pakai --no-override untuk meniru aplikasi.
    load_dotenv(override=not a.no_override)

    role = a.role or os.getenv("DEFAULT_ROLE_NAME", "").strip()
    print(f"Role name : {role or '(KOSONG)'}")
    print(f"Region    : {a.region}")
    if not role:
        print("DEFAULT_ROLE_NAME belum di-set di .env"); sys.exit(1)

    shadow = [k for k in ("AWS_ACCESS_KEY_ID_STS", "AWS_SECRET_ACCESS_KEY_STS",
                          "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")
              if os.environ.get(k)]
    print(f"Env terisi: {', '.join(shadow) or '-'}")

    ak, sk, source = load_keys()
    if not step_credentials(ak, sk, source, a.region):
        print("\nCredentials dasar bermasalah. Perbaiki dulu sebelum cek role per akun.")
        sys.exit(2)

    accounts = a.accounts or list(DEFAULT_ACCOUNTS)
    results = {acc: step_assume(ak, sk, acc, DEFAULT_ACCOUNTS.get(acc), role, a.region)
               for acc in accounts}

    print("\n=== Ringkasan ===")
    for acc, good in results.items():
        print(f"  {'OK  ' if good else 'FAIL'}  {acc}  {DEFAULT_ACCOUNTS.get(acc, '')}")
    sys.exit(0 if all(results.values()) else 3)


if __name__ == "__main__":
    main()
