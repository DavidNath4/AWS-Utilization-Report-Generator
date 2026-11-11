"""
app.py - FastAPI service untuk generate AWS utilization report

Endpoints:
  GET  /              — Web UI untuk upload & generate
  GET  /health        — Health check
  POST /preview       — Upload multiple .docx, return grouping preview
  POST /generate      — Upload multiple .docx, generate reports, return zip
  POST /generate-report — Single file (backward compatible)

Run lokal: python app.py
"""
import os, json, shutil, logging, tempfile, zipfile, io
from datetime import datetime, timedelta, timezone
from typing import List
from collections import defaultdict
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse

from docx_parser import parse_cloudviz_docx
from auth import assume_role
from collectors import (collect_ec2, collect_ebs, collect_rds, collect_s3,
    collect_drs, collect_vpn, collect_efs, collect_lightsail, collect_lightsail_buckets,
    collect_savings_plans, collect_cost_by_service, collect_guardduty,
    build_infrastructure_summary)
from report_generator import generate_report

load_dotenv()
logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
logger = logging.getLogger(__name__)
app = FastAPI(title="AWS Utilization Report API", version="2.0.0")

# In-memory log buffer for UI
import collections
log_buffer = collections.deque(maxlen=200)

class UILogHandler(logging.Handler):
    def emit(self, record):
        if record.levelno >= logging.WARNING:
            log_buffer.append(self.format(record))

_ui_handler = UILogHandler()
_ui_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
logging.getLogger().addHandler(_ui_handler)

def _group_name(customer_name):
    """Extract org name from customer name. 'TMLI-Prod' → 'TMLI', 'Rodamas' → 'Rodamas'."""
    parts = customer_name.split("-")
    return parts[0].strip()


def _parse_files(files_data):
    """Parse multiple docx files, return list of parsed info + group them."""
    parsed = []
    for fpath, fname in files_data:
        try:
            info = parse_cloudviz_docx(fpath)
            info["source_file"] = fname
            info["group"] = _group_name(info["customer_name"])
            parsed.append(info)
        except Exception as e:
            logger.warning(f"Gagal parse {fname}: {e}")
            parsed.append({"source_file": fname, "error": str(e)})
    return parsed


def _collect_for_account(account_id, region, role_name, period_days, tmp_dir, start_date=None, end_date=None):
    """Collect all AWS data for one account."""
    session = assume_role(account_id, role_name, region)
    if not session:
        raise Exception(f"Gagal assume role ke {account_id}")
    charts_dir = os.path.join(tmp_dir, f"charts_{account_id}")
    os.makedirs(charts_dir, exist_ok=True)
    ec2 = collect_ec2(session, period_days, charts_dir, start_date=start_date, end_date=end_date)
    ebs = collect_ebs(session, period_days)
    rds = collect_rds(session, period_days, charts_dir, start_date=start_date, end_date=end_date)
    s3 = collect_s3(session, period_days, start_date=start_date, end_date=end_date)
    drs = collect_drs(session, period_days, charts_dir, start_date=start_date, end_date=end_date)
    vpn = collect_vpn(session)
    efs = collect_efs(session)
    lightsail = collect_lightsail(session, period_days, charts_dir, start_date=start_date, end_date=end_date)
    lightsail_buckets = collect_lightsail_buckets(session, period_days, start_date=start_date, end_date=end_date)
    sp = collect_savings_plans(session, period_days, start_date=start_date, end_date=end_date)
    cost = collect_cost_by_service(session, period_days, start_date=start_date, end_date=end_date)
    guardduty = collect_guardduty(session, period_days, start_date=start_date, end_date=end_date)
    return {"ec2": ec2, "ebs": ebs, "rds": rds, "s3": s3, "drs": drs, "vpn": vpn, "efs": efs,
            "guardduty": guardduty,
            "lightsail": lightsail, "lightsail_buckets": lightsail_buckets, "savings_plans": sp, "cost": cost}

def _build_merged_report_data(group_name, accounts_info, accounts_data, period_days, start_date=None, end_date=None):
    """Merge data from multiple accounts into one report data dict."""
    _end = end_date or datetime.now(timezone.utc)
    _start = start_date or (_end - timedelta(days=period_days))

    all_ec2, all_ebs, all_rds, all_s3, all_drs, all_vpn, all_efs = [], [], [], [], [], [], []
    all_lightsail = []
    all_lightsail_buckets = []
    all_sp = {"summary": {}, "plans": []}
    all_cost_services = []
    total_cost = 0
    account_ids = []
    regions = set()

    # Per-account data for separate slides
    per_account = []

    for info in accounts_info:
        aid = info["account_id"]
        account_ids.append(f"{aid} ({info['customer_name']})")
        regions.add(info["region"])

        data = accounts_data.get(aid, {})
        label = info["customer_name"]

        # Store per-account data
        acct_ec2 = data.get("ec2", [])
        acct_ebs = data.get("ebs", [])
        acct_rds = data.get("rds", [])
        acct_s3 = data.get("s3", [])
        acct_drs = data.get("drs", [])
        acct_vpn = data.get("vpn", [])
        acct_efs = data.get("efs", [])
        acct_lightsail = data.get("lightsail", [])
        acct_lightsail_buckets = data.get("lightsail_buckets", [])
        acct_infra = build_infrastructure_summary(acct_ec2, acct_rds, acct_s3, acct_ebs)

        per_account.append({
            "label": label,
            "account_id": aid,
            "hld_image": info.get("hld_image"),
            "infrastructure_summary": acct_infra,
            "compute_utilization": acct_ec2,
            "ebs_utilization": acct_ebs,
            "rds_utilization": acct_rds,
            "s3_utilization": acct_s3,
            "drs_source_servers": acct_drs,
            "vpn_connections": acct_vpn,
            "efs_filesystems": acct_efs,
            "lightsail_instances": acct_lightsail,
            "lightsail_buckets": acct_lightsail_buckets,
            "guardduty": data.get("guardduty"),
        })

        # Tag each resource with account label for merged view
        for ec2 in acct_ec2:
            ec2["name"] = f"[{label}] {ec2.get('name', '-')}"
            all_ec2.append(ec2)
        for ebs in acct_ebs:
            ebs["instance_name"] = f"[{label}] {ebs.get('instance_name', '-')}"
            all_ebs.append(ebs)
        for rds in acct_rds:
            rds["db_identifier"] = f"[{label}] {rds.get('db_identifier', '-')}"
            all_rds.append(rds)
        for s3 in acct_s3:
            all_s3.append(s3)
        for drs in acct_drs:
            all_drs.append(drs)
        for vpn in acct_vpn:
            all_vpn.append(vpn)
        for efs in acct_efs:
            all_efs.append(efs)
        for lsi in acct_lightsail:
            all_lightsail.append(lsi)
        for lsb in acct_lightsail_buckets:
            all_lightsail_buckets.append(lsb)
        sp = data.get("savings_plans", {})
        if sp.get("plans"):
            all_sp["plans"].extend(sp["plans"])
            if sp.get("summary"):
                all_sp["summary"] = sp["summary"]
        cost = data.get("cost", {})
        total_cost += cost.get("total_cost", 0)
        all_cost_services.extend(cost.get("services", []))

    # Merge cost services
    merged_costs = defaultdict(float)
    for svc in all_cost_services:
        merged_costs[svc["service"]] += svc["cost"]
    sorted_costs = sorted(merged_costs.items(), key=lambda x: x[1], reverse=True)
    final_services = [{"service": s, "cost": round(c, 2),
        "percent": round(c / total_cost * 100, 1) if total_cost > 0 else 0}
        for s, c in sorted_costs if c > 0]

    infra = build_infrastructure_summary(all_ec2, all_rds, all_s3, all_ebs)

    return {
        "account_id": " | ".join(account_ids),
        "customer_name": group_name,
        "region": " | ".join(regions),
        "collection_date": _end.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "period": f"{_start.strftime('%Y-%m-%d')} to {_end.strftime('%Y-%m-%d')}",
        "infrastructure_summary": infra,
        "compute_utilization": all_ec2,
        "ebs_utilization": all_ebs,
        "s3_utilization": all_s3,
        "rds_utilization": all_rds,
        "savings_plans": all_sp,
        "cost_by_service": {"total_cost": round(total_cost, 2), "currency": "USD", "services": final_services},
        "drs_source_servers": all_drs,
        "vpn_connections": all_vpn,
        "efs_filesystems": all_efs,
        "lightsail_instances": all_lightsail,
        "lightsail_buckets": all_lightsail_buckets,
        "hld_image": None,
        "guardduty": per_account[0]["guardduty"] if len(per_account) == 1 else None,
        "per_account": per_account,
    }

