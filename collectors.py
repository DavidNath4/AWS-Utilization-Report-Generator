"""collectors.py - Collect data dari AWS API + CloudWatch metrics"""
import os, json, logging
from datetime import datetime, timedelta, timezone
logger = logging.getLogger(__name__)

# Nama metrik CloudWatch Agent default untuk Windows
WIN_MEM = "Memory % Committed Bytes In Use"
WIN_DISK_FREE = "LogicalDisk % Free Space"

def get_metric(cw, ns, mn, dims, pd, stat="Maximum", start_date=None, end_date=None):
    try:
        et = end_date or datetime.now(timezone.utc)
        st = start_date or (et - timedelta(days=pd))
        days = max(int((et - st).total_seconds() / 86400), 1)
        r = cw.get_metric_statistics(Namespace=ns, MetricName=mn, Dimensions=dims,
            StartTime=st, EndTime=et, Period=days*86400, Statistics=[stat])
        dp = r.get("Datapoints", [])
        if not dp: return "-"
        return round(max(d[stat] for d in dp), 2)
    except Exception as e:
        logger.warning(f"Gagal query {ns}/{mn}: {e}"); return "-"

def format_bytes(bv):
    if bv is None or bv == "-": return "-"
    gb = bv / (1024**3)
    if gb >= 1024: return f"{round(gb/1024, 2)} TB"
    elif gb >= 1: return f"{round(gb, 2)} GB"
    else: return f"{round(bv/(1024**2), 2)} MB"

def generate_chart(cw, title, mc, pd, op, start_date=None, end_date=None):
    et = end_date or datetime.now(timezone.utc)
    st = start_date or (et - timedelta(days=pd))
    w = {"metrics": mc, "view": "timeSeries", "stacked": False, "region": cw.meta.region_name,
         "title": title, "period": 3600, "stat": "Maximum",
         "start": st.strftime("%Y-%m-%dT%H:%M:%SZ"), "end": et.strftime("%Y-%m-%dT%H:%M:%SZ"),
         "width": 800, "height": 300}
    try:
        r = cw.get_metric_widget_image(MetricWidget=json.dumps(w))
        img = r.get("MetricWidgetImage")
        if img:
            os.makedirs(os.path.dirname(op), exist_ok=True)
            with open(op, "wb") as f: f.write(img)
            return op
    except Exception as e: logger.warning(f"Gagal chart '{title}': {e}")
    return None

