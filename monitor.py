import json
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


def main():
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


if __name__ == "__main__":
    main()