# ============================================================
# Endpoints
# ============================================================

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/logs")
def get_logs():
    """Return recent warnings/errors."""
    return {"logs": list(log_buffer)}


@app.get("/", response_class=HTMLResponse)
def home():
    html_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()


@app.post("/preview")
async def preview_groups(files: List[UploadFile] = File(...)):
    """Upload multiple .docx, return grouping preview."""
    tmp_dir = tempfile.mkdtemp(prefix="preview_")
    try:
        files_data = []
        for f in files:
            if not f.filename.endswith(".docx"):
                continue
            fpath = os.path.join(tmp_dir, f.filename)
            with open(fpath, "wb") as out:
                out.write(await f.read())
            files_data.append((fpath, f.filename))

        parsed = _parse_files(files_data)
        groups = defaultdict(list)
        errors = []
        for p in parsed:
            if "error" in p:
                errors.append(p)
            else:
                groups[p["group"]].append({
                    "customer_name": p["customer_name"],
                    "account_id": p["account_id"],
                    "region": p["region"],
                    "source_file": p["source_file"],
                })

        return {
            "groups": {k: v for k, v in groups.items()},
            "total_reports": len(groups),
            "errors": errors,
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

@app.post("/generate")
async def generate_reports(files: List[UploadFile] = File(...), period_days: int = 30,
                           start_date: str = None, end_date: str = None):
    """Upload multiple .docx, generate reports. Optional: start_date & end_date (YYYY-MM-DD)."""
    role_name = os.getenv("DEFAULT_ROLE_NAME", "")
    if not role_name:
        raise HTTPException(500, "DEFAULT_ROLE_NAME belum di-set")

    # Parse dates
    _end = None; _start = None
    if start_date and end_date:
        try:
            _start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            _end = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            period_days = (_end - _start).days
        except ValueError:
            raise HTTPException(400, "Format tanggal harus YYYY-MM-DD")
    else:
        _end = datetime.now(timezone.utc)
        _start = _end - timedelta(days=period_days)

    tmp_dir = tempfile.mkdtemp(prefix="gen_")
    try:
        # Save files
        files_data = []
        for f in files:
            if not f.filename.endswith(".docx"): continue
            fpath = os.path.join(tmp_dir, f.filename)
            with open(fpath, "wb") as out: out.write(await f.read())
            files_data.append((fpath, f.filename))

        if not files_data:
            raise HTTPException(400, "No .docx files uploaded")

        # Parse & group
        parsed = [p for p in _parse_files(files_data) if "error" not in p]
        groups = defaultdict(list)
        for p in parsed: groups[p["group"]].append(p)

        # Single file shortcut
        if len(parsed) == 1:
            p = parsed[0]
            data = _collect_for_account(p["account_id"], p["region"], role_name, period_days, tmp_dir, start_date=_start, end_date=_end)
            infra = build_infrastructure_summary(data["ec2"], data["rds"], data["s3"], data["ebs"])
            report_data = {
                "account_id": p["account_id"], "customer_name": p["customer_name"],
                "region": p["region"],
                "collection_date": _end.strftime("%Y-%m-%d %H:%M:%S UTC"),
                "period": f"{_start.strftime('%Y-%m-%d')} to {_end.strftime('%Y-%m-%d')}",
                "infrastructure_summary": infra, "compute_utilization": data["ec2"],
                "ebs_utilization": data["ebs"], "s3_utilization": data["s3"],
                "rds_utilization": data["rds"], "savings_plans": data["savings_plans"],
                "cost_by_service": data["cost"], "drs_source_servers": data["drs"],
                "vpn_connections": data["vpn"], "efs_filesystems": data["efs"],
                "lightsail_instances": data["lightsail"],
                "lightsail_buckets": data["lightsail_buckets"],
                "guardduty": data["guardduty"],
                "hld_image": p.get("hld_image"),
            }
            out_dir = os.path.join(tmp_dir, "output")
            path = generate_report(report_data, output_dir=out_dir)
            slug = p["customer_name"].lower().replace(" ", "-")
            fname = f"{p['account_id']}_{slug}_report.pptx"
            return FileResponse(path, media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                headers={"Content-Disposition": f'attachment; filename="{fname}"'})

        # Multiple files: collect per account, merge per group, generate reports
        accounts_data = {}
        for p in parsed:
            aid = p["account_id"]
            if aid not in accounts_data:
                try:
                    accounts_data[aid] = _collect_for_account(
                        aid, p["region"], role_name, period_days, tmp_dir, start_date=_start, end_date=_end)
                except Exception as e:
                    logger.error(f"Gagal collect {aid}: {e}")

        # Generate per group
        report_paths = []
        for grp_name, grp_infos in groups.items():
            report_data = _build_merged_report_data(
                grp_name, grp_infos, accounts_data, period_days, start_date=_start, end_date=_end)
            out_dir = os.path.join(tmp_dir, f"output_{grp_name}")
            path = generate_report(report_data, output_dir=out_dir)
            report_paths.append((grp_name, path))

        # Single group → return file directly
        if len(report_paths) == 1:
            grp, path = report_paths[0]
            fname = os.path.basename(path)
            return FileResponse(path, media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                headers={"Content-Disposition": f'attachment; filename="{fname}"'})

        # Multiple groups → return zip
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for grp, path in report_paths:
                zf.write(path, os.path.basename(path))
        zip_buf.seek(0)
        return StreamingResponse(zip_buf, media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="reports.zip"'})

    except HTTPException: raise
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        raise HTTPException(500, str(e))


# Backward compatible single-file endpoint
@app.post("/generate-report")
async def generate_single(file: UploadFile = File(...), period_days: int = 30):
    return await generate_reports(files=[file], period_days=period_days)


@app.post("/generate-direct")
async def generate_direct(
    account_id: str,
    customer_name: str,
    region: str = "ap-southeast-3",
    period_days: int = 30,
    start_date: str = None,
    end_date: str = None,
):
    """
    Generate report langsung tanpa upload .docx.
    Cukup pass account_id, customer_name, region sebagai query params.

    Contoh:
      POST /generate-direct?account_id=083264029433&customer_name=Payquest&region=ap-southeast-3
    """
    role_name = os.getenv("DEFAULT_ROLE_NAME", "")
    if not role_name:
        raise HTTPException(500, "DEFAULT_ROLE_NAME belum di-set")

    # Parse dates
    if start_date and end_date:
        try:
            _start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            _end = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            period_days = (_end - _start).days
        except ValueError:
            raise HTTPException(400, "Format tanggal harus YYYY-MM-DD")
    else:
        _end = datetime.now(timezone.utc)
        _start = _end - timedelta(days=period_days)

    tmp_dir = tempfile.mkdtemp(prefix="direct_")
    try:
        data = _collect_for_account(account_id, region, role_name, period_days, tmp_dir,
                                    start_date=_start, end_date=_end)
        infra = build_infrastructure_summary(data["ec2"], data["rds"], data["s3"], data["ebs"])

        report_data = {
            "account_id": account_id,
            "customer_name": customer_name,
            "region": region,
            "collection_date": _end.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "period": f"{_start.strftime('%Y-%m-%d')} to {_end.strftime('%Y-%m-%d')}",
            "infrastructure_summary": infra,
            "compute_utilization": data["ec2"],
            "ebs_utilization": data["ebs"],
            "s3_utilization": data["s3"],
            "rds_utilization": data["rds"],
            "savings_plans": data["savings_plans"],
            "cost_by_service": data["cost"],
            "drs_source_servers": data["drs"],
            "vpn_connections": data["vpn"],
            "efs_filesystems": data["efs"],
            "lightsail_instances": data["lightsail"],
            "lightsail_buckets": data["lightsail_buckets"],
            "guardduty": data["guardduty"],
            "hld_image": None,
        }

        out_dir = os.path.join(tmp_dir, "output")
        path = generate_report(report_data, output_dir=out_dir)

        # Read file into memory first, then cleanup tmp_dir safely
        with open(path, "rb") as f:
            file_bytes = f.read()
        shutil.rmtree(tmp_dir, ignore_errors=True)

        slug = customer_name.lower().replace(" ", "-")
        import re as _re
        safe_slug = _re.sub(r'[<>:"/\\|?*]', '', slug)
        fname = f"{account_id}_{safe_slug}_report.pptx"
        return StreamingResponse(
            io.BytesIO(file_bytes),
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generate-direct: {e}", exc_info=True)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(500, str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
