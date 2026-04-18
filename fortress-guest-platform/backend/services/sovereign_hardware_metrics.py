"""
Sovereign bare-metal collectors: NVML GPUs, SNMP interface rates, disk IOPS, storage mounts.

Runs on DGX / Fortress API host. All external targets are configured via Settings env vars.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import psutil
import structlog

if TYPE_CHECKING:
    from backend.core.config import Settings

logger = structlog.get_logger()

_nvml_lock = threading.Lock()
_nvml_initialized = False

_snmp_lock = threading.Lock()
# key: f"{host}:{if_index}" -> (monotonic_ts, in_octets, out_octets, discards)
_snmp_prev: dict[str, tuple[float, int, int, int]] = {}

_diskstat_lock = threading.Lock()
# mount_path -> (monotonic_ts, reads_completed, writes_completed)
_diskstat_prev: dict[str, tuple[float, int, int]] = {}


def _nvml_init() -> bool:
    global _nvml_initialized
    with _nvml_lock:
        if _nvml_initialized:
            return True
        try:
            import pynvml  # type: ignore[import-untyped]

            pynvml.nvmlInit()
            _nvml_initialized = True
            return True
        except Exception as exc:
            logger.warning("nvml_init_failed", error=str(exc))
            return False


def nvml_shutdown() -> None:
    global _nvml_initialized
    with _nvml_lock:
        if not _nvml_initialized:
            return
        try:
            import pynvml  # type: ignore[import-untyped]

            pynvml.nvmlShutdown()
        except Exception:
            pass
        _nvml_initialized = False


@dataclass(frozen=True)
class GpuReading:
    gpu_id: int
    utilization_pct: int
    memory_used_mb: int
    memory_total_mb: int
    temperature_c: int


def collect_nvml_gpus() -> list[GpuReading]:
    if not _nvml_init():
        return []
    try:
        import pynvml  # type: ignore[import-untyped]

        out: list[GpuReading] = []
        count = int(pynvml.nvmlDeviceGetCount())
        for i in range(count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            temp = int(pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU))
            used_mb = int(mem.used) // (1024 * 1024)
            total_mb = max(int(mem.total) // (1024 * 1024), 1)
            out.append(
                GpuReading(
                    gpu_id=i,
                    utilization_pct=int(min(100, max(0, util.gpu))),
                    memory_used_mb=used_mb,
                    memory_total_mb=total_mb,
                    temperature_c=temp,
                )
            )
        return out
    except Exception as exc:
        logger.warning("nvml_collect_failed", error=str(exc))
        return []


def _parse_if_indices(raw: str) -> list[int]:
    out: list[int] = []
    for part in (raw or "").split(","):
        p = part.strip()
        if not p:
            continue
        try:
            out.append(int(p))
        except ValueError:
            continue
    return out


def _snmp_get_row(host: str, port: int, community: str, if_index: int) -> tuple[str, int, int, int] | None:
    """Return (if_descr, in_octets, out_octets, drops) or None on failure."""
    try:
        from pysnmp.hlapi import (  # type: ignore[import-untyped]
            CommunityData,
            ContextData,
            ObjectIdentity,
            ObjectType,
            SnmpEngine,
            UdpTransportTarget,
            getCmd,
        )
    except ImportError:
        logger.warning("pysnmp_not_installed")
        return None

    oids = (
        ObjectType(ObjectIdentity(f"1.3.6.1.2.1.2.2.1.2.{if_index}")),
        ObjectType(ObjectIdentity(f"1.3.6.1.2.1.31.1.1.1.6.{if_index}")),
        ObjectType(ObjectIdentity(f"1.3.6.1.2.1.31.1.1.1.10.{if_index}")),
        ObjectType(ObjectIdentity(f"1.3.6.1.2.1.2.2.1.13.{if_index}")),
        ObjectType(ObjectIdentity(f"1.3.6.1.2.1.2.2.1.19.{if_index}")),
    )
    try:
        for error_indication, error_status, _error_index, var_binds in getCmd(
            SnmpEngine(),
            CommunityData(community),
            UdpTransportTarget((host, port), timeout=2.0, retries=1),
            ContextData(),
            *oids,
        ):
            if error_indication or error_status:
                return None
            vals: list[object] = [vb[1] for vb in var_binds]
            if len(vals) < 5:
                return None

            def _int(v: object) -> int:
                try:
                    return int(v)
                except Exception:
                    try:
                        return int(getattr(v, "_value", 0))
                    except Exception:
                        return 0

            descr_raw = vals[0]
            if hasattr(descr_raw, "prettyPrint"):
                descr = str(descr_raw.prettyPrint())
            else:
                descr = str(descr_raw)
            in_o = _int(vals[1])
            out_o = _int(vals[2])
            in_d = _int(vals[3])
            out_d = _int(vals[4])
            return (descr or f"if{if_index}", in_o, out_o, in_d + out_d)
    except Exception as exc:
        logger.warning("snmp_get_failed", host=host, if_index=if_index, error=str(exc))
        return None


def _build_snmp_auth(settings: Settings):
    from pysnmp.hlapi import (  # type: ignore[import-untyped]
        CommunityData,
        UsmUserData,
        usmAesCfb128Protocol,
        usmDESPrivProtocol,
        usmHMACMD5AuthProtocol,
        usmHMACSHAAuthProtocol,
    )

    version = (settings.system_health_mikrotik_snmp_version or "v2c").strip().lower()
    if version == "v3":
        username = (settings.system_health_mikrotik_snmp_v3_username or "").strip()
        auth_key = (settings.system_health_mikrotik_snmp_v3_auth_key or "").strip()
        priv_key = (settings.system_health_mikrotik_snmp_v3_priv_key or "").strip()
        if not username:
            logger.warning("snmp_v3_missing_username")
            return None
        auth_protocol_name = (settings.system_health_mikrotik_snmp_v3_auth_protocol or "SHA").strip().upper()
        priv_protocol_name = (settings.system_health_mikrotik_snmp_v3_priv_protocol or "AES128").strip().upper()
        auth_protocol = (
            usmHMACMD5AuthProtocol if auth_protocol_name == "MD5" else usmHMACSHAAuthProtocol
        )
        priv_protocol = usmDESPrivProtocol if priv_protocol_name == "DES" else usmAesCfb128Protocol
        if auth_key and priv_key:
            return UsmUserData(
                userName=username,
                authKey=auth_key,
                privKey=priv_key,
                authProtocol=auth_protocol,
                privProtocol=priv_protocol,
            )
        if auth_key:
            return UsmUserData(
                userName=username,
                authKey=auth_key,
                authProtocol=auth_protocol,
            )
        return UsmUserData(userName=username)

    raw_comm = (settings.system_health_mikrotik_snmp_community or "").strip()
    community = raw_comm or "public"
    return CommunityData(community)


@dataclass(frozen=True)
class NetworkReading:
    interface: str
    rx_bytes_sec: int
    tx_bytes_sec: int
    dropped_packets: int


def collect_snmp_network(settings: Settings) -> list[NetworkReading]:
    host = (settings.system_health_mikrotik_snmp_host or "").strip()
    if not host:
        return []
    port = int(settings.system_health_mikrotik_snmp_port)
    indices = _parse_if_indices(settings.system_health_mikrotik_snmp_if_indices)
    if not indices:
        return []
    try:
        from pysnmp.hlapi import (  # type: ignore[import-untyped]
            ContextData,
            ObjectIdentity,
            ObjectType,
            SnmpEngine,
            UdpTransportTarget,
            getCmd,
        )
    except ImportError:
        logger.warning("pysnmp_not_installed")
        return []

    auth = _build_snmp_auth(settings)
    if auth is None:
        return []

    now = time.monotonic()
    readings: list[NetworkReading] = []

    with _snmp_lock:
        for if_idx in indices:
            key = f"{host}:{if_idx}"
            row = None
            try:
                oids = (
                    ObjectType(ObjectIdentity(f"1.3.6.1.2.1.2.2.1.2.{if_idx}")),
                    ObjectType(ObjectIdentity(f"1.3.6.1.2.1.31.1.1.1.6.{if_idx}")),
                    ObjectType(ObjectIdentity(f"1.3.6.1.2.1.31.1.1.1.10.{if_idx}")),
                    ObjectType(ObjectIdentity(f"1.3.6.1.2.1.2.2.1.13.{if_idx}")),
                    ObjectType(ObjectIdentity(f"1.3.6.1.2.1.2.2.1.19.{if_idx}")),
                )
                for error_indication, error_status, _error_index, var_binds in getCmd(
                    SnmpEngine(),
                    auth,
                    UdpTransportTarget((host, port), timeout=2.0, retries=1),
                    ContextData(),
                    *oids,
                ):
                    if error_indication or error_status:
                        row = None
                        break
                    vals: list[object] = [vb[1] for vb in var_binds]
                    if len(vals) < 5:
                        row = None
                        break

                    def _int(v: object) -> int:
                        try:
                            return int(v)
                        except Exception:
                            try:
                                return int(getattr(v, "_value", 0))
                            except Exception:
                                return 0

                    descr_raw = vals[0]
                    descr = str(descr_raw.prettyPrint()) if hasattr(descr_raw, "prettyPrint") else str(descr_raw)
                    row = (
                        descr or f"if{if_idx}",
                        _int(vals[1]),
                        _int(vals[2]),
                        _int(vals[3]) + _int(vals[4]),
                    )
            except Exception as exc:
                logger.warning("snmp_get_failed", host=host, if_index=if_idx, error=str(exc))
            if row is None:
                continue
            descr, in_oct, out_oct, drops = row
            prev = _snmp_prev.get(key)
            _snmp_prev[key] = (now, in_oct, out_oct, drops)

            if prev is None:
                readings.append(
                    NetworkReading(interface=descr, rx_bytes_sec=0, tx_bytes_sec=0, dropped_packets=drops)
                )
                continue

            p_t, p_in, p_out, _p_drops = prev
            dt = now - p_t
            if dt <= 0:
                readings.append(
                    NetworkReading(interface=descr, rx_bytes_sec=0, tx_bytes_sec=0, dropped_packets=drops)
                )
                continue
            rx_sec = max(0, int((in_oct - p_in) / dt))
            tx_sec = max(0, int((out_oct - p_out) / dt))
            readings.append(
                NetworkReading(
                    interface=descr,
                    rx_bytes_sec=rx_sec,
                    tx_bytes_sec=tx_sec,
                    dropped_packets=drops,
                )
            )

    return readings


def _parse_mount_list(raw: str) -> list[tuple[str, str]]:
    """Return list of (label, path) from comma-separated mount paths."""
    paths: list[str] = []
    for part in (raw or "").split(","):
        p = part.strip()
        if p:
            paths.append(p)
    if not paths:
        paths = ["/mnt/synology"]
    out: list[tuple[str, str]] = []
    for path in paths:
        label = path.rstrip("/").split("/")[-1] or path
        out.append((label, path))
    return out


def _diskstats_line_for_device(major: int, minor: int) -> tuple[int, int] | None:
    """Return (reads_completed, writes_completed) for block dev major:minor."""
    try:
        with open("/proc/diskstats", encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 16:
                    continue
                if int(parts[0]) == major and int(parts[1]) == minor:
                    reads = int(parts[3])
                    writes = int(parts[7])
                    return reads, writes
    except Exception:
        return None
    return None


def _iops_for_mount(mount_path: str) -> int:
    try:
        st = os.stat(mount_path)
        dev = st.st_dev
        major = os.major(dev)
        minor = os.minor(dev)
    except Exception:
        return 0

    line = _diskstats_line_for_device(major, minor)
    if line is None:
        return 0
    reads, writes = line
    now = time.monotonic()
    with _diskstat_lock:
        prev = _diskstat_prev.get(mount_path)
        _diskstat_prev[mount_path] = (now, reads, writes)
        if prev is None:
            return 0
        p_t, p_r, p_w = prev
        dt = now - p_t
        if dt <= 0:
            return 0
        return max(0, int(((reads - p_r) + (writes - p_w)) / dt))


@dataclass(frozen=True)
class StorageReading:
    volume: str
    mount_path: str
    capacity_pct: float
    iops: int


def collect_storage(settings: Settings) -> list[StorageReading]:
    out: list[StorageReading] = []
    for label, path in _parse_mount_list(settings.system_health_synology_mount_paths):
        try:
            usage = psutil.disk_usage(path)
            iops = _iops_for_mount(path)
            out.append(
                StorageReading(
                    volume=label,
                    mount_path=path,
                    capacity_pct=round(float(usage.percent), 2),
                    iops=iops,
                )
            )
        except Exception as exc:
            logger.warning("storage_mount_unreadable", path=path, error=str(exc))
    return out


def host_cpu_ram_load() -> tuple[float, float, float]:
    """CPU percent (non-blocking), RAM percent, 1m load average."""
    load_1 = 0.0
    try:
        load_1, _, _ = os.getloadavg()
    except OSError:
        pass
    ram = psutil.virtual_memory()
    return round(psutil.cpu_percent(interval=None), 1), round(ram.percent, 1), round(load_1, 2)
