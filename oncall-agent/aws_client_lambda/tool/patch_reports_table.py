import os
import re
import csv
from datetime import datetime, timezone
from typing import Dict, List, Tuple

import boto3
import botocore

PKG_ARCHES = ("x86_64", "aarch64", "i386", "i686", "noarch")

# ---------- helpers ----------

def iso_utc(dt) -> str:
    if not dt:
        return ""
    if isinstance(dt, (int, float)):
        dt = datetime.fromtimestamp(dt, tz=timezone.utc)
    if getattr(dt, "tzinfo", None) is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()

def list_objects(s3, bucket: str, prefix: str):
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            yield obj

def read_text(s3, bucket: str, key: str) -> str:
    try:
        r = s3.get_object(Bucket=bucket, Key=key)
        return r["Body"].read().decode("utf-8", errors="replace")
    except botocore.exceptions.ClientError as e:
        print(f"[WARN] Cannot read s3://{bucket}/{key}: {e}")
        return ""

def find_instance_ids_from_key(key: str) -> List[str]:
    return [p for p in key.split("/") if p.startswith("i-")]

def get_instance_names(region: str, instance_ids: List[str]) -> Dict[str, str]:
    names: Dict[str, str] = {}
    if not instance_ids:
        return names
    ec2 = boto3.client("ec2", region_name=region)
    try:
        for i in range(0, len(instance_ids), 100):
            batch = instance_ids[i:i+100]
            resp = ec2.describe_instances(InstanceIds=batch)
            for res in resp.get("Reservations", []):
                for inst in res.get("Instances", []):
                    iid = inst.get("InstanceId", "")
                    nm = ""
                    for t in inst.get("Tags", []):
                        if t.get("Key") == "Name":
                            nm = t.get("Value", "")
                            break
                    names[iid] = nm
    except Exception as e:
        print(f"[WARN] describe_instances failed: {e}")
    return names

def stdout_is_install(stdout: str) -> bool:
    s = stdout.lower()
    if "operation = install" in s or "operation type: install" in s:
        return True
    return "installed:" in s and "no packages" not in s

def parse_packages_from_stdout(stdout: str) -> List[Dict]:
    """
    Supports:
      1) Dict-style block after 'Reading Local Configuration file'
      2) 'Installed:' section with lines like 'package.arch version'
    """
    packages: List[Dict] = []
    if not stdout:
        return packages

    dict_pat = re.compile(
        r"'(?P<key>(?P<base>[^']+?):(?P<epoch>\d+):(?P<ver>[^']+))'"
        r"\s*:\s*\{[^}]*?'installedTime'\s*:\s*(?P<itime>\d+)[^}]*?"
        r"'state'\s*:\s*'(?P<state>[^']+)'[^}]*\}",
        re.DOTALL,
    )
    for m in dict_pat.finditer(stdout):
        if m.group("state") != "Installed":
            continue
        base = m.group("base")
        name = base
        if "." in base:
            maybe_name, maybe_arch = base.rsplit(".", 1)
            if maybe_arch in PKG_ARCHES:
                name = maybe_name
        ver = m.group("ver")
        try:
            ts_iso = datetime.fromtimestamp(int(m.group("itime")), tz=timezone.utc).isoformat()
        except Exception:
            ts_iso = ""
        packages.append({
            "name": name,
            "version": ver,
            "installed_at": ts_iso,
            "full_line": f"{m.group('key')} state=Installed",
        })

    in_installed = False
    for line in stdout.splitlines():
        s = line.strip()
        if not s:
            continue
        if "Installed:" in s:
            in_installed = True
            continue
        if any(h in s for h in ("Missing:", "Failed:", "InstalledRejected:")):
            in_installed = False
            continue
        if in_installed:
            parts = s.split()
            if len(parts) >= 2:
                pkg = parts[0]
                ver = parts[1]
                if "." in pkg:
                    name_part, arch = pkg.rsplit(".", 1)
                    if arch in PKG_ARCHES:
                        pkg = name_part
                packages.append({
                    "name": pkg,
                    "version": ver,
                    "installed_at": "",
                    "full_line": s,
                })

    return packages

def build_rows_from_s3(region: str, bucket: str, prefix: str,
                       window_id: str, window_execution_id: str, window_name: str) -> List[Dict]:
    s3 = boto3.client("s3", region_name=region)

    stdout_objs: List[Tuple[str, dict]] = []
    total = 0
    for obj in list_objects(s3, bucket, prefix):
        total += 1
        key = obj["Key"]
        base = key.rsplit("/", 1)[-1].lower()
        if base in ("stdout", "stdout.txt"):
            stdout_objs.append((key, obj))

    print(f"[INFO] Listed {total} objects, found {len(stdout_objs)} stdout files under s3://{bucket}/{prefix}")

    inst_ids = []
    for key, _ in stdout_objs:
        inst_ids.extend(find_instance_ids_from_key(key))
    inst_ids = sorted(set(inst_ids))
    names = get_instance_names(region, inst_ids)

    rows: List[Dict] = []

    for key, meta in stdout_objs:
        stdout = read_text(s3, bucket, key)
        pkgs = parse_packages_from_stdout(stdout)

        # Skip SCAN-only logs unless we still parsed something
        if not pkgs and not stdout_is_install(stdout):
            continue

        iid = ""
        for seg in key.split("/"):
            if seg.startswith("i-"):
                iid = seg
                break

        if not pkgs:
            rows.append({
                "instance_id": iid,
                "instance_name": names.get(iid, ""),
                "package_name": "",
                "version": "",
                "installed_at": iso_utc(meta.get("LastModified")),
                "window_name": window_name,
                "window_id": window_id,
                "window_execution_id": window_execution_id,
                "full_line": f"(no packages parsed) s3://{bucket}/{key}",
            })
            continue

        for p in pkgs:
            rows.append({
                "instance_id": iid,
                "instance_name": names.get(iid, ""),
                "package_name": p.get("name", ""),
                "version": p.get("version", ""),
                "installed_at": p.get("installed_at") or iso_utc(meta.get("LastModified")),
                "window_name": window_name,
                "window_id": window_id,
                "window_execution_id": window_execution_id,
                "full_line": p.get("full_line", ""),
            })

    return rows

