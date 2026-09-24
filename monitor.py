import argparse
import grp
import json
import os
import pwd
import subprocess

import psutil


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


def main():
    parser = argparse.ArgumentParser(description="Disk & Process Health Monitor")
    parser.add_argument("--watch", help="Process name to monitor (e.g. nova-compute)")
    parser.add_argument("--check-path", help="Path to check ownership/permissions (e.g. /var/lib/nova)")
    parser.add_argument("--expected-owner", help="Expected user:group for --check-path (e.g. nova:nova)")
    args = parser.parse_args()

    disk_results = check_disk_usage()
    print("=== Disk Usage (Task 1) ===")
    for r in disk_results:
        status = "ALERT: ABOVE 80%!" if r["flagged"] else "OK"
        print(f"{r['device']} mounted on {r['mountpoint']} ({r['fstype']}): {r['percent_used']}% used - {status}")

    block_devices = get_block_devices()
    print("\n=== Block Devices (Task 2) ===")
    for d in block_devices:
        mp = ", ".join(d["mountpoints"]) if d["mountpoints"] else "(not mounted)"
        print(f"{d['name']} - size: {d['size']}, type: {d['type']}, mountpoint: {mp}")

    if args.watch:
        print(f"\n=== Process Watch (Task 3): '{args.watch}' ===")
        matches = check_process(args.watch)
        if matches:
            for m in matches:
                print(f"PID {m['pid']} - {m['name']} - CPU: {m['cpu_percent']}% - Memory: {m['memory_mb']} MB")
        else:
            print(f"ALERT: Process '{args.watch}' is NOT running!")

    if args.check_path:
        print(f"\n=== Path Check (Task 4): '{args.check_path}' ===")
        result = check_path_permissions(args.check_path, args.expected_owner)
        if "error" in result:
            print(f"ALERT: {result['error']}")
        else:
            print(f"Path: {result['path']}")
            print(f"Owner: {result['owner']}")
            print(f"Permissions: {result['permissions']}")
            if result["mismatch"]:
                print(f"ALERT: Ownership mismatch! Expected {result['expected']}, got {result['owner']}")
            elif args.expected_owner:
                print("Ownership matches expected value - OK")


if __name__ == "__main__":
    main()