def collect_ec2(session, pd, cd, start_date=None, end_date=None):
    logger.info("Collecting EC2...")
    ec2 = session.client("ec2"); cw = session.client("cloudwatch")
    try:
        instances = []
        for page in ec2.get_paginator("describe_instances").paginate():
            for res in page["Reservations"]: instances.extend(res["Instances"])
        logger.info(f"Found {len(instances)} EC2")
    except Exception as e: logger.error(f"Gagal list EC2: {e}"); return []
    results = []
    for inst in instances:
        iid = inst["InstanceId"]; tags = {t["Key"]: t["Value"] for t in inst.get("Tags", [])}
        nm = tags.get("Name", "-"); os_type = "Windows" if inst.get("Platform","").lower() == "windows" else "Linux"
        dims = [{"Name": "InstanceId", "Value": iid}]
        cpu = get_metric(cw, "AWS/EC2", "CPUUtilization", dims, pd, start_date=start_date, end_date=end_date)
        avg_cpu = get_metric(cw, "AWS/EC2", "CPUUtilization", dims, pd, stat="Average", start_date=start_date, end_date=end_date)
        if os_type == "Windows":
            # CWAgent Windows: nama metrik & dimension berbeda dengan Linux
            mem_dims = [{"Name": "InstanceId", "Value": iid}, {"Name": "objectname", "Value": "Memory"}]
            disk_dims = [{"Name": "InstanceId", "Value": iid}, {"Name": "objectname", "Value": "LogicalDisk"},
                         {"Name": "instance", "Value": "C:"}]
            mem = get_metric(cw, "CWAgent", WIN_MEM, mem_dims, pd, start_date=start_date, end_date=end_date)
            avg_mem = get_metric(cw, "CWAgent", WIN_MEM, mem_dims, pd, stat="Average", start_date=start_date, end_date=end_date)
            free = get_metric(cw, "CWAgent", WIN_DISK_FREE, disk_dims, pd, stat="Average", start_date=start_date, end_date=end_date)
            avg_disk = round(100 - free, 2) if free != "-" else "-"  # metrik Windows = % free, report = % used
        else:
            mem = get_metric(cw, "CWAgent", "mem_used_percent", dims, pd, start_date=start_date, end_date=end_date)
            avg_mem = get_metric(cw, "CWAgent", "mem_used_percent", dims, pd, stat="Average", start_date=start_date, end_date=end_date)
            avg_disk = get_metric(cw, "CWAgent", "disk_used_percent", dims, pd, stat="Average", start_date=start_date, end_date=end_date)
        net_in = get_metric(cw, "AWS/EC2", "NetworkIn", dims, pd, stat="Average", start_date=start_date, end_date=end_date)
        net_out = get_metric(cw, "AWS/EC2", "NetworkOut", dims, pd, stat="Average", start_date=start_date, end_date=end_date)
        vol_read = get_metric(cw, "AWS/EC2", "EBSReadBytes", dims, pd, stat="Average", start_date=start_date, end_date=end_date)
        vol_write = get_metric(cw, "AWS/EC2", "EBSWriteBytes", dims, pd, stat="Average", start_date=start_date, end_date=end_date)
        # Format network/volume bytes
        net_in_s = format_bytes(net_in) if net_in != "-" else "-"
        net_out_s = format_bytes(net_out) if net_out != "-" else "-"
        vol_read_s = format_bytes(vol_read) if vol_read != "-" else "-"
        vol_write_s = format_bytes(vol_write) if vol_write != "-" else "-"
        cc = generate_chart(cw, f"CPU-{nm}({iid})", [["AWS/EC2","CPUUtilization","InstanceId",iid]], pd, os.path.join(cd, f"ec2_{iid}_cpu.png"), start_date=start_date, end_date=end_date)
        if os_type == "Windows":
            mem_metrics = [["CWAgent", WIN_MEM, "InstanceId", iid, "objectname", "Memory"]]
            # Disk used % = 100 - free % (metric math), hanya C:
            disk_metrics = [[{"expression": "100-m1", "label": "Disk used % (C:)", "id": "e1"}],
                            ["CWAgent", WIN_DISK_FREE, "InstanceId", iid, "instance", "C:", "objectname", "LogicalDisk",
                             {"id": "m1", "visible": False}]]
        else:
            mem_metrics = [["CWAgent","mem_used_percent","InstanceId",iid]]
            disk_metrics = [["CWAgent","disk_used_percent","InstanceId",iid]]
        mc = generate_chart(cw, f"Mem-{nm}({iid})", mem_metrics, pd, os.path.join(cd, f"ec2_{iid}_mem.png"), start_date=start_date, end_date=end_date)
        dc = generate_chart(cw, f"Disk-{nm}({iid})", disk_metrics, pd, os.path.join(cd, f"ec2_{iid}_disk.png"), start_date=start_date, end_date=end_date)
        vwc = generate_chart(cw, f"VolumeWriteBytes-{nm}({iid})", [["AWS/EC2","EBSWriteBytes","InstanceId",iid]], pd, os.path.join(cd, f"ec2_{iid}_vol_write.png"), start_date=start_date, end_date=end_date)
        vrc = generate_chart(cw, f"VolumeReadBytes-{nm}({iid})", [["AWS/EC2","EBSReadBytes","InstanceId",iid]], pd, os.path.join(cd, f"ec2_{iid}_vol_read.png"), start_date=start_date, end_date=end_date)
        noc = generate_chart(cw, f"NetworkOut-{nm}({iid})", [["AWS/EC2","NetworkOut","InstanceId",iid]], pd, os.path.join(cd, f"ec2_{iid}_net_out.png"), start_date=start_date, end_date=end_date)
        nic = generate_chart(cw, f"NetworkIn-{nm}({iid})", [["AWS/EC2","NetworkIn","InstanceId",iid]], pd, os.path.join(cd, f"ec2_{iid}_net_in.png"), start_date=start_date, end_date=end_date)
        results.append({"instance_id": iid, "instance_type": inst.get("InstanceType","-"), "name": nm,
            "state": inst["State"]["Name"], "os": os_type, "private_ip": inst.get("PrivateIpAddress","-"),
            "max_cpu_percent": cpu, "avg_cpu_percent": avg_cpu, "max_mem_percent": mem, "avg_mem_percent": avg_mem,
            "avg_disk_percent": avg_disk, "net_in_avg": net_in_s, "net_out_avg": net_out_s,
            "vol_read_avg": vol_read_s, "vol_write_avg": vol_write_s,
            "cpu_chart": cc, "mem_chart": mc, "disk_chart": dc,
            "vol_write_chart": vwc, "vol_read_chart": vrc,
            "net_out_chart": noc, "net_in_chart": nic, "remark": "-"})
    return results

def collect_ebs(session, pd):
    logger.info("Collecting EBS...")
    ec2 = session.client("ec2")
    try:
        volumes = []
        for page in ec2.get_paginator("describe_volumes").paginate(): volumes.extend(page["Volumes"])
        logger.info(f"Found {len(volumes)} EBS")
    except Exception as e: logger.error(f"Gagal list EBS: {e}"); return []
    names = {}
    try:
        for page in ec2.get_paginator("describe_instances").paginate():
            for res in page["Reservations"]:
                for inst in res["Instances"]:
                    tags = {t["Key"]: t["Value"] for t in inst.get("Tags", [])}
                    names[inst["InstanceId"]] = tags.get("Name", "-")
    except: pass
    results = []
    for vol in volumes:
        att = vol.get("Attachments", []); iid = att[0]["InstanceId"] if att else "-"
        results.append({"volume_id": vol["VolumeId"], "instance_id": iid,
            "instance_name": names.get(iid, "-") if iid != "-" else "-",
            "storage_type": vol.get("VolumeType","-"), "size_gb": vol.get("Size",0),
            "iops": vol.get("Iops","-"), "state": vol.get("State","-"), "free_space_percent": "-", "remark": "-"})
    return results

def collect_rds(session, pd, cd, start_date=None, end_date=None):
    logger.info("Collecting RDS...")
    rds = session.client("rds"); cw = session.client("cloudwatch")
    try:
        instances = []
        for page in rds.get_paginator("describe_db_instances").paginate(): instances.extend(page["DBInstances"])
        logger.info(f"Found {len(instances)} RDS")
    except Exception as e: logger.error(f"Gagal list RDS: {e}"); return []
    results = []
    for db in instances:
        did = db["DBInstanceIdentifier"]; dims = [{"Name": "DBInstanceIdentifier", "Value": did}]
        cpu = get_metric(cw, "AWS/RDS", "CPUUtilization", dims, pd, start_date=start_date, end_date=end_date)
        avg_cpu = get_metric(cw, "AWS/RDS", "CPUUtilization", dims, pd, stat="Average", start_date=start_date, end_date=end_date)
        fm = get_metric(cw, "AWS/RDS", "FreeableMemory", dims, pd, stat="Average", start_date=start_date, end_date=end_date)
        fs = get_metric(cw, "AWS/RDS", "FreeStorageSpace", dims, pd, stat="Average", start_date=start_date, end_date=end_date)
        cc = generate_chart(cw, f"RDS CPU-{did}", [["AWS/RDS","CPUUtilization","DBInstanceIdentifier",did]], pd, os.path.join(cd, f"rds_{did}_cpu.png"), start_date=start_date, end_date=end_date)
        mc = generate_chart(cw, f"RDS Mem-{did}", [["AWS/RDS","FreeableMemory","DBInstanceIdentifier",did]], pd, os.path.join(cd, f"rds_{did}_memory.png"), start_date=start_date, end_date=end_date)
        sc = generate_chart(cw, f"RDS Sto-{did}", [["AWS/RDS","FreeStorageSpace","DBInstanceIdentifier",did]], pd, os.path.join(cd, f"rds_{did}_storage.png"), start_date=start_date, end_date=end_date)
        results.append({"db_identifier": did, "instance_type": db.get("DBInstanceClass","-"),
            "engine": db.get("Engine","-"), "engine_version": db.get("EngineVersion","-"),
            "status": db.get("DBInstanceStatus","-"), "allocated_storage_gb": db.get("AllocatedStorage",0),
            "max_cpu_percent": cpu, "avg_cpu_percent": avg_cpu,
            "freeable_memory": format_bytes(fm) if fm!="-" else "-",
            "free_storage": format_bytes(fs) if fs!="-" else "-",
            "cpu_chart": cc, "mem_chart": mc, "storage_chart": sc, "remark": "-"})
    return results

def collect_s3(session, pd, start_date=None, end_date=None):
    logger.info("Collecting S3...")
    s3 = session.client("s3")
    try:
        buckets = s3.list_buckets().get("Buckets", [])
        logger.info(f"Found {len(buckets)} S3")
    except Exception as e: logger.error(f"Gagal list S3: {e}"); return []
    cw_clients = {}; results = []
    for b in buckets:
        bn = b["Name"]
        try: region = s3.get_bucket_location(Bucket=bn).get("LocationConstraint") or "us-east-1"
        except: region = "-"
        if region != "-":
            if region not in cw_clients: cw_clients[region] = session.client("cloudwatch", region_name=region)
            cw = cw_clients[region]
        else: cw = session.client("cloudwatch")
        dims = [{"Name":"BucketName","Value":bn},{"Name":"StorageType","Value":"StandardStorage"}]
        sb = get_metric(cw, "AWS/S3", "BucketSizeBytes", dims, pd, stat="Average", start_date=start_date, end_date=end_date)
        ts = format_bytes(sb) if sb!="-" else "-"
        od = [{"Name":"BucketName","Value":bn},{"Name":"StorageType","Value":"AllStorageTypes"}]
        oc = get_metric(cw, "AWS/S3", "NumberOfObjects", od, pd, stat="Average", start_date=start_date, end_date=end_date)
        if oc != "-": oc = int(oc)
        avs = format_bytes(sb/oc) if sb!="-" and oc!="-" and oc>0 else "-"
        results.append({"bucket_name": bn, "region": region, "total_size": ts,
            "total_bytes": sb if sb!="-" else 0, "object_count": oc, "avg_object_size": avs, "remark": "-"})
    return results

def collect_drs(session, pd=30, cd=None, start_date=None, end_date=None):
    logger.info("Collecting DRS...")
    try: drs = session.client("drs")
    except: return []
    try:
        servers = drs.describe_source_servers(filters={}).get("items", [])
        logger.info(f"Found {len(servers)} DRS")
    except Exception as e: logger.info(f"DRS not available: {e}"); return []
    cw = None
    try: cw = session.client("cloudwatch")
    except Exception: cw = None
    results = []
    for srv in servers:
        sp = srv.get("sourceProperties", {}); hostname = sp.get("identificationHints", {}).get("hostname", "-")
        os_info = sp.get("os", {}).get("fullString", "-"); sid = srv.get("sourceServerID", "-")
        disks = sp.get("disks", [])
        disk_str = "\n".join(f"{d.get('deviceName','?')}: {round(d.get('bytes',0)/(1024**3))} GiB" for d in disks) or "-"

        # Replication status
        dri = srv.get("dataReplicationInfo", {})
        repl_state = dri.get("dataReplicationState", "-")
        lag = dri.get("lagDuration", "-")
        # Health: healthy if continuous replication and no/low lag
        healthy = "Healthy" if repl_state in ("CONTINUOUS",) and (lag in ("-", "PT0S", None) or lag == "PT0S") else \
                  ("Lag" if repl_state == "CONTINUOUS" else repl_state)

        # CloudWatch charts (Backlog & LagDuration) per source server
        backlog_chart = lag_chart = None
        if cw and cd:
            safe = "".join(ch if ch.isalnum() else "_" for ch in sid)
            backlog_chart = generate_chart(cw, f"Backlog - {hostname}",
                [["AWS/DRS", "Backlog", "SourceServerID", sid]], pd,
                os.path.join(cd, f"drs_{safe}_backlog.png"), start_date=start_date, end_date=end_date)
            lag_chart = generate_chart(cw, f"LagDuration - {hostname}",
                [["AWS/DRS", "LagDuration", "SourceServerID", sid]], pd,
                os.path.join(cd, f"drs_{safe}_lag.png"), start_date=start_date, end_date=end_date)

        results.append({
            "source_server": f"{hostname} ({sid})",
            "os": os_info,
            "disk_size": disk_str,
            "repl_state": repl_state,
            "lag": lag,
            "health": healthy,
            "backlog_chart": backlog_chart,
            "lag_chart": lag_chart,
            "remark": "-",
        })
    return results