def write_csv(rows: List[Dict], out_path: str) -> str:
    fieldnames = [
        "instance_id",
        "instance_name",
        "package_name",
        "version",
        "installed_at",
        "window_name",
        "window_id",
        "window_execution_id",
        "full_line",
    ]
    os.makedirs(os.path.dirname(out_path) or "/tmp", exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})
    return out_path

def upload_csv_to_s3(region: str, local_path: str, dest_bucket: str, dest_key: str):
    s3 = boto3.client("s3", region_name=region)
    with open(local_path, "rb") as fh:
        s3.put_object(
            Bucket=dest_bucket,
            Key=dest_key,
            Body=fh.read(),
            ContentType="text/csv",
        )
    print(f"[INFO] Uploaded CSV to s3://{dest_bucket}/{dest_key}")

# ---------- Lambda handler ----------

def handler(event, context):
    """
    Expected inputs:
      - From EventBridge (Maintenance Window Execution success):
          event.detail.WindowId, event.detail.WindowExecutionId, event.detail.Name (optional)
      - Or custom invoke with:
          event["bucket"], event["prefix"]  OR  event["window_id"] + event["execution_id"]
      Env vars:
          MW_LOG_BUCKET        (bucket to READ logs from) [optional if provided in event]
          DEST_BUCKET          (bucket to WRITE CSV to; defaults to MW_LOG_BUCKET)
          DEST_PREFIX          (default "mw-csv/")
          PREFIX_TEMPLATE      (default "{window_id}-prod/{execution_id}/")
          AWS_REGION           (Lambda provides this)
    """
    print(f"[INFO] Incoming event keys: {list(event.keys()) if isinstance(event, dict) else type(event)}")

    region = os.environ.get("AWS_REGION", "us-east-1")
    mw_log_bucket = event.get("bucket") or os.environ.get("MW_LOG_BUCKET")
    if not mw_log_bucket:
        raise ValueError("Missing bucket: set event['bucket'] or env MW_LOG_BUCKET")

    # Try EventBridge detail first
    detail = event.get("detail", {}) if isinstance(event, dict) else {}
    window_id = (
        event.get("window_id")
        or detail.get("WindowId")
        or detail.get("windowId")
        or ""
    )
    execution_id = (
        event.get("execution_id")
        or detail.get("WindowExecutionId")
        or detail.get("windowExecutionId")
        or ""
    )
    window_name = (
        event.get("window_name")
        or detail.get("Name")
        or os.environ.get("WINDOW_NAME_DEFAULT", "")
    )

    # Build scan prefix
    prefix = event.get("prefix")
    if not prefix:
        tmpl = os.environ.get("PREFIX_TEMPLATE", "{window_id}-prod/{execution_id}/")
        if not window_id or not execution_id:
            raise ValueError("Need window_id and execution_id (from event.detail or event fields) when no prefix is provided.")
        prefix = tmpl.format(window_id=window_id, execution_id=execution_id)
        if not prefix.endswith("/"):
            prefix += "/"

    print(f"[INFO] Region: {region}")
    print(f"[INFO] Read Bucket: {mw_log_bucket}")
    print(f"[INFO] Scan Prefix: s3://{mw_log_bucket}/{prefix}")

    rows = build_rows_from_s3(
        region=region,
        bucket=mw_log_bucket,
        prefix=prefix,
        window_id=window_id or "unknown-window",
        window_execution_id=execution_id or "unknown-exec",
        window_name=window_name or "",
    )

    parsed_count = len(rows)
    if parsed_count == 0:
        print("[WARN] No rows parsed. This often means SCAN-only run, wrong prefix, or outputs not in S3 yet.")

    # Write CSV to /tmp and upload to S3
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_window = window_id or "unknown-window"
    safe_exec = execution_id or "unknown-exec"
    local_path = f"/tmp/mw_packages_{safe_window}_{safe_exec}_{ts}.csv"
    write_csv(rows, local_path)
    print(f"[INFO] Local CSV: {local_path}")

    dest_bucket = os.environ.get("DEST_BUCKET") or mw_log_bucket
    dest_prefix = os.environ.get("DEST_PREFIX", "mw-csv/").strip("/")
    dest_key = f"{dest_prefix}/{safe_window}/{safe_exec}/mw_packages_{safe_window}_{safe_exec}_{ts}.csv"
    upload_csv_to_s3(region, local_path, dest_bucket, dest_key)

    return {
        "ok": True,
        "parsed_rows": parsed_count,
        "read_bucket": mw_log_bucket,
        "scan_prefix": prefix,
        "dest_bucket": dest_bucket,
        "dest_key": dest_key,
        "window_id": safe_window,
        "execution_id": safe_exec,
        "window_name": window_name,
    }