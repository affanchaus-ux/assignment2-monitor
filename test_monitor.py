import json
from unittest.mock import MagicMock, patch

import monitor


class FakePartition:
    def __init__(self, device, mountpoint, fstype):
        self.device = device
        self.mountpoint = mountpoint
        self.fstype = fstype


class FakeUsage:
    def __init__(self, percent):
        self.percent = percent


def test_check_disk_usage_flags_above_threshold():
    partitions = [FakePartition("/dev/sda1", "/", "ext4")]
    with patch("monitor.psutil.disk_partitions", return_value=partitions), \
         patch("monitor.psutil.disk_usage", return_value=FakeUsage(85.0)):
        results = monitor.check_disk_usage(threshold=80)

    assert len(results) == 1
    assert results[0]["flagged"] is True
    assert results[0]["percent_used"] == 85.0


def test_check_disk_usage_ok_below_threshold():
    partitions = [FakePartition("/dev/sda1", "/", "ext4")]
    with patch("monitor.psutil.disk_partitions", return_value=partitions), \
         patch("monitor.psutil.disk_usage", return_value=FakeUsage(20.0)):
        results = monitor.check_disk_usage(threshold=80)

    assert results[0]["flagged"] is False


def test_check_disk_usage_skips_permission_error():
    partitions = [FakePartition("/dev/sda1", "/mnt/protected", "ext4")]
    with patch("monitor.psutil.disk_partitions", return_value=partitions), \
         patch("monitor.psutil.disk_usage", side_effect=PermissionError):
        results = monitor.check_disk_usage()

    assert results == []


FAKE_LSBLK_OUTPUT = {
    "blockdevices": [
        {
            "name": "sda",
            "size": "40G",
            "type": "disk",
            "mountpoints": [None],
            "children": [
                {"name": "sda1", "size": "38G", "type": "part", "mountpoints": ["/"]}
            ],
        }
    ]
}


def test_get_block_devices_parses_and_dedupes():
    fake_result = MagicMock()
    fake_result.stdout = json.dumps(FAKE_LSBLK_OUTPUT)
    with patch("monitor.subprocess.run", return_value=fake_result):
        devices = monitor.get_block_devices()

    names = [d["name"] for d in devices]
    assert names == ["sda", "sda1"]
    assert devices[1]["mountpoints"] == ["/"]


class FakeProcess:
    def __init__(self, pid, name, cpu, mem_bytes):
        self.info = {"pid": pid, "name": name}
        self._cpu = cpu
        self._mem = mem_bytes

    def cpu_percent(self, interval=None):
        return self._cpu

    def memory_info(self):
        mem = MagicMock()
        mem.rss = self._mem
        return mem


def test_check_process_finds_match():
    procs = [FakeProcess(101, "sshd", 0.5, 10 * 1024 * 1024)]
    with patch("monitor.psutil.process_iter", return_value=procs):
        matches = monitor.check_process("sshd")

    assert len(matches) == 1
    assert matches[0]["pid"] == 101
    assert matches[0]["memory_mb"] == 10.0


def test_check_process_no_match():
    procs = [FakeProcess(101, "nginx", 0.1, 1024)]
    with patch("monitor.psutil.process_iter", return_value=procs):
        matches = monitor.check_process("sshd")

    assert matches == []


def test_check_path_permissions_ok(tmp_path):
    test_file = tmp_path / "testfile"
    test_file.write_text("hello")

    result = monitor.check_path_permissions(str(test_file))

    assert result["path"] == str(test_file)
    assert result["mismatch"] is False
    assert "owner" in result


def test_check_path_permissions_missing_path():
    result = monitor.check_path_permissions("/nonexistent/path/xyz123")

    assert "error" in result
    assert "does not exist" in result["error"]


def test_check_path_permissions_mismatch(tmp_path):
    test_file = tmp_path / "testfile"
    test_file.write_text("hello")

    result = monitor.check_path_permissions(str(test_file), expected_owner="nobody:nogroup")

    assert result["mismatch"] is True
    assert result["expected"] == "nobody:nogroup"