def collect_vpn(session):
    """Collect Site-to-Site VPN connections."""
    logger.info("Collecting VPN...")
    try: ec2 = session.client("ec2")
    except: return []
    try:
        vpns = ec2.describe_vpn_connections().get("VpnConnections", [])
        logger.info(f"Found {len(vpns)} VPN connections")
    except Exception as e: logger.info(f"VPN not available: {e}"); return []
    results = []
    for v in vpns:
        tags = {t["Key"]: t["Value"] for t in v.get("Tags", [])}
        results.append({
            "name": tags.get("Name", "-"),
            "vpn_id": v.get("VpnConnectionId", "-"),
            "state": v.get("State", "-"),
            "remark": "-",
        })
    return results

def collect_efs(session):
    """Collect EFS file systems."""
    logger.info("Collecting EFS...")
    try: efs = session.client("efs")
    except: return []
    try:
        filesystems = efs.describe_file_systems().get("FileSystems", [])
        logger.info(f"Found {len(filesystems)} EFS file systems")
    except Exception as e: logger.info(f"EFS not available: {e}"); return []
    results = []
    for fs in filesystems:
        tags = {t["Key"]: t["Value"] for t in fs.get("Tags", [])}
        size_bytes = fs.get("SizeInBytes", {}).get("Value", 0)
        results.append({
            "name": tags.get("Name", fs.get("Name", "-")),
            "file_system_id": fs.get("FileSystemId", "-"),
            "encrypted": "Encrypted" if fs.get("Encrypted") else "Not Encrypted",
            "total_size": format_bytes(size_bytes) if size_bytes else "-",
            "state": fs.get("LifeCycleState", "-"),
        })
    return results


def _gd_severity(score):
    """Map GuardDuty numeric severity to label: High (>=7), Medium (4-<7), Low (<4)."""
    try: score = float(score)
    except (TypeError, ValueError): score = 0.0
    if score >= 7: return "High"
    if score >= 4: return "Medium"
    return "Low"


def collect_guardduty(session, pd=30, start_date=None, end_date=None, max_findings=500):
    """Collect GuardDuty findings for the configured region(s) of the session only.
    Never raises. Returns {"regions": [{region,status,message}], "summary": {...}, "findings": [...]}.
    status: ok | not_enabled | access_denied | error."""
    logger.info("Collecting GuardDuty...")
    from botocore.exceptions import ClientError
    _et = end_date or datetime.now(timezone.utc)
    _st = start_date or (_et - timedelta(days=pd))
    ms_start, ms_end = int(_st.timestamp() * 1000), int(_et.timestamp() * 1000)
    denied_codes = ("AccessDeniedException", "AccessDenied", "UnauthorizedOperation")
    regions = [session.region_name]
    result = {"regions": [], "summary": {"High": 0, "Medium": 0, "Low": 0, "total": 0}, "findings": []}
    for r in regions:
        try:
            gd = session.client("guardduty", region_name=r)
            detectors = gd.list_detectors().get("DetectorIds", [])
            if not detectors:
                result["regions"].append({"region": r, "status": "not_enabled", "message": "GuardDuty not enabled"})
                continue
            det = detectors[0]
            criteria = {"Criterion": {"service.archived": {"Eq": ["false"]},
                                      "updatedAt": {"Gte": ms_start, "Lte": ms_end}}}
            ids = []
            for page in gd.get_paginator("list_findings").paginate(
                    DetectorId=det, FindingCriteria=criteria,
                    SortCriteria={"AttributeName": "updatedAt", "OrderBy": "DESC"}):
                ids.extend(page.get("FindingIds", []))
                if len(ids) >= max_findings: break
            ids = ids[:max_findings]
            for i in range(0, len(ids), 50):
                for f in gd.get_findings(DetectorId=det, FindingIds=ids[i:i+50]).get("Findings", []):
                    score = f.get("Severity", 0)
                    svc = f.get("Service", {}) or {}
                    seen = f.get("UpdatedAt") or svc.get("EventLastSeen") or "-"
                    if isinstance(seen, datetime): seen = seen.strftime("%Y-%m-%d %H:%M")
                    else: seen = str(seen).replace("T", " ")[:16]
                    result["findings"].append({
                        "severity": _gd_severity(score), "severity_score": float(score or 0),
                        "type": f.get("Type", "-"), "title": f.get("Title", "-"),
                        "resource_type": (f.get("Resource", {}) or {}).get("ResourceType", "-"),
                        "region": f.get("Region", r), "count": svc.get("Count", "-"),
                        "last_seen": seen,
                    })
            result["regions"].append({"region": r, "status": "ok", "message": ""})
            logger.info(f"Found {len(ids)} GuardDuty findings in {r}")
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in denied_codes:
                logger.warning(f"GuardDuty access denied in {r}: {e}")
                result["regions"].append({"region": r, "status": "access_denied",
                    "message": "Access denied to GuardDuty (check guardduty:* permissions)"})
            else:
                logger.warning(f"GuardDuty error in {r}: {e}")
                result["regions"].append({"region": r, "status": "error",
                    "message": "Unable to retrieve GuardDuty findings"})
        except Exception as e:
            logger.warning(f"GuardDuty error in {r}: {e}")
            result["regions"].append({"region": r, "status": "error",
                "message": "Unable to retrieve GuardDuty findings"})
    result["findings"].sort(key=lambda x: (x["severity_score"], x["last_seen"]), reverse=True)
    for f in result["findings"]:
        result["summary"][f["severity"]] += 1
    result["summary"]["total"] = len(result["findings"])
    return result


def _ls_chart(ls, instance_name, metric_name, title, output_path, pd, unit=None, start_date=None, end_date=None):
    """Fetch Lightsail metric time-series and plot with matplotlib. Returns PNG path or None."""
    try:
        et = end_date or datetime.now(timezone.utc)
        st = start_date or (et - timedelta(days=pd))
        total = int((et - st).total_seconds())
        # Aim for ~hourly granularity but respect Lightsail's max 60480 datapoints; cap period
        period = min(max((total // 300) // 60 * 60, 3600), 21600)
        if period < 60: period = 3600
        u = unit or ("Percent" if metric_name == "CPUUtilization" else "Bytes")
        r = ls.get_instance_metric_data(
            instanceName=instance_name, metricName=metric_name,
            period=period, startTime=st, endTime=et, unit=u, statistics=["Average"])
        pts = r.get("metricData", [])
        if not pts:
            logger.info(f"Lightsail chart {metric_name} for {instance_name}: no datapoints")
            return None
        # Log actual keys once for debugging
        logger.debug(f"Lightsail {metric_name} datapoint keys: {list(pts[0].keys())}")

        # Extract average values (avg is confirmed working). Timestamp key may vary.
        def _ts(p):
            return p.get("timestamp") or p.get("timeStamp") or p.get("time")
        def _avg(p):
            return p.get("average", p.get("Average"))

        pairs = [(_ts(p), _avg(p)) for p in pts if _avg(p) is not None]
        if not pairs:
            logger.info(f"Lightsail chart {metric_name} for {instance_name}: no average values")
            return None
        # Sort by timestamp if available
        if all(t is not None for t, _ in pairs):
            pairs.sort(key=lambda x: x[0])
            xs = [t for t, _ in pairs]
        else:
            xs = list(range(len(pairs)))  # fallback: index-based x-axis
        ys = [v for _, v in pairs]

        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        fig, ax = plt.subplots(figsize=(4.5, 1.7))
        ax.plot(xs, ys, color="#2E75B6", linewidth=1.2)
        ax.fill_between(xs, ys, color="#2E75B6", alpha=0.15)
        ax.set_title(title, fontsize=8, fontweight="bold")
        ax.tick_params(labelsize=6)
        if xs and not isinstance(xs[0], int):
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
        ax.grid(True, alpha=0.3, linewidth=0.5)
        plt.tight_layout()
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        plt.savefig(output_path, dpi=120, facecolor="white"); plt.close()
        return output_path
    except Exception as e:
        logger.warning(f"Gagal chart Lightsail {metric_name} for {instance_name}: {e}")
        return None


def collect_lightsail(session, pd, cd=None, start_date=None, end_date=None):
    """Collect Lightsail instances across all Lightsail regions (optional).
    Returns [] if not available/empty. cd = charts output dir."""
    logger.info("Collecting Lightsail...")
    try: ls_default = session.client("lightsail")
    except Exception as e:
        logger.info(f"Lightsail not available: {e}"); return []

    # Determine which regions to scan
    regions = []
    try:
        rr = ls_default.get_regions()
        regions = [r["name"] for r in rr.get("regions", [])]
    except Exception as e:
        # RegionSetupInProgressException etc. are transient/expected — fall back to session region quietly
        logger.info(f"Lightsail get_regions unavailable, using session region only: {e}")
    if not regions:
        # Fallback to the session's region
        regions = [ls_default.meta.region_name]

    results = []
    total_found = 0
    for region in regions:
        try:
            ls = session.client("lightsail", region_name=region)
            instances = []
            token = None
            while True:
                kwargs = {"pageToken": token} if token else {}
                resp = ls.get_instances(**kwargs)
                instances.extend(resp.get("instances", []))
                token = resp.get("nextPageToken")
                if not token: break
        except Exception as e:
            # Opt-in regions not enabled for the account throw UnrecognizedClientException — expected, skip quietly
            logger.debug(f"Lightsail region {region} skipped: {e}")
            continue

        if not instances:
            continue
        total_found += len(instances)
        logger.info(f"Found {len(instances)} Lightsail instances in {region}")

        for inst in instances:
            name = inst.get("name", "-")
            max_cpu = _ls_metric(ls, name, "CPUUtilization", "Maximum", pd, start_date, end_date)
            avg_cpu = _ls_metric(ls, name, "CPUUtilization", "Average", pd, start_date, end_date)
            net_in = _ls_metric(ls, name, "NetworkIn", "Sum", pd, start_date, end_date)
            net_out = _ls_metric(ls, name, "NetworkOut", "Sum", pd, start_date, end_date)
            hw = inst.get("hardware", {})
            # Utilization charts (like EC2)
            cpu_chart = mem_chart = net_chart = None
            if cd:
                safe = "".join(ch if ch.isalnum() else "_" for ch in name)
                cpu_chart = _ls_chart(ls, name, "CPUUtilization", f"CPU - {name}",
                    os.path.join(cd, f"ls_{safe}_cpu.png"), pd, start_date=start_date, end_date=end_date)
                mem_chart = _ls_chart(ls, name, "BurstCapacityPercentage", f"Burst Capacity - {name}",
                    os.path.join(cd, f"ls_{safe}_burst.png"), pd, unit="Percent", start_date=start_date, end_date=end_date)
                net_chart = _ls_chart(ls, name, "NetworkOut", f"Network Out - {name}",
                    os.path.join(cd, f"ls_{safe}_netout.png"), pd, unit="Bytes", start_date=start_date, end_date=end_date)
                logger.info(f"Lightsail charts for {name}: cpu={'OK' if cpu_chart else 'None'}, "
                            f"burst={'OK' if mem_chart else 'None'}, net={'OK' if net_chart else 'None'}")
            else:
                logger.warning("Lightsail charts skipped: no charts dir (cd) provided")
            results.append({
                "name": name,
                "region": region,
                "blueprint": inst.get("blueprintName", "-"),
                "bundle": inst.get("bundleId", "-"),
                "cpu_count": hw.get("cpuCount", "-"),
                "ram_gb": round(hw.get("ramSizeInGb", 0), 1) if hw.get("ramSizeInGb") else "-",
                "state": inst.get("state", {}).get("name", "-"),
                "public_ip": inst.get("publicIpAddress", "-"),
                "max_cpu_percent": f"{max_cpu}%" if max_cpu != "-" else "-",
                "avg_cpu_percent": f"{avg_cpu}%" if avg_cpu != "-" else "-",
                "net_in": format_bytes(net_in) if net_in != "-" else "-",
                "net_out": format_bytes(net_out) if net_out != "-" else "-",
                "cpu_chart": cpu_chart,
                "burst_chart": mem_chart,
                "net_chart": net_chart,
            })

    logger.info(f"Total Lightsail instances found: {total_found}")
    return results


def _ls_metric(ls, instance_name, metric_name, stat, pd, start_date=None, end_date=None):
    """Query Lightsail instance metric.
    Note: request statistics use CamelCase (Maximum/Average/Sum) but the response
    datapoint keys are lowercase (maximum/average/sum)."""
    try:
        et = end_date or datetime.now(timezone.utc)
        st = start_date or (et - timedelta(days=pd))
        # Lightsail period must be a multiple of 60; cap at 6h to stay within point limits
        total = int((et - st).total_seconds())
        period = min(max((total // 60) * 60, 3600), 21600)
        r = ls.get_instance_metric_data(
            instanceName=instance_name, metricName=metric_name,
            period=period, startTime=st, endTime=et,
            unit="Percent" if metric_name == "CPUUtilization" else "Bytes",
            statistics=[stat])
        pts = r.get("metricData", [])
        if not pts: return "-"
        key = stat[0].lower() + stat[1:]  # Maximum -> maximum, Average -> average, Sum -> sum
        vals = [p[key] for p in pts if key in p]
        if not vals: return "-"
        return round(max(vals), 2)
    except Exception as e:
        logger.warning(f"Gagal query Lightsail {metric_name}: {e}"); return "-"


def collect_lightsail_buckets(session, pd, start_date=None, end_date=None):
    """Collect Lightsail object storage buckets across all Lightsail regions (optional).
    Returns [] if not available/empty."""
    logger.info("Collecting Lightsail buckets...")
    try: ls_default = session.client("lightsail")
    except Exception as e:
        logger.info(f"Lightsail not available: {e}"); return []

    regions = []
    try:
        rr = ls_default.get_regions()
        regions = [r["name"] for r in rr.get("regions", [])]
    except Exception as e:
        # RegionSetupInProgressException etc. are transient/expected — fall back to session region quietly
        logger.info(f"Lightsail get_regions unavailable, using session region only: {e}")
    if not regions:
        regions = [ls_default.meta.region_name]

    results = []
    total_found = 0
    for region in regions:
        try:
            ls = session.client("lightsail", region_name=region)
            buckets = []
            token = None
            while True:
                kwargs = {"pageToken": token} if token else {}
                resp = ls.get_buckets(**kwargs)
                buckets.extend(resp.get("buckets", []))
                token = resp.get("nextPageToken")
                if not token: break
        except Exception as e:
            logger.debug(f"Lightsail buckets region {region} skipped: {e}")
            continue

        if not buckets:
            continue

        # Map bundleId -> storage size (GB)
        bundle_size = {}
        try:
            bb = ls.get_bucket_bundles()
            for b in bb.get("bundles", []):
                bundle_size[b.get("bundleId")] = b.get("storagePerMonthInGb", 0)
        except Exception as e:
            logger.debug(f"Gagal get bucket bundles {region}: {e}")

        total_found += len(buckets)
        logger.info(f"Found {len(buckets)} Lightsail buckets in {region}")

        for bk in buckets:
            name = bk.get("name", "-")
            size_bytes = _ls_bucket_metric(ls, name, "BucketSizeBytes", pd, start_date, end_date)
            obj_count = _ls_bucket_metric(ls, name, "NumberOfObjects", pd, start_date, end_date)
            plan_gb = bundle_size.get(bk.get("bundleId"), 0)
            stored_gb = round(size_bytes / (1024**3), 2) if size_bytes != "-" else "-"
            quota_pct = "-"
            if stored_gb != "-" and plan_gb:
                quota_pct = f"{round(stored_gb / plan_gb * 100, 2)}%"
            # Access permission
            access = bk.get("accessRules", {})
            get_obj = access.get("getObject", "-")
            access_label = "All objects are private" if get_obj == "private" else f"getObject: {get_obj}"
            results.append({
                "name": name,
                "region": region,
                "url": bk.get("url", "-"),
                "plan_size": f"{plan_gb} GB" if plan_gb else "-",
                "object_count": f"{int(obj_count):,}" if obj_count != "-" else "-",
                "stored_data": f"{stored_gb} GB" if stored_gb != "-" else "-",
                "quota_used": quota_pct,
                "access": access_label,
            })

    logger.info(f"Total Lightsail buckets found: {total_found}")
    return results


def _ls_bucket_metric(ls, bucket_name, metric_name, pd, start_date=None, end_date=None):
    """Query Lightsail bucket metric (BucketSizeBytes / NumberOfObjects)."""
    try:
        et = end_date or datetime.now(timezone.utc)
        st = start_date or (et - timedelta(days=pd))
        total = int((et - st).total_seconds())
        period = min(max((total // 60) * 60, 3600), 21600)
        unit = "Bytes" if metric_name == "BucketSizeBytes" else "Count"
        r = ls.get_bucket_metric_data(
            bucketName=bucket_name, metricName=metric_name,
            period=period, startTime=st, endTime=et,
            unit=unit, statistics=["Average"])
        pts = r.get("metricData", [])
        if not pts: return "-"
        vals = [p["average"] for p in pts if "average" in p]
        if not vals: return "-"
        return round(vals[-1], 2)  # latest datapoint
    except Exception as e:
        logger.warning(f"Gagal query Lightsail bucket {metric_name}: {e}"); return "-"


def collect_savings_plans(session, pd, start_date=None, end_date=None):
    logger.info("Collecting Savings Plans...")
    try: spc = session.client("savingsplans")
    except: return {"summary": {}, "plans": [], "inventory": [], "coverage_breakdown": []}
    try: plans = spc.describe_savings_plans().get("savingsPlans", [])
    except: return {"summary": {}, "plans": [], "inventory": [], "coverage_breakdown": []}
    if not plans: return {"summary": {}, "plans": [], "inventory": [], "coverage_breakdown": []}

    # Inventory (active plans)
    inventory = []
    for p in plans:
        if p.get("state", "").lower() != "active": continue
        s, e = p.get("start", "-"), p.get("end", "-")
        if hasattr(s, "strftime"): s = s.strftime("%Y-%m-%d %H:%M:%S")
        if hasattr(e, "strftime"): e = e.strftime("%Y-%m-%d %H:%M:%S")
        inventory.append({"savings_plan_id": p.get("savingsPlanId","-"), "status": p.get("state","-"),
            "type": p.get("savingsPlanType","-"), "ec2_instance_family": p.get("ec2InstanceFamily","-"),
            "region": p.get("region","-"), "commitment": p.get("commitment","-"),
            "start": str(s), "end": str(e)})

    # Utilization breakdown
    pr = []
    for p in plans:
        s, e = p.get("start", "-"), p.get("end", "-")
        if hasattr(s, "strftime"): s = s.strftime("%Y-%m-%d")
        if hasattr(e, "strftime"): e = e.strftime("%Y-%m-%d")
        pr.append({"savings_plan_id": p.get("savingsPlanId","-"), "savings_plan_arn": p.get("savingsPlanArn","-"),
            "type": p.get("savingsPlanType","-"), "state": p.get("state","-"),
            "ec2_instance_family": p.get("ec2InstanceFamily","-"), "region": p.get("region","-"),
            "utilization_percent": "-", "total_commitment": "-", "used_commitment": "-", "net_savings": "-"})

    summary = {}
    coverage_breakdown = []
    try:
        ce = session.client("ce")
        _et = end_date or datetime.now(timezone.utc); _st = start_date or (_et - timedelta(days=pd))
        tp = {"Start": _st.strftime("%Y-%m-%d"), "End": _et.strftime("%Y-%m-%d")}
        t = ce.get_savings_plans_utilization(TimePeriod=tp).get("Total", {})
        ud, sd, am = t.get("Utilization",{}), t.get("Savings",{}), t.get("AmortizedCommitment",{})
        summary = {"sp_spend": f"${float(am.get('TotalAmortizedCommitment',0)):,.2f}",
            "on_demand_equivalent": f"${float(sd.get('OnDemandCostEquivalent',0)):,.2f}",
            "total_net_savings": f"${float(sd.get('NetSavings',0)):,.2f}",
            "utilization_percent": f"{float(ud.get('UtilizationPercentage',0)):.0f}%", "average_coverage": "-"}
        # Utilization details per plan
        try:
            for d in ce.get_savings_plans_utilization_details(TimePeriod=tp).get("SavingsPlansUtilizationDetails",[]):
                arn = d.get("SavingsPlanArn","")
                for x in pr:
                    if x["savings_plan_arn"] == arn:
                        du, ds2, da = d.get("Utilization",{}), d.get("Savings",{}), d.get("AmortizedCommitment",{})
                        x.update({"utilization_percent": f"{float(du.get('UtilizationPercentage',0)):.0f}%",
                            "total_commitment": f"${float(da.get('TotalAmortizedCommitment',0)):,.2f}",
                            "used_commitment": f"${float(du.get('TotalCommitment',0)):,.2f}",
                            "net_savings": f"${float(ds2.get('NetSavings',0)):,.2f}"}); break
        except: pass
        # Coverage
        try:
            cv = ce.get_savings_plans_coverage(TimePeriod=tp).get("SavingsPlansCoverages",[])
            if cv: summary["average_coverage"] = f"{float(cv[0].get('Coverage',{}).get('CoveragePercentage',0)):.0f}%"
        except: pass
        # Coverage breakdown by instance family
        try:
            cov_resp = ce.get_savings_plans_coverage(TimePeriod=tp,
                GroupBy=[{"Type": "DIMENSION", "Key": "INSTANCE_TYPE_FAMILY"}])
            for item in cov_resp.get("SavingsPlansCoverages", []):
                attrs = item.get("Attributes", {})
                cov = item.get("Coverage", {})
                coverage_breakdown.append({
                    "service": attrs.get("SERVICE", "-"),
                    "instance_family": attrs.get("INSTANCE_TYPE_FAMILY", "-"),
                    "region": attrs.get("REGION", "-"),
                    "sp_covered_spend": f"${float(cov.get('SpendCoveredBySavingsPlans', 0)):,.2f}",
                    "on_demand_spend": f"${float(cov.get('OnDemandCost', 0)):,.2f}",
                    "coverage": f"{float(cov.get('CoveragePercentage', 0)):.0f}%",
                })
        except: pass
    except: pass
    return {"summary": summary, "plans": pr, "inventory": inventory, "coverage_breakdown": coverage_breakdown}

def collect_cost_by_service(session, pd, start_date=None, end_date=None):
    logger.info("Collecting cost by service...")
    try: ce = session.client("ce")
    except Exception as e:
        logger.warning(f"Cost Explorer client gagal dibuat: {e}")
        return {"total_cost": 0, "currency": "USD", "services": []}
    _et = end_date or datetime.now(timezone.utc); _st = start_date or (_et - timedelta(days=pd))
    # Cost Explorer End is EXCLUSIVE — make the selected end date inclusive by adding 1 day
    _et_q = _et + timedelta(days=1)
    if _et_q.strftime("%Y-%m-%d") == _st.strftime("%Y-%m-%d"):
        _et_q = _st + timedelta(days=1)
    try:
        # DAILY granularity works for any date range (MONTHLY only returns data for full calendar months)
        r = ce.get_cost_and_usage(TimePeriod={"Start": _st.strftime("%Y-%m-%d"), "End": _et_q.strftime("%Y-%m-%d")},
            Granularity="DAILY", Metrics=["UnblendedCost"], GroupBy=[{"Type":"DIMENSION","Key":"SERVICE"}])
        sc = {}
        for p in r.get("ResultsByTime",[]):
            for g in p.get("Groups",[]): sc[g["Keys"][0]] = sc.get(g["Keys"][0],0) + float(g["Metrics"]["UnblendedCost"]["Amount"])
        ss = sorted(sc.items(), key=lambda x:x[1], reverse=True); tot = sum(c for _,c in ss)
        logger.info(f"Cost by service: {len(ss)} services, total=${round(tot,2)}")
        return {"total_cost": round(tot,2), "currency": "USD",
            "services": [{"service":s,"cost":round(c,2),"percent":round(c/tot*100,1) if tot>0 else 0} for s,c in ss if c>0]}
    except Exception as e:
        logger.warning(f"Gagal get cost by service: {e}")
        return {"total_cost": 0, "currency": "USD", "services": []}

def build_infrastructure_summary(ec2, rds, s3, ebs):
    sm = []
    et = {}
    for i in ec2: et[i["instance_type"]] = et.get(i["instance_type"],0)+1
    for t,c in sorted(et.items()): sm.append({"category":"Compute","service":"EC2","type":t,"qty":c})
    rt = {}
    for d in rds: rt[d["instance_type"]] = rt.get(d["instance_type"],0)+1
    for t,c in sorted(rt.items()): sm.append({"category":"Database","service":"RDS","type":t,"qty":c})
    if s3: sm.append({"category":"Storage","service":"S3","type":"-","qty":len(s3)})
    vt = {}
    for v in ebs: vt[v["storage_type"]] = vt.get(v["storage_type"],0)+1
    for t,c in sorted(vt.items()): sm.append({"category":"Storage","service":"EBS","type":t,"qty":c})
    return sm