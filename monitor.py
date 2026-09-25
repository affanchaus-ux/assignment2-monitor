import argparse
import grp
import json
import logging
import os
import pwd
import subprocess
import time
from logging.handlers import RotatingFileHandler

import psutil
import yaml


def load_config(config_file="config.yaml"):
    if not os.path.exists(config_file):
        return {}
    with open(config_file) as f:
        return yaml.safe_load(f) or {}


def setup_logging(log_file="monitor.log", max_bytes=1_000_000, backup_count=3):
    logger = logging.getLogger("monitor")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count)
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


def check_disk_usage(threshold=80):
    results = []
    for partition in psutil.disk_partitions():
        try:
            usage = psutil.disk_usage(partition.mountpoint)
        except PermissionError:
            continue
        flagged = usage.percent > threshold
        results.append({
            "device": partition.device,
            "mountpoint": partition.mountpoint,
            "fstype": partition.fstype,
            "percent_used": usage.percent,
            "flagged": flagged,
        })
    return results


def get_block_devices():
    output = subprocess.run(
        ["lsblk", "-J"], capture_output=True, text=True, check=True
    )
    data = json.loads(output.stdout)

    devices = []
    seen_names = set()

    def walk(dev_list):
        for dev in dev_list:
            name = dev.get("name")
            if name not in seen_names:
                seen_names.add(name)
                mountpoints = [m for m in dev.get("mountpoints", []) if m]
                devices.append({
                    "name": name,
                    "size": dev.get("size"),
                    "type": dev.get("type"),
                    "mountpoints": mountpoints,
                })
            if "children" in dev:
                walk(dev["children"])

    walk(data["blockdevices"])
    return devices


def check_process(name):
    matches = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            proc_name = proc.info["name"] or ""
            if name.lower() in proc_name.lower():
                cpu = proc.cpu_percent(interval=0.1)
                mem_mb = proc.memory_info().rss / (1024 * 1024)
                matches.append({
                    "pid": proc.info["pid"],
                    "name": proc_name,
                    "cpu_percent": cpu,
                    "memory_mb": round(mem_mb, 2),
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return matches


def check_path_permissions(path, expected_owner=None):
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return {"error": f"Path '{path}' does not exist"}
    except PermissionError:
        return {"error": f"Permission denied accessing '{path}'"}

    owner_user = pwd.getpwuid(st.st_uid).pw_name
    owner_group = grp.getgrgid(st.st_gid).gr_name
    perms = oct(st.st_mode)[-3:]
    actual_owner = f"{owner_user}:{owner_group}"

    result = {
        "path": path,
        "owner": actual_owner,
        "permissions": perms,
        "mismatch": False,
    }

    if expected_owner and actual_owner != expected_owner:
        result["mismatch"] = True
        result["expected"] = expected_owner

    return result


def run_checks(settings, logger):
    alerts = []

    disk_results = check_disk_usage(threshold=settings["threshold"])
    print("=== Disk Usage (Task 1) ===")
    for r in disk_results:
        status = "ALERT: ABOVE 80%!" if r["flagged"] else "OK"
        line = f"{r['device']} mounted on {r['mountpoint']} ({r['fstype']}): {r['percent_used']}% used - {status}"
        print(line)
        if r["flagged"]:
            logger.warning(line)
            alerts.append(line)
        else:
            logger.info(line)

    block_devices = get_block_devices()
    print("\n=== Block Devices (Task 2) ===")
    for d in block_devices:
        mp = ", ".join(d["mountpoints"]) if d["mountpoints"] else "(not mounted)"
        line = f"{d['name']} - size: {d['size']}, type: {d['type']}, mountpoint: {mp}"
        print(line)
        logger.info(line)

    if settings["watch"]:
        print(f"\n=== Process Watch (Task 3): '{settings['watch']}' ===")
        matches = check_process(settings["watch"])
        if matches:
            for m in matches:
                line = f"PID {m['pid']} - {m['name']} - CPU: {m['cpu_percent']}% - Memory: {m['memory_mb']} MB"
                print(line)
                logger.info(line)
        else:
            line = f"ALERT: Process '{settings['watch']}' is NOT running!"
            print(line)
            logger.warning(line)
            alerts.append(line)

    if settings["check_path"]:
        print(f"\n=== Path Check (Task 4): '{settings['check_path']}' ===")
        result = check_path_permissions(settings["check_path"], settings["expected_owner"])
        if "error" in result:
            line = f"ALERT: {result['error']}"
            print(line)
            logger.error(line)
            alerts.append(line)
        else:
            print(f"Path: {result['path']}")
            print(f"Owner: {result['owner']}")
            print(f"Permissions: {result['permissions']}")
            logger.info(
                f"Path: {result['path']}, Owner: {result['owner']}, "
                f"Permissions: {result['permissions']}"
            )
            if result["mismatch"]:
                line = f"ALERT: Ownership mismatch! Expected {result['expected']}, got {result['owner']}"
                print(line)
                logger.warning(line)
                alerts.append(line)
            elif settings["expected_owner"]:
                print("Ownership matches expected value - OK")

    print("\n=== Alert Summary (Task 6) ===")
    if alerts:
        print(f"Total alerts: {len(alerts)}")
        for a in alerts:
            print(f" - {a}")
        logger.warning(f"Alert summary: {len(alerts)} alert(s) found")
    else:
        print("No alerts - all checks passed OK")
        logger.info("Alert summary: no alerts")


def main():
    parser = argparse.ArgumentParser(description="Disk & Process Health Monitor")
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML file (default: config.yaml)")
    parser.add_argument("--threshold", type=int, default=None, help="Disk usage alert threshold percent")
    parser.add_argument("--watch", default=None, help="Process name to monitor (e.g. nova-compute)")
    parser.add_argument("--check-path", default=None, help="Path to check ownership/permissions (e.g. /var/lib/nova)")
    parser.add_argument("--expected-owner", default=None, help="Expected user:group for --check-path (e.g. nova:nova)")
    parser.add_argument("--interval", type=int, default=None, help="Seconds between checks in continuous mode")
    parser.add_argument("--once", action="store_true", help="Run checks a single time and exit (for testing)")
    args = parser.parse_args()

    config = load_config(args.config)

    settings = {
        "threshold": args.threshold if args.threshold is not None else config.get("disk_threshold", 80),
        "watch": args.watch or config.get("watch_process"),
        "check_path": args.check_path or config.get("check_path"),
        "expected_owner": args.expected_owner or config.get("expected_owner"),
        "interval": args.interval if args.interval is not None else config.get("interval", 30),
    }

    logger = setup_logging(
        log_file=config.get("log_file", "monitor.log"),
        max_bytes=config.get("log_max_bytes", 1_000_000),
        backup_count=config.get("log_backup_count", 3),
    )

    if args.once:
        run_checks(settings, logger)
        return

    print(f"Starting continuous monitoring (every {settings['interval']}s). Press Ctrl+C to stop.")
    logger.info("Monitoring started (continuous mode)")
    try:
        while True:
            run_checks(settings, logger)
            time.sleep(settings["interval"])
    except KeyboardInterrupt:
        print("\nMonitoring stopped by user.")
        logger.info("Monitoring stopped by user (KeyboardInterrupt)")


if __name__ == "__main__":
    main()
