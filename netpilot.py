#!/usr/bin/env python3
"""
NetPilot - Advanced Network Device Discovery and Management for FreeBSD/PGSD

This script provides comprehensive network device discovery, driver management,
interface configuration, and network diagnostics for GhostBSD and FreeBSD systems.

Author: NetPilot Project
License: BSD 2-Clause
Version: 0.0.4
"""

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import time
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Union, Any, Tuple
from enum import Enum
import tempfile
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
NETWORK_CLASS_PREFIX = "02"
USB_NETWORK_CLASS = "0x02"
MAX_RETRY_ATTEMPTS = 3
DRIVER_LOAD_TIMEOUT = 10
INTERFACE_PROBE_DELAY = 2
NETPILOT_VERSION = "0.0.4"

class DeviceType(Enum):
    ETHERNET = "ethernet"
    WIFI = "wifi"
    USB_ETHERNET = "usb_ethernet"
    USB_WIFI = "usb_wifi"
    UNKNOWN = "unknown"

class InterfaceStatus(Enum):
    UP = "up"
    DOWN = "down"
    ACTIVE = "active"
    INACTIVE = "inactive"
    NO_CARRIER = "no_carrier"

# Compiled regex patterns
PCI_PATTERN = re.compile(
    r'^(?P<tag>\w+)@pci.*\n'
    r'\s*vendor\s*=\s*"(?P<venname>[^"]+)"\s*\(0x(?P<vendor>[0-9a-f]+)\)\n'
    r'\s*device\s*=\s*"(?P<devname>[^"]+)"\s*\(0x(?P<device>[0-9a-f]+)\)\n'
    r'.*class\s*=\s*0x(?P<class>[0-9a-f]{4})',
    re.MULTILINE | re.IGNORECASE
)

USB_VENDOR_PATTERN = re.compile(r"idVendor\s*=\s*0x([0-9a-f]{4})", re.IGNORECASE)
USB_PRODUCT_PATTERN = re.compile(r"idProduct\s*=\s*0x([0-9a-f]{4})", re.IGNORECASE)
USB_CLASS_PATTERN = re.compile(r"bDeviceClass\s*=\s*(0x[0-9a-f]{2})", re.IGNORECASE)
USB_INTERFACE_CLASS_PATTERN = re.compile(r"bInterfaceClass\s*=\s*(0x[0-9a-f]{2})", re.IGNORECASE)


@dataclass
class NetworkDevice:
    """Enhanced network device representation."""
    vendor: str
    device: str
    device_class: str
    vendor_name: Optional[str] = None
    device_name: Optional[str] = None
    bus_info: Optional[str] = None
    is_usb: bool = False
    device_type: DeviceType = DeviceType.UNKNOWN
    subsystem_vendor: Optional[str] = None
    subsystem_device: Optional[str] = None
    driver_loaded: Optional[str] = None
    firmware_required: Optional[str] = None
    capabilities: List[str] = field(default_factory=list)


@dataclass
class DriverRule:
    """Enhanced driver rule with dependencies and conflicts."""
    kld: str
    vendor: Optional[str] = None
    device_ids: Optional[List[str]] = None
    vendor_ids: Optional[List[str]] = None
    device_class: Optional[str] = None
    is_usb: bool = False
    firmware: Optional[str] = None
    description: Optional[str] = None
    device_type: DeviceType = DeviceType.UNKNOWN
    dependencies: List[str] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)
    load_order: int = 50  # Lower numbers load first
    min_freebsd_version: Optional[str] = None


@dataclass
class NetworkInterface:
    """Enhanced network interface with full configuration."""
    name: str
    status: InterfaceStatus = InterfaceStatus.DOWN
    mac_address: Optional[str] = None
    interface_type: DeviceType = DeviceType.UNKNOWN
    driver: Optional[str] = None
    speed: Optional[str] = None
    duplex: Optional[str] = None
    mtu: Optional[int] = None
    ip_addresses: List[str] = field(default_factory=list)
    wireless_info: Optional[Dict[str, Any]] = None
    statistics: Optional[Dict[str, int]] = None
    capabilities: List[str] = field(default_factory=list)


@dataclass
class WirelessNetwork:
    """Represents a discovered wireless network."""
    ssid: str
    bssid: str
    signal_strength: int
    frequency: str
    encryption: str
    channel: int


@dataclass
class SystemConfigEntry:
    """Represents a system configuration entry."""
    file_path: str
    key: str
    value: str
    comment: Optional[str] = None
    section: Optional[str] = None


@dataclass
class ConfigurationChange:
    """Represents a configuration change made by NetPilot."""
    timestamp: str
    file_path: str
    action: str  # "added", "modified", "removed"
    key: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    backup_file: Optional[str] = None


class SystemConfigManager:
    """Manages system configuration files (/boot/loader.conf and /etc/rc.conf)."""
    
    def __init__(self, backup_dir: str = "/var/backups/netpilot"):
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.changes: List[ConfigurationChange] = []
        
        # Configuration file paths
        self.loader_conf = Path("/boot/loader.conf")
        self.rc_conf = Path("/etc/rc.conf")
        
    def backup_file(self, file_path: Path) -> Optional[str]:
        """Create a backup of a configuration file."""
        try:
            if not file_path.exists():
                return None
                
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"{file_path.name}.{timestamp}.backup"
            backup_path = self.backup_dir / backup_name
            
            shutil.copy2(file_path, backup_path)
            logger.info(f"Created backup: {backup_path}")
            return str(backup_path)
            
        except Exception as e:
            logger.error(f"Failed to backup {file_path}: {e}")
            return None
    
    def read_config_file(self, file_path: Path) -> Dict[str, str]:
        """Read and parse a configuration file."""
        config = {}
        try:
            if not file_path.exists():
                return config
                
            with open(file_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        if '=' in line:
                            key, value = line.split('=', 1)
                            config[key.strip()] = value.strip().strip('"')
        except Exception as e:
            logger.error(f"Failed to read {file_path}: {e}")
        
        return config
    
    def write_config_file(self, file_path: Path, config: Dict[str, str], 
                         new_entries: List[SystemConfigEntry]) -> bool:
        """Write configuration file with new entries."""
        try:
            # Read existing content to preserve comments and structure
            existing_lines = []
            if file_path.exists():
                with open(file_path, 'r') as f:
                    existing_lines = f.readlines()
            
            # Create new content
            new_lines = []
            processed_keys = set()
            
            # Process existing lines
            for line in existing_lines:
                stripped = line.strip()
                if stripped and not stripped.startswith('#') and '=' in stripped:
                    key = stripped.split('=', 1)[0].strip()
                    # Check if we need to update this key
                    updated = False
                    for entry in new_entries:
                        if entry.key == key:
                            new_lines.append(f'{key}="{entry.value}"\n')
                            processed_keys.add(key)
                            updated = True
                            break
                    if not updated:
                        new_lines.append(line)
                else:
                    new_lines.append(line)
            
            # Add NetPilot section if we have new entries
            unprocessed_entries = [e for e in new_entries if e.key not in processed_keys]
            if unprocessed_entries:
                new_lines.append(f"\n# NetPilot Configuration - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                for entry in unprocessed_entries:
                    if entry.comment:
                        new_lines.append(f"# {entry.comment}\n")
                    new_lines.append(f'{entry.key}="{entry.value}"\n')
            
            # Write to temporary file first, then move
            temp_file = file_path.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                f.writelines(new_lines)
            
            # Atomic move
            temp_file.rename(file_path)
            logger.info(f"Updated configuration file: {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to write {file_path}: {e}")
            return False
    
    def add_loader_conf_entries(self, entries: List[SystemConfigEntry]) -> bool:
        """Add entries to /boot/loader.conf."""
        if not entries:
            return True
            
        logger.info(f"Adding {len(entries)} entries to {self.loader_conf}")
        
        # Backup first
        backup_file = self.backup_file(self.loader_conf)
        
        # Read existing config
        existing_config = self.read_config_file(self.loader_conf)
        
        # Filter out entries that already exist with same value
        new_entries = []
        for entry in entries:
            if entry.key not in existing_config or existing_config[entry.key] != entry.value:
                new_entries.append(entry)
                
                # Record the change
                change = ConfigurationChange(
                    timestamp=datetime.now().isoformat(),
                    file_path=str(self.loader_conf),
                    action="modified" if entry.key in existing_config else "added",
                    key=entry.key,
                    old_value=existing_config.get(entry.key),
                    new_value=entry.value,
                    backup_file=backup_file
                )
                self.changes.append(change)
        
        if not new_entries:
            logger.debug("No new loader.conf entries needed")
            return True
        
        return self.write_config_file(self.loader_conf, existing_config, new_entries)
    
    def add_rc_conf_entries(self, entries: List[SystemConfigEntry]) -> bool:
        """Add entries to /etc/rc.conf."""
        if not entries:
            return True
            
        logger.info(f"Adding {len(entries)} entries to {self.rc_conf}")
        
        # Backup first
        backup_file = self.backup_file(self.rc_conf)
        
        # Read existing config
        existing_config = self.read_config_file(self.rc_conf)
        
        # Filter out entries that already exist with same value
        new_entries = []
        for entry in entries:
            if entry.key not in existing_config or existing_config[entry.key] != entry.value:
                new_entries.append(entry)
                
                # Record the change
                change = ConfigurationChange(
                    timestamp=datetime.now().isoformat(),
                    file_path=str(self.rc_conf),
                    action="modified" if entry.key in existing_config else "added",
                    key=entry.key,
                    old_value=existing_config.get(entry.key),
                    new_value=entry.value,
                    backup_file=backup_file
                )
                self.changes.append(change)
        
        if not new_entries:
            logger.debug("No new rc.conf entries needed")
            return True
        
        return self.write_config_file(self.rc_conf, existing_config, new_entries)
    
    def generate_loader_conf_entries(self, successful_drivers: List[str], 
                                   firmware_installed: List[str]) -> List[SystemConfigEntry]:
        """Generate loader.conf entries for successfully loaded drivers."""
        entries = []
        
        # Add drivers that should load at boot
        boot_drivers = {
            "if_em", "if_igb", "if_ix", "if_re", "if_bge", "if_alc",  # Ethernet
            "if_axge", "if_axe", "if_ure", "if_cdce",                # USB Ethernet
            "if_iwm", "if_iwlwifi", "if_ath", "if_ath10k", "if_ath11k",  # WiFi
            "if_rtwn", "if_rtw88", "if_rtw89", "if_bwi",             # WiFi continued
            "if_urtwn", "if_run", "if_rum", "if_ural"                # USB WiFi
        }
        
        for driver in successful_drivers:
            if driver in boot_drivers:
                # Add the _load="YES" entry
                entries.append(SystemConfigEntry(
                    file_path=str(self.loader_conf),
                    key=f"{driver}_load",
                    value="YES",
                    comment=f"Load {driver} network driver at boot"
                ))
                
                # Add the _name="/boot/modules/xxx.ko" entry
                entries.append(SystemConfigEntry(
                    file_path=str(self.loader_conf),
                    key=f"{driver}_name",
                    value=f"/boot/modules/{driver}.ko",
                    comment=f"Specify path for {driver} kernel module"
                ))
        
        # Add dependencies for modern WiFi drivers
        if any(d in successful_drivers for d in ["if_iwlwifi", "if_rtw88", "if_rtw89", "if_ath11k"]):
            entries.extend([
                SystemConfigEntry(
                    file_path=str(self.loader_conf),
                    key="linuxkpi_load",
                    value="YES",
                    comment="Linux KPI compatibility layer for modern WiFi drivers"
                ),
                SystemConfigEntry(
                    file_path=str(self.loader_conf),
                    key="lindebugfs_load", 
                    value="YES",
                    comment="Linux debugfs compatibility for WiFi drivers"
                )
            ])
        
        return entries
    
    def generate_rc_conf_entries(self, interfaces: List[NetworkInterface], 
                               enable_dhcp: bool = False) -> List[SystemConfigEntry]:
        """Generate rc.conf entries for network interfaces."""
        entries = []
        
        for interface in interfaces:
            if interface.interface_type == DeviceType.ETHERNET:
                # Enable interface
                entries.append(SystemConfigEntry(
                    file_path=str(self.rc_conf),
                    key=f"ifconfig_{interface.name}",
                    value="up" if not enable_dhcp else "DHCP",
                    comment=f"Enable {interface.name} ethernet interface"
                ))
                
                if enable_dhcp:
                    entries.append(SystemConfigEntry(
                        file_path=str(self.rc_conf),
                        key=f"ifconfig_{interface.name}",
                        value="DHCP",
                        comment=f"Configure {interface.name} for DHCP"
                    ))
            
            elif interface.interface_type == DeviceType.WIFI:
                # Create wlan interface
                wlan_name = f"wlan{interface.name[-1]}" if interface.name[-1].isdigit() else "wlan0"
                
                entries.extend([
                    SystemConfigEntry(
                        file_path=str(self.rc_conf),
                        key=f"wlans_{interface.name}",
                        value=wlan_name,
                        comment=f"Create {wlan_name} for {interface.name} WiFi interface"
                    ),
                    SystemConfigEntry(
                        file_path=str(self.rc_conf),
                        key=f"ifconfig_{wlan_name}",
                        value="WPA DHCP" if enable_dhcp else "up",
                        comment=f"Configure {wlan_name} for WPA and DHCP" if enable_dhcp else f"Enable {wlan_name}"
                    )
                ])
        
        return entries
    
    def get_changes_summary(self) -> Dict[str, Any]:
        """Get summary of all configuration changes made."""
        return {
            "total_changes": len(self.changes),
            "changes": [asdict(change) for change in self.changes],
            "files_modified": list(set(change.file_path for change in self.changes)),
            "backup_directory": str(self.backup_dir)
        }


class CommandRunner:
    """Enhanced command execution with caching and parallel execution."""
    
    def __init__(self, cache_enabled: bool = True):
        self.cache_enabled = cache_enabled
        self._cache: Dict[str, subprocess.CompletedProcess] = {}
    
    def run(self, cmd: str, check: bool = False, timeout: int = 30, cache: bool = True) -> subprocess.CompletedProcess:
        """Execute a shell command with caching and error handling."""
        cache_key = f"{cmd}:{check}:{timeout}" if cache and self.cache_enabled else None
        
        if cache_key and cache_key in self._cache:
            logger.debug(f"Using cached result for: {cmd}")
            return self._cache[cache_key]
        
        try:
            logger.debug(f"Executing: {cmd}")
            result = subprocess.run(
                cmd,
                shell=True,
                text=True,
                capture_output=True,
                check=check,
                timeout=timeout
            )
            
            if cache_key:
                self._cache[cache_key] = result
                
            if result.returncode != 0 and check:
                logger.warning(f"Command failed: {cmd}, stderr: {result.stderr}")
            return result
            
        except subprocess.TimeoutExpired:
            logger.error(f"Command timed out: {cmd}")
            raise
        except Exception as e:
            logger.error(f"Command execution failed: {cmd}, error: {e}")
            raise
    
    def run_parallel(self, commands: List[str], max_workers: int = 4) -> List[subprocess.CompletedProcess]:
        """Execute multiple commands in parallel."""
        results = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_cmd = {executor.submit(self.run, cmd): cmd for cmd in commands}
            
            for future in as_completed(future_to_cmd):
                cmd = future_to_cmd[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    logger.error(f"Parallel command failed: {cmd}, error: {e}")
                    # Create a dummy failed result
                    results.append(subprocess.CompletedProcess(
                        cmd, returncode=1, stdout="", stderr=str(e)
                    ))
        
        return results


class EnhancedDriverDatabase:
    """Advanced driver database with intelligent matching."""
    
    def __init__(self):
        self.rules = self._load_comprehensive_rules()
        self.blacklist = self._load_blacklist()
    
    def _load_comprehensive_rules(self) -> List[DriverRule]:
        """Load comprehensive driver rules with modern hardware support."""
        return [
            # === ETHERNET DRIVERS ===
            
            # Intel Ethernet - Gigabit
            DriverRule(
                kld="if_igb", vendor="0x8086",
                device_ids=["0x10a7", "0x10a9", "0x10d6", "0x10e6", "0x10e7", "0x10e8", 
                           "0x150a", "0x1518", "0x1521", "0x1522", "0x1523", "0x1524"],
                description="Intel 82575/82576/82580/I350/I354 Gigabit Ethernet",
                device_type=DeviceType.ETHERNET, load_order=10
            ),
            
            # Intel Ethernet - Legacy
            DriverRule(
                kld="if_em", vendor="0x8086",
                device_ids=["0x10d3", "0x1502", "0x1533", "0x150c", "0x10de", "0x10df", 
                           "0x10ef", "0x1049", "0x104a", "0x104b", "0x104c", "0x104d"],
                description="Intel 82571/82572/82573/82574/82583 Ethernet",
                device_type=DeviceType.ETHERNET, load_order=20
            ),
            
            # Intel Ethernet - 10 Gigabit
            DriverRule(
                kld="if_ix", vendor="0x8086",
                device_ids=["0x10fb", "0x10f8", "0x154d", "0x1528", "0x154a", "0x154f",
                           "0x1557", "0x1558", "0x1560", "0x1563", "0x15aa", "0x15ab"],
                description="Intel 82598/82599/X540/X550 10 Gigabit Ethernet",
                device_type=DeviceType.ETHERNET, load_order=15
            ),
            
            # Intel Ethernet - Modern (I219/I225/I226) with potential kernel module package
            DriverRule(
                kld="if_em", vendor="0x8086",
                device_ids=["0x156f", "0x1570", "0x15b7", "0x15b8", "0x15b9", "0x15bb",
                           "0x15bc", "0x15bd", "0x15be", "0x0d4e", "0x0d4f", "0x0d4c"],
                description="Intel I219/I225/I226 Gigabit Ethernet",
                device_type=DeviceType.ETHERNET, load_order=5
            ),
            
            # Realtek Ethernet
            DriverRule(
                kld="if_re", vendor="0x10ec",
                device_ids=["0x8168", "0x8169", "0x8136", "0x8167", "0x8161", "0x8162",
                           "0x8125", "0x3000", "0x8129", "0x8139"],
                description="Realtek RTL8139/8169/8168/8111/8125 Ethernet",
                device_type=DeviceType.ETHERNET, load_order=25
            ),
            
            # Broadcom Ethernet
            DriverRule(
                kld="if_bge", vendor="0x14e4",
                description="Broadcom BCM57xx Gigabit Ethernet",
                device_type=DeviceType.ETHERNET, load_order=30
            ),
            
            # Atheros/Qualcomm Ethernet
            DriverRule(
                kld="if_alc", vendor="0x1969",
                description="Atheros/Qualcomm AR813x/AR815x/AR816x/AR817x Ethernet",
                device_type=DeviceType.ETHERNET, load_order=35
            ),
            
            # === USB ETHERNET ===
            
            # ASIX USB 3.0 Gigabit
            DriverRule(
                kld="if_axge", vendor_ids=["0x0b95"], is_usb=True,
                description="ASIX AX88179/AX88178A USB 3.0 Gigabit Ethernet",
                device_type=DeviceType.USB_ETHERNET, load_order=40
            ),
            
            # ASIX USB 2.0
            DriverRule(
                kld="if_axe", vendor_ids=["0x0b95", "0x077b", "0x2001"], is_usb=True,
                description="ASIX AX88x72 USB 2.0 Ethernet",
                device_type=DeviceType.USB_ETHERNET, load_order=45
            ),
            
            # Realtek USB
            DriverRule(
                kld="if_ure", vendor_ids=["0x0bda", "0x0411"], is_usb=True,
                description="Realtek RTL8152/RTL8153 USB Ethernet",
                device_type=DeviceType.USB_ETHERNET, load_order=50
            ),
            
            # USB CDC Ethernet
            DriverRule(
                kld="if_cdce", device_class=USB_NETWORK_CLASS, is_usb=True,
                description="USB CDC Ethernet",
                device_type=DeviceType.USB_ETHERNET, load_order=55
            ),
            
            # === WIFI DRIVERS ===
            
            # Intel WiFi - Modern (AX/AC series)
            DriverRule(
                kld="if_iwlwifi", vendor="0x8086",
                device_ids=["0x2723", "0x2725", "0x271b", "0x271c", "0x2720", "0x30dc", 
                           "0x31dc", "0x9df0", "0x02f0", "0x06f0", "0x34f0", "0x43f0",
                           "0xa0f0", "0x2526", "0x51f0", "0x51f1", "0x54f0", "0x7af0"],
                firmware="wifi-firmware-iwlwifi-kmod",
                description="Intel WiFi 6E/6/AC (AX200/AX201/AX210/AC9560/AC9260/BE200)",
                device_type=DeviceType.WIFI, load_order=60,
                dependencies=["linuxkpi", "lindebugfs"]
            ),
            
            # Intel WiFi - AX210 specific (WiFi 6E)
            DriverRule(
                kld="if_iwlwifi", vendor="0x8086",
                device_ids=["0x2725", "0x51f0", "0x51f1", "0x54f0", "0x7af0"],
                firmware="wifi-firmware-iwlwifi-kmod-ax210",
                description="Intel WiFi 6E AX210 series",
                device_type=DeviceType.WIFI, load_order=58,
                dependencies=["linuxkpi", "lindebugfs"]
            ),
            
            # Intel WiFi - 22000 series (newer chipsets)
            DriverRule(
                kld="if_iwlwifi", vendor="0x8086", 
                device_ids=["0x2723", "0x271b", "0x271c", "0x30dc", "0x31dc", "0x43f0", "0xa0f0"],
                firmware="wifi-firmware-iwlwifi-kmod-22000",
                description="Intel WiFi 22000 series (AX200/AX201)",
                device_type=DeviceType.WIFI, load_order=59,
                dependencies=["linuxkpi", "lindebugfs"]
            ),
            
            # Intel WiFi - 9000 series
            DriverRule(
                kld="if_iwlwifi", vendor="0x8086",
                device_ids=["0x9df0", "0x02f0", "0x06f0", "0x34f0"],
                firmware="wifi-firmware-iwlwifi-kmod-9000", 
                description="Intel WiFi 9000 series (9560/9260)",
                device_type=DeviceType.WIFI, load_order=61,
                dependencies=["linuxkpi", "lindebugfs"]
            ),
            
            # Intel WiFi - Legacy (7000/8000 series for if_iwm)
            DriverRule(
                kld="if_iwm", vendor="0x8086",
                device_ids=["0x095a", "0x095b", "0x24f3", "0x24f4", "0x24f5", "0x24f6"],
                firmware="wifi-firmware-iwlwifi-kmod-7000",
                description="Intel WiFi 7000 series (7260/7265)",
                device_type=DeviceType.WIFI, load_order=65
            ),
            
            DriverRule(
                kld="if_iwm", vendor="0x8086",
                device_ids=["0x24fd", "0x24fb", "0x3165", "0x3166"],
                firmware="wifi-firmware-iwlwifi-kmod-8000",
                description="Intel WiFi 8000 series (8260/8265/3165)",
                device_type=DeviceType.WIFI, load_order=66
            ),
            
            # Qualcomm Atheros WiFi - WiFi 6E/7 (ath12k)
            DriverRule(
                kld="if_ath12k", vendor="0x17cb",
                device_ids=["0x1107", "0x1109"],
                firmware="wifi-firmware-ath12k-kmod",
                description="Qualcomm Atheros WiFi 6E/7 (WCN7850)",
                device_type=DeviceType.WIFI, load_order=68,
                dependencies=["linuxkpi"]
            ),
            
            # Qualcomm Atheros WiFi - WiFi 6E (ath11k)
            DriverRule(
                kld="if_ath11k", vendor="0x17cb",
                device_ids=["0x1101", "0x1103", "0x1104"],
                firmware="wifi-firmware-ath11k-kmod",
                description="Qualcomm Atheros WiFi 6E (QCA6390/QCA6490)",
                device_type=DeviceType.WIFI, load_order=70,
                dependencies=["linuxkpi"]
            ),
            
            # Qualcomm Atheros WiFi - AC series (ath10k) 
            DriverRule(
                kld="if_ath10k", vendor="0x168c",
                device_ids=["0x003c", "0x0041", "0x003e", "0x0040", "0x0046", "0x0056"],
                firmware="wifi-firmware-ath10k-kmod",
                description="Qualcomm Atheros 802.11ac (QCA988x/QCA99x0/QCA6174/QCA9377)",
                device_type=DeviceType.WIFI, load_order=75
            ),
            
            # Realtek WiFi - WiFi 6 (rtw89)
            DriverRule(
                kld="if_rtw89", vendor="0x10ec",
                device_ids=["0x8852", "0x8851", "0xc852", "0xc851"],
                firmware="wifi-firmware-rtw89-kmod",
                description="Realtek WiFi 6 (RTL8852AE/RTL8852BE/RTL8851B)",
                device_type=DeviceType.WIFI, load_order=85,
                dependencies=["linuxkpi"]
            ),
            
            # Realtek WiFi - WiFi 5 (rtw88)
            DriverRule(
                kld="if_rtw88", vendor="0x10ec",
                device_ids=["0x8822", "0x8821", "0xb822", "0xc822", "0x8723", "0xb723"],
                firmware="wifi-firmware-rtw88-kmod",
                description="Realtek WiFi 5 (RTL8822BE/RTL8822CE/RTL8723DE)",
                device_type=DeviceType.WIFI, load_order=90,
                dependencies=["linuxkpi"]
            ),
            
            # MediaTek WiFi (mt76)
            DriverRule(
                kld="if_mt76", vendor="0x14c3",
                device_ids=["0x7915", "0x7906", "0x7922", "0x7996"],
                firmware="wifi-firmware-mt76-kmod",
                description="MediaTek MT76xx WiFi 6/6E",
                device_type=DeviceType.WIFI, load_order=95,
                dependencies=["linuxkpi"]
            ),
            
            # Realtek WiFi - Legacy (native FreeBSD driver)
            DriverRule(
                kld="if_rtwn", vendor="0x10ec",
                device_ids=["0x8176", "0x8178", "0x8188", "0x8192"],
                description="Realtek 802.11n (RTL8188/RTL8192 series)",
                device_type=DeviceType.WIFI, load_order=95
            ),
            
            # Broadcom WiFi
            DriverRule(
                kld="if_bwi", vendor="0x14e4",
                device_ids=["0x4311", "0x4312", "0x4315", "0x4318", "0x4319"],
                description="Broadcom BCM43xx 802.11bg",
                device_type=DeviceType.WIFI, load_order=100
            ),
            
            # Atheros WiFi - Legacy (native FreeBSD driver)
            DriverRule(
                kld="if_ath", vendor="0x168c",
                description="Atheros 802.11abgn (AR5xxx/AR9xxx series)",
                device_type=DeviceType.WIFI, load_order=105
            ),
            
            # === USB WIFI ===
            
            # Realtek USB WiFi - Modern
            DriverRule(
                kld="if_urtwn", vendor_ids=["0x0bda", "0x2019", "0x20f4", "0x2001", "0x050d"],
                is_usb=True, firmware="wifi-firmware-rtw88-kmod",
                description="Realtek RTL8188/RTL8192/RTL8723 USB WiFi",
                device_type=DeviceType.USB_WIFI, load_order=110
            ),
            
            # MediaTek USB WiFi - MT7601U
            DriverRule(
                kld="if_mt7601u", vendor_ids=["0x148f", "0x0e8d"], 
                is_usb=True, firmware="wifi-firmware-mt7601u-kmod",
                description="MediaTek MT7601U USB WiFi",
                device_type=DeviceType.USB_WIFI, load_order=115
            ),
            
            # Ralink/MediaTek USB WiFi - Legacy
            DriverRule(
                kld="if_run", vendor_ids=["0x148f", "0x0df6", "0x0789", "0x083a", "0x2019"],
                is_usb=True, 
                description="Ralink/MediaTek RT2870/RT3070/RT5370 USB WiFi (legacy)",
                device_type=DeviceType.USB_WIFI, load_order=120
            ),
            
            # Legacy USB WiFi drivers (no firmware packages in new system)
            DriverRule(
                kld="if_rum", vendor_ids=["0x148f", "0x0b05", "0x050d", "0x0769", "0x0411"],
                is_usb=True,
                description="Ralink RT2501/RT2601 USB WiFi (legacy)",
                device_type=DeviceType.USB_WIFI, load_order=125
            ),
            
            DriverRule(
                kld="if_ural", vendor_ids=["0x148f", "0x0b05", "0x050d", "0x13b1", "0x0411"],
                is_usb=True,
                description="Ralink RT2500 USB WiFi (legacy)",
                device_type=DeviceType.USB_WIFI, load_order=130
            ),
        ]
    
    def _load_blacklist(self) -> Set[str]:
        """Load driver blacklist."""
        # Drivers known to cause conflicts or issues
        return {
            "if_iwn",  # Superseded by if_iwm
        }
    
    def match_device(self, device: NetworkDevice) -> Optional[DriverRule]:
        """Enhanced device matching with conflict detection."""
        matching_rules = []
        
        for rule in self.rules:
            if rule.kld in self.blacklist:
                continue
                
            if rule.is_usb != device.is_usb:
                continue
                
            # Check vendor match
            if rule.vendor and device.vendor != rule.vendor:
                continue
                
            # Check vendor list for USB devices
            if rule.vendor_ids and device.vendor not in rule.vendor_ids:
                continue
                
            # Check device ID list
            if rule.device_ids and device.device not in rule.device_ids:
                continue
                
            # Check device class
            if rule.device_class and device.device_class != rule.device_class:
                continue
                
            matching_rules.append(rule)
        
        if not matching_rules:
            return None
        
        # Return the rule with the highest priority (lowest load_order)
        return min(matching_rules, key=lambda r: r.load_order)
    
    def get_specific_firmware_package(self, device: NetworkDevice, rule: DriverRule) -> str:
        """Get device-specific firmware package if available."""
        if not rule.firmware:
            return None
            
        # Intel WiFi specific firmware based on device ID
        if rule.vendor == "0x8086" and "iwlwifi" in rule.firmware:
            device_firmware_map = {
                # AX210 series (WiFi 6E)
                "0x2725": "wifi-firmware-iwlwifi-kmod-ax210",
                "0x51f0": "wifi-firmware-iwlwifi-kmod-ax210", 
                "0x51f1": "wifi-firmware-iwlwifi-kmod-ax210",
                "0x54f0": "wifi-firmware-iwlwifi-kmod-ax210",
                "0x7af0": "wifi-firmware-iwlwifi-kmod-ax210",
                
                # 22000 series (AX200/AX201)
                "0x2723": "wifi-firmware-iwlwifi-kmod-22000",
                "0x271b": "wifi-firmware-iwlwifi-kmod-22000",
                "0x271c": "wifi-firmware-iwlwifi-kmod-22000", 
                "0x30dc": "wifi-firmware-iwlwifi-kmod-22000",
                "0x31dc": "wifi-firmware-iwlwifi-kmod-22000",
                "0x43f0": "wifi-firmware-iwlwifi-kmod-22000",
                "0xa0f0": "wifi-firmware-iwlwifi-kmod-22000",
                
                # 9000 series
                "0x9df0": "wifi-firmware-iwlwifi-kmod-9000",
                "0x02f0": "wifi-firmware-iwlwifi-kmod-9000",
                "0x06f0": "wifi-firmware-iwlwifi-kmod-9000",
                "0x34f0": "wifi-firmware-iwlwifi-kmod-9000",
                
                # 8000 series (for if_iwm)
                "0x24fd": "wifi-firmware-iwlwifi-kmod-8000",
                "0x24fb": "wifi-firmware-iwlwifi-kmod-8000",
                "0x3165": "wifi-firmware-iwlwifi-kmod-8000",
                "0x3166": "wifi-firmware-iwlwifi-kmod-8000",
                
                # 7000 series (for if_iwm)
                "0x095a": "wifi-firmware-iwlwifi-kmod-7000",
                "0x095b": "wifi-firmware-iwlwifi-kmod-7000",
                "0x24f3": "wifi-firmware-iwlwifi-kmod-7000",
                "0x24f4": "wifi-firmware-iwlwifi-kmod-7000",
                "0x24f5": "wifi-firmware-iwlwifi-kmod-7000",
                "0x24f6": "wifi-firmware-iwlwifi-kmod-7000",
            }
            
            specific_fw = device_firmware_map.get(device.device)
            if specific_fw:
                return specific_fw
        
        # Qualcomm Atheros specific firmware
        if rule.vendor == "0x168c" and "ath10k" in rule.firmware:
            device_firmware_map = {
                "0x003c": "wifi-firmware-ath10k-kmod-qca988x_hw20",
                "0x0041": "wifi-firmware-ath10k-kmod-qca6174_hw30", 
                "0x003e": "wifi-firmware-ath10k-kmod-qca6174_hw21",
                "0x0040": "wifi-firmware-ath10k-kmod-qca99x0_hw20",
                "0x0046": "wifi-firmware-ath10k-kmod-qca9377_hw10",
                "0x0056": "wifi-firmware-ath10k-kmod-qca9888_hw20",
            }
            
            specific_fw = device_firmware_map.get(device.device)
            if specific_fw:
                return specific_fw
        
        # Qualcomm Atheros ath11k specific firmware
        if rule.vendor == "0x17cb" and "ath11k" in rule.firmware:
            device_firmware_map = {
                "0x1101": "wifi-firmware-ath11k-kmod-qca6390_hw20",
                "0x1103": "wifi-firmware-ath11k-kmod-wcn6855_hw20",
                "0x1104": "wifi-firmware-ath11k-kmod-qcn9074_hw10",
            }
            
            specific_fw = device_firmware_map.get(device.device)
            if specific_fw:
                return specific_fw
        
        # Realtek specific firmware (rtw88)
        if rule.vendor == "0x10ec" and "rtw88" in rule.firmware:
            device_firmware_map = {
                "0x8822": "wifi-firmware-rtw88-kmod-rtw8822b",
                "0x8821": "wifi-firmware-rtw88-kmod-rtw8821c", 
                "0xb822": "wifi-firmware-rtw88-kmod-rtw8822b",
                "0xc822": "wifi-firmware-rtw88-kmod-rtw8822c",
                "0x8723": "wifi-firmware-rtw88-kmod-rtw8723d",
                "0xb723": "wifi-firmware-rtw88-kmod-rtw8703b",
            }
            
            specific_fw = device_firmware_map.get(device.device)
            if specific_fw:
                return specific_fw
        
        # Realtek specific firmware (rtw89)
        if rule.vendor == "0x10ec" and "rtw89" in rule.firmware:
            device_firmware_map = {
                "0x8852": "wifi-firmware-rtw89-kmod-rtw8852a",
                "0x8851": "wifi-firmware-rtw89-kmod-rtw8851b",
                "0xc852": "wifi-firmware-rtw89-kmod-rtw8852c", 
                "0xc851": "wifi-firmware-rtw89-kmod-rtw8852b",
            }
            
            specific_fw = device_firmware_map.get(device.device)
            if specific_fw:
                return specific_fw
        
        # Return the generic firmware package as fallback
        return rule.firmware
    
    def get_dependencies(self, rule: DriverRule) -> List[str]:
        """Get dependency chain for a driver."""
        deps = []
        for dep in rule.dependencies:
            deps.append(dep)
            # Could recursively find dependencies of dependencies here
        return deps
    
    def get_coverage_summary(self) -> Dict[str, List[str]]:
        """Get a summary of driver coverage by category."""
        ethernet_drivers = []
        wifi_drivers = []
        usb_ethernet = []
        usb_wifi = []
        
        for rule in self.rules:
            if rule.is_usb:
                if rule.device_type == DeviceType.USB_WIFI:
                    usb_wifi.append(f"{rule.kld}: {rule.description}")
                else:
                    usb_ethernet.append(f"{rule.kld}: {rule.description}")
            else:
                if rule.device_type == DeviceType.WIFI:
                    wifi_drivers.append(f"{rule.kld}: {rule.description}")
                else:
                    ethernet_drivers.append(f"{rule.kld}: {rule.description}")
        
        return {
            "ethernet_pci": ethernet_drivers,
            "wifi_pci": wifi_drivers,
            "ethernet_usb": usb_ethernet,
            "wifi_usb": usb_wifi
        }


class AdvancedNetworkManager:
    """Advanced network device discovery and management."""
    
    def __init__(self, enable_system_config: bool = False):
        self.cmd_runner = CommandRunner()
        self.driver_db = EnhancedDriverDatabase()
        self.loaded_modules: Set[str] = set()
        self.failed_modules: Set[str] = set()
        self.interface_cache: Dict[str, NetworkInterface] = {}
        self.system_config = SystemConfigManager() if enable_system_config else None
        
    def _detect_freebsd_version(self) -> str:
        """Detect FreeBSD version."""
        try:
            result = self.cmd_runner.run("uname -r")
            return result.stdout.strip()
        except Exception:
            return "unknown"
    
    def _enhanced_pci_discovery(self) -> List[NetworkDevice]:
        """Enhanced PCI device discovery with additional info."""
        devices = []
        try:
            # Get basic PCI info
            result = self.cmd_runner.run("pciconf -lv")
            
            for match in PCI_PATTERN.finditer(result.stdout):
                device_class = match.group("class").lower()
                if device_class.startswith(NETWORK_CLASS_PREFIX):
                    device = NetworkDevice(
                        vendor=f"0x{match.group('vendor')}",
                        device=f"0x{match.group('device')}",
                        device_class=f"0x{device_class}",
                        vendor_name=match.group("venname"),
                        device_name=match.group("devname"),
                        bus_info=match.group("tag"),
                        is_usb=False
                    )
                    
                    # Determine device type
                    device.device_type = self._classify_device(device)
                    
                    # Get additional PCI info
                    self._enhance_pci_device_info(device)
                    
                    devices.append(device)
                    logger.debug(f"Found PCI device: {device}")
        
        except Exception as e:
            logger.error(f"Failed to discover PCI devices: {e}")
        
        return devices
    
    def _enhanced_usb_discovery(self) -> List[NetworkDevice]:
        """Enhanced USB device discovery with better filtering."""
        devices = []
        try:
            result = self.cmd_runner.run("usbconfig dump_all_desc")
            
            for block in result.stdout.split("\n\n"):
                # Look for network-related devices
                if not any(pattern in block for pattern in ["bDeviceClass", "bInterfaceClass"]):
                    continue
                
                vendor_match = USB_VENDOR_PATTERN.search(block)
                product_match = USB_PRODUCT_PATTERN.search(block)
                
                if not (vendor_match and product_match):
                    continue
                
                # Check for network class at device or interface level
                device_class_match = USB_CLASS_PATTERN.search(block)
                interface_class_match = USB_INTERFACE_CLASS_PATTERN.search(block)
                
                is_network_device = False
                device_class = None
                
                if device_class_match:
                    device_class = device_class_match.group(1)
                    is_network_device = device_class == USB_NETWORK_CLASS
                
                if not is_network_device and interface_class_match:
                    device_class = interface_class_match.group(1)
                    is_network_device = device_class == USB_NETWORK_CLASS
                
                if is_network_device or self._is_known_usb_network_vendor(vendor_match.group(1)):
                    device = NetworkDevice(
                        vendor=f"0x{vendor_match.group(1)}",
                        device=f"0x{product_match.group(1)}",
                        device_class=device_class,
                        is_usb=True
                    )
                    
                    device.device_type = self._classify_device(device)
                    devices.append(device)
                    logger.debug(f"Found USB device: {device}")
        
        except Exception as e:
            logger.error(f"Failed to discover USB devices: {e}")
        
        return devices
    
    def _is_known_usb_network_vendor(self, vendor_id: str) -> bool:
        """Check if vendor is known to make USB network devices."""
        known_vendors = {
            "0b95",  # ASIX
            "0bda",  # Realtek
            "148f",  # Ralink
            "0df6",  # Sitecom
            "0789",  # Logitec
            "083a",  # Accton
            "2019",  # Planex
        }
        return vendor_id.lower() in known_vendors
    
    def _classify_device(self, device: NetworkDevice) -> DeviceType:
        """Classify device type based on vendor/device info."""
        # Check against known WiFi vendors/devices
        wifi_vendors = {"0x168c", "0x14e4"}  # Atheros, Broadcom
        intel_wifi_devices = {"0x095a", "0x095b", "0x3165", "0x3166", "0x24f3", "0x2723"}
        
        if device.vendor in wifi_vendors:
            return DeviceType.USB_WIFI if device.is_usb else DeviceType.WIFI
        
        if device.vendor == "0x8086" and device.device in intel_wifi_devices:
            return DeviceType.USB_WIFI if device.is_usb else DeviceType.WIFI
        
        # Default to ethernet
        return DeviceType.USB_ETHERNET if device.is_usb else DeviceType.ETHERNET
    
    def _enhance_pci_device_info(self, device: NetworkDevice):
        """Get additional PCI device information."""
        try:
            if device.bus_info:
                # Get detailed PCI config
                result = self.cmd_runner.run(f"pciconf -r {device.bus_info} 0x2c:0x30")
                if result.returncode == 0:
                    # Parse subsystem vendor/device (if needed)
                    pass
                
                # Check if driver is already loaded
                result = self.cmd_runner.run(f"pciconf -l | grep {device.bus_info}")
                if result.returncode == 0:
                    driver_match = re.search(r'^(\w+)@', result.stdout)
                    if driver_match:
                        device.driver_loaded = driver_match.group(1)
        
        except Exception as e:
            logger.debug(f"Failed to enhance PCI device info: {e}")
    
    def _load_module_with_dependencies(self, rule: DriverRule) -> bool:
        """Load a module with its dependencies."""
        if rule.kld in self.failed_modules:
            logger.debug(f"Skipping {rule.kld} - previously failed")
            return False
        
        try:
            # Load dependencies first
            for dep in self.driver_db.get_dependencies(rule):
                if not self._is_module_loaded(dep):
                    if not self._load_single_module(dep):
                        logger.warning(f"Failed to load dependency {dep} for {rule.kld}")
            
            # Load the main module
            return self._load_single_module(rule.kld)
        
        except Exception as e:
            logger.error(f"Error loading module {rule.kld}: {e}")
            self.failed_modules.add(rule.kld)
            return False
    
    def _is_module_loaded(self, module: str) -> bool:
        """Check if a kernel module is loaded."""
        try:
            result = self.cmd_runner.run(f"kldstat -n {module}")
            return module in result.stdout
        except Exception:
            return False
    
    def _load_single_module(self, module: str) -> bool:
        """Load a single kernel module."""
        if self._is_module_loaded(module):
            logger.debug(f"Module {module} already loaded")
            return True
        
        try:
            result = self.cmd_runner.run(f"kldload {module}", timeout=DRIVER_LOAD_TIMEOUT)
            success = result.returncode == 0
            
            if success:
                self.loaded_modules.add(module)
                logger.info(f"Successfully loaded module: {module}")
                # Wait for device to stabilize
                time.sleep(1)
            else:
                logger.warning(f"Failed to load module {module}: {result.stderr}")
                self.failed_modules.add(module)
            
            return success
        
        except Exception as e:
            logger.error(f"Error loading module {module}: {e}")
            self.failed_modules.add(module)
            return False
    
    def _install_firmware_package(self, package: str) -> bool:
        """Install firmware package with retry logic."""
        try:
            # Check if already installed
            check_result = self.cmd_runner.run(f"pkg info {package}")
            if check_result.returncode == 0:
                logger.debug(f"Firmware {package} already installed")
                return True
            
            # Try to install
            result = self.cmd_runner.run(f"pkg install -y {package}", timeout=120)
            
            if result.returncode == 0:
                logger.info(f"Successfully installed firmware: {package}")
                return True
            else:
                logger.warning(f"Failed to install firmware {package}: {result.stderr}")
                return False
        
        except Exception as e:
            logger.warning(f"Error installing firmware {package}: {e}")
            return False
    
    def _discover_interfaces_comprehensive(self) -> List[NetworkInterface]:
        """Comprehensive interface discovery with full details."""
        interfaces = []
        
        try:
            # Get all interfaces
            result = self.cmd_runner.run("ifconfig -l")
            interface_names = result.stdout.strip().split()
            
            # Process interfaces in parallel for speed
            interface_commands = [f"ifconfig {name}" for name in interface_names]
            interface_results = self.cmd_runner.run_parallel(interface_commands)
            
            for name, result in zip(interface_names, interface_results):
                if name.startswith("lo"):  # Skip loopback
                    continue
                
                if result.returncode != 0:
                    continue
                
                interface = self._parse_interface_details(name, result.stdout)
                if interface and interface.interface_type != DeviceType.UNKNOWN:
                    interfaces.append(interface)
                    self.interface_cache[name] = interface
        
        except Exception as e:
            logger.error(f"Failed to discover interfaces: {e}")
        
        return interfaces
    
    def _parse_interface_details(self, name: str, ifconfig_output: str) -> Optional[NetworkInterface]:
        """Parse detailed interface information from ifconfig output."""
        try:
            # Skip non-ethernet interfaces initially
            if "ether " not in ifconfig_output:
                return None
            
            # Basic info
            interface = NetworkInterface(name=name)
            
            # MAC address
            mac_match = re.search(r"ether ([a-f0-9:]{17})", ifconfig_output, re.IGNORECASE)
            if mac_match:
                interface.mac_address = mac_match.group(1)
            
            # Status
            if "status: active" in ifconfig_output:
                interface.status = InterfaceStatus.ACTIVE
            elif "status: no carrier" in ifconfig_output:
                interface.status = InterfaceStatus.NO_CARRIER
            elif re.search(r"flags=.*UP", ifconfig_output):
                interface.status = InterfaceStatus.UP
            else:
                interface.status = InterfaceStatus.DOWN
            
            # MTU
            mtu_match = re.search(r"mtu (\d+)", ifconfig_output)
            if mtu_match:
                interface.mtu = int(mtu_match.group(1))
            
            # IP addresses
            ip_matches = re.findall(r"inet (\d+\.\d+\.\d+\.\d+)", ifconfig_output)
            interface.ip_addresses = ip_matches
            
            # Media/speed info
            media_match = re.search(r"media: .*?<(.+?)>", ifconfig_output)
            if media_match:
                media_info = media_match.group(1)
                if "full-duplex" in media_info:
                    interface.duplex = "full"
                elif "half-duplex" in media_info:
                    interface.duplex = "half"
                
                # Extract speed
                speed_match = re.search(r"(\d+)(?:baseT|G)", media_info)
                if speed_match:
                    speed_val = int(speed_match.group(1))
                    if "G" in media_info or speed_val >= 1000:
                        interface.speed = f"{speed_val}G" if "G" in media_info else f"{speed_val//1000}G"
                    else:
                        interface.speed = f"{speed_val}M"
            
            # Determine interface type
            if name.startswith("wlan") or "wireless" in ifconfig_output.lower():
                interface.interface_type = DeviceType.WIFI
                interface.wireless_info = self._get_wireless_info(name)
            else:
                interface.interface_type = DeviceType.ETHERNET
            
            # Capabilities
            caps_match = re.search(r"options=\w+<(.+?)>", ifconfig_output)
            if caps_match:
                interface.capabilities = [cap.strip() for cap in caps_match.group(1).split(",")]
            
            # Statistics (basic)
            interface.statistics = self._get_interface_statistics(name)
            
            return interface
        
        except Exception as e:
            logger.debug(f"Failed to parse interface {name}: {e}")
            return None
    
    def _get_wireless_info(self, interface: str) -> Optional[Dict[str, Any]]:
        """Get wireless-specific information."""
        try:
            result = self.cmd_runner.run(f"ifconfig {interface}")
            if result.returncode != 0:
                return None
            
            wireless_info = {}
            
            # Extract SSID
            ssid_match = re.search(r'ssid "([^"]*)"', result.stdout)
            if ssid_match:
                wireless_info["ssid"] = ssid_match.group(1)
            
            # Extract channel
            channel_match = re.search(r"channel (\d+)", result.stdout)
            if channel_match:
                wireless_info["channel"] = int(channel_match.group(1))
            
            # Extract signal strength
            signal_match = re.search(r"signal (-?\d+)dBm", result.stdout)
            if signal_match:
                wireless_info["signal_dbm"] = int(signal_match.group(1))
            
            return wireless_info if wireless_info else None
        
        except Exception:
            return None
    
    def _get_interface_statistics(self, interface: str) -> Optional[Dict[str, int]]:
        """Get interface statistics."""
        try:
            result = self.cmd_runner.run(f"netstat -I {interface} -b")
            if result.returncode != 0:
                return None
            
            lines = result.stdout.strip().split('\n')
            if len(lines) >= 2:
                # Parse the statistics line
                fields = lines[1].split()
                if len(fields) >= 10:
                    return {
                        "bytes_in": int(fields[6]),
                        "bytes_out": int(fields[9]),
                        "packets_in": int(fields[4]),
                        "packets_out": int(fields[7]),
                        "errors_in": int(fields[5]),
                        "errors_out": int(fields[8])
                    }
        
        except Exception:
            pass
        
        return None
    
    def scan_wireless_networks(self, interface: str) -> List[WirelessNetwork]:
        """Scan for available wireless networks."""
        networks = []
        
        try:
            result = self.cmd_runner.run(f"ifconfig {interface} scan", timeout=30)
            if result.returncode != 0:
                return networks
            
            for line in result.stdout.split('\n')[1:]:  # Skip header
                if not line.strip():
                    continue
                
                # Parse scan results (simplified)
                parts = line.split()
                if len(parts) >= 6:
                    ssid = parts[0]
                    bssid = parts[1]
                    try:
                        signal = int(parts[2])
                        channel = int(parts[3])
                        encryption = " ".join(parts[5:]) if len(parts) > 5 else "Open"
                        
                        network = WirelessNetwork(
                            ssid=ssid,
                            bssid=bssid,
                            signal_strength=signal,
                            frequency=f"Channel {channel}",
                            encryption=encryption,
                            channel=channel
                        )
                        networks.append(network)
                    except (ValueError, IndexError):
                        continue
        
        except Exception as e:
            logger.error(f"Failed to scan wireless networks on {interface}: {e}")
        
        return networks
    
    def configure_interface_dhcp(self, interface: str) -> bool:
        """Configure interface for DHCP."""
        try:
            # Bring interface up
            self.cmd_runner.run(f"ifconfig {interface} up")
            
            # Start DHCP client
            result = self.cmd_runner.run(f"dhclient {interface}", timeout=30)
            
            if result.returncode == 0:
                logger.info(f"Successfully configured {interface} for DHCP")
                return True
            else:
                logger.warning(f"DHCP configuration failed for {interface}")
                return False
        
        except Exception as e:
            logger.error(f"Error configuring DHCP for {interface}: {e}")
            return False
    
    def run_comprehensive_discovery(self, enable_boot_config: bool = False, 
                                   enable_dhcp_config: bool = False) -> Dict[str, Any]:
        """Run comprehensive network discovery and configuration."""
        logger.info("Starting comprehensive network discovery...")
        
        start_time = time.time()
        
        # Step 1: Run devmatch
        self._run_devmatch()
        
        # Step 2: Parallel device discovery
        logger.info("Discovering network devices...")
        with ThreadPoolExecutor(max_workers=2) as executor:
            pci_future = executor.submit(self._enhanced_pci_discovery)
            usb_future = executor.submit(self._enhanced_usb_discovery)
            
            pci_devices = pci_future.result()
            usb_devices = usb_future.result()
        
        all_devices = pci_devices + usb_devices
        logger.info(f"Found {len(all_devices)} network devices")
        
        # Step 3: Load drivers intelligently
        driver_results = self._load_drivers_for_devices(all_devices)
        
        # Step 4: Wait for interfaces to appear
        time.sleep(INTERFACE_PROBE_DELAY)
        
        # Step 5: Discover interfaces
        logger.info("Discovering network interfaces...")
        interfaces = self._discover_interfaces_comprehensive()
        
        # Step 6: Configure system files if requested
        config_changes = {}
        if self.system_config and (enable_boot_config or enable_dhcp_config):
            logger.info("Configuring system files...")
            config_changes = self._configure_system_files(
                driver_results, interfaces, enable_boot_config, enable_dhcp_config
            )
        
        # Step 7: Prepare comprehensive results
        discovery_time = time.time() - start_time
        
        result = {
            "discovery_info": {
                "timestamp": time.time(),
                "discovery_time_seconds": round(discovery_time, 2),
                "freebsd_version": self._detect_freebsd_version(),
                "netpilot_version": NETPILOT_VERSION,
                "total_devices_found": len(all_devices),
                "total_interfaces_found": len(interfaces)
            },
            "devices": [asdict(device) for device in all_devices],
            "interfaces": [asdict(interface) for interface in interfaces],
            "driver_results": driver_results,
            "statistics": {
                "pci_devices": len(pci_devices),
                "usb_devices": len(usb_devices),
                "ethernet_interfaces": len([i for i in interfaces if i.interface_type == DeviceType.ETHERNET]),
                "wifi_interfaces": len([i for i in interfaces if i.interface_type == DeviceType.WIFI]),
                "active_interfaces": len([i for i in interfaces if i.status == InterfaceStatus.ACTIVE]),
                "modules_loaded": len(self.loaded_modules),
                "modules_failed": len(self.failed_modules)
            }
        }
        
        # Add configuration changes if any were made
        if config_changes:
            result["system_configuration"] = config_changes
        
        logger.info(f"Discovery completed in {discovery_time:.2f}s: {result['statistics']}")
        return result
    
    def _configure_system_files(self, driver_results: Dict[str, Any], 
                              interfaces: List[NetworkInterface],
                              enable_boot_config: bool, 
                              enable_dhcp_config: bool) -> Dict[str, Any]:
        """Configure system files based on discovery results."""
        changes = {}
        
        try:
            # Configure loader.conf for boot-time driver loading
            if enable_boot_config:
                successful_drivers = [r["driver"] for r in driver_results.get("successful", [])]
                firmware_installed = [r["firmware"] for r in driver_results.get("firmware_installed", [])]
                
                loader_entries = self.system_config.generate_loader_conf_entries(
                    successful_drivers, firmware_installed
                )
                
                if loader_entries:
                    success = self.system_config.add_loader_conf_entries(loader_entries)
                    changes["loader_conf"] = {
                        "success": success,
                        "entries_added": len(loader_entries),
                        "entries": [{"key": e.key, "value": e.value, "comment": e.comment} for e in loader_entries]
                    }
                    logger.info(f"Added {len(loader_entries)} entries to /boot/loader.conf")
            
            # Configure rc.conf for interface startup
            if enable_dhcp_config:
                rc_entries = self.system_config.generate_rc_conf_entries(interfaces, enable_dhcp=True)
                
                if rc_entries:
                    success = self.system_config.add_rc_conf_entries(rc_entries)
                    changes["rc_conf"] = {
                        "success": success,
                        "entries_added": len(rc_entries),
                        "entries": [{"key": e.key, "value": e.value, "comment": e.comment} for e in rc_entries]
                    }
                    logger.info(f"Added {len(rc_entries)} entries to /etc/rc.conf")
            
            # Add summary of all changes
            if self.system_config.changes:
                changes["summary"] = self.system_config.get_changes_summary()
                
        except Exception as e:
            logger.error(f"Failed to configure system files: {e}")
            changes["error"] = str(e)
        
        return changes
    
    def create_wlan_interfaces(self, wifi_interfaces: List[NetworkInterface]) -> List[str]:
        """Create wlan interfaces for WiFi devices."""
        created_interfaces = []
        
        for interface in wifi_interfaces:
            if interface.interface_type == DeviceType.WIFI:
                wlan_name = f"wlan{len(created_interfaces)}"
                
                try:
                    # Create wlan interface
                    result = self.cmd_runner.run(f"ifconfig {wlan_name} create wlandev {interface.name}")
                    
                    if result.returncode == 0:
                        created_interfaces.append(wlan_name)
                        logger.info(f"Created {wlan_name} for {interface.name}")
                    else:
                        logger.warning(f"Failed to create {wlan_name} for {interface.name}")
                        
                except Exception as e:
                    logger.error(f"Error creating wlan interface for {interface.name}: {e}")
        
        return created_interfaces
    
    def _load_drivers_for_devices(self, devices: List[NetworkDevice]) -> Dict[str, Any]:
        """Load drivers for discovered devices with intelligence."""
        results = {
            "successful": [],
            "failed": [],
            "firmware_installed": [],
            "conflicts": []
        }
        
        # Sort devices by priority (ethernet first, then wifi)
        ethernet_devices = [d for d in devices if d.device_type in [DeviceType.ETHERNET, DeviceType.USB_ETHERNET]]
        wifi_devices = [d for d in devices if d.device_type in [DeviceType.WIFI, DeviceType.USB_WIFI]]
        
        # Load ethernet drivers first
        for device in ethernet_devices:
            self._load_driver_for_device(device, results)
        
        # Then load wifi drivers
        for device in wifi_devices:
            self._load_driver_for_device(device, results)
        
        return results
    
    def _load_driver_for_device(self, device: NetworkDevice, results: Dict[str, Any]):
        """Load driver for a specific device."""
        rule = self.driver_db.match_device(device)
        if not rule:
            logger.debug(f"No driver rule found for {device.vendor}:{device.device}")
            return
        
        device_desc = f"{device.vendor_name or 'Unknown'} {device.device_name or device.vendor}"
        logger.info(f"Loading driver {rule.kld} for {device_desc}")
        
        if self._load_module_with_dependencies(rule):
            results["successful"].append({
                "device": device_desc,
                "driver": rule.kld,
                "device_id": f"{device.vendor}:{device.device}"
            })
            
            # Install firmware if needed - use device-specific firmware
            if rule.firmware:
                specific_firmware = self.driver_db.get_specific_firmware_package(device, rule)
                if self._install_firmware_package(specific_firmware):
                    results["firmware_installed"].append({
                        "device": device_desc,
                        "firmware": specific_firmware
                    })
                # Fallback to generic firmware if specific fails
                elif specific_firmware != rule.firmware and self._install_firmware_package(rule.firmware):
                    results["firmware_installed"].append({
                        "device": device_desc,
                        "firmware": rule.firmware
                    })
        else:
            results["failed"].append({
                "device": device_desc,
                "driver": rule.kld,
                "device_id": f"{device.vendor}:{device.device}"
            })
    
    def _run_devmatch(self):
        """Run FreeBSD's devmatch with enhanced error handling."""
        try:
            logger.debug("Running devmatch service...")
            self.cmd_runner.run("devmatch -p", timeout=30)
            self.cmd_runner.run("/etc/rc.d/devmatch onestart", timeout=30)
        except Exception as e:
            logger.debug(f"Devmatch execution failed: {e}")


def print_banner():
    """Print simple NetPilot banner."""
    print(f"\n🌐 NetPilot v{NETPILOT_VERSION}")
    print("Advanced Network Discovery & Management for GhostBSD/FreeBSD")
    print("=" * 60)


def main():
    """Enhanced main function with comprehensive options."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="NetPilot - Advanced Network Device Discovery and Management for GhostBSD/FreeBSD",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                          # Basic discovery with auto-driver loading
  %(prog)s -v                       # Verbose discovery output
  %(prog)s --configure-dhcp         # Auto-configure DHCP on active interfaces
  %(prog)s --scan-wifi              # Scan for WiFi networks on available interfaces
  %(prog)s --show-coverage          # Show supported hardware database
  %(prog)s --json-output            # Machine-readable JSON output

System Configuration:
  %(prog)s --configure-boot         # Add drivers to /boot/loader.conf
  %(prog)s --configure-startup      # Add interfaces to /etc/rc.conf
  %(prog)s --create-wlan            # Create wlan interfaces for WiFi
  %(prog)s --show-config-changes    # Preview configuration changes

Complete Setup:
  sudo %(prog)s --configure-boot --configure-startup --configure-dhcp --create-wlan -v
        """
    )
    
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable detailed logging and progress information")
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress non-error output (for scripting)")
    parser.add_argument("--json-output", action="store_true", help="Machine-readable JSON output for automation")
    parser.add_argument("--show-coverage", action="store_true", help="Show supported drivers and hardware")
    parser.add_argument("--configure-dhcp", action="store_true", help="Auto-configure DHCP on discovered interfaces")
    parser.add_argument("--scan-wifi", action="store_true", help="Scan for WiFi networks")
    parser.add_argument("--interface", help="Target specific interface for operations")
    parser.add_argument("--no-driver-loading", action="store_true", help="Discovery only, skip driver loading")
    parser.add_argument("--retry-failed", action="store_true", help="Retry previously failed modules")
    parser.add_argument("--configure-boot", action="store_true", help="Add drivers to /boot/loader.conf for boot-time loading")
    parser.add_argument("--configure-startup", action="store_true", help="Add interfaces to /etc/rc.conf for automatic startup")
    parser.add_argument("--create-wlan", action="store_true", help="Create wlan interfaces for WiFi devices")
    parser.add_argument("--backup-configs", action="store_true", help="Backup configuration files before modification")
    parser.add_argument("--show-config-changes", action="store_true", help="Show what configuration changes would be made")
    parser.add_argument("--version", action="version", version=f"NetPilot {NETPILOT_VERSION}")
    
    args = parser.parse_args()
    
    # Show banner unless quiet or JSON output
    if not args.quiet and not args.json_output:
        print_banner()
    
    # Configure logging
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    elif args.quiet:
        logging.getLogger().setLevel(logging.ERROR)
    
    try:
        # Determine if system configuration is needed
        enable_system_config = any([
            args.configure_boot, 
            args.configure_startup, 
            args.show_config_changes,
            args.backup_configs
        ])
        
        manager = AdvancedNetworkManager(enable_system_config=enable_system_config)
        
        # Show coverage if requested
        if args.show_coverage:
            if not args.json_output:
                print("🌐 NetPilot Hardware Support Database\n")
            
            coverage = manager.driver_db.get_coverage_summary()
            
            if args.json_output:
                print(json.dumps(coverage, indent=2))
                return 0
            
            coverage_data = {
                "Ethernet (PCI/PCIe)": coverage["ethernet_pci"],
                "WiFi (PCI/PCIe)": coverage["wifi_pci"], 
                "USB Ethernet": coverage["ethernet_usb"],
                "USB WiFi": coverage["wifi_usb"]
            }
            
            for category, drivers in coverage_data.items():
                print(f"=== {category} ===")
                for driver in sorted(drivers):
                    print(f"  • {driver}")
                print()
            
            firmware_packages = sorted({r.firmware for r in manager.driver_db.rules if r.firmware})
            print("=== Firmware Packages ===")
            for fw in firmware_packages:
                print(f"  • {fw}")
            
            return 0
        
        # Main discovery
        if args.no_driver_loading:
            # Discovery only mode
            devices = manager._enhanced_pci_discovery() + manager._enhanced_usb_discovery()
            interfaces = manager._discover_interfaces_comprehensive()
            
            result = {
                "devices": [asdict(d) for d in devices],
                "interfaces": [asdict(i) for i in interfaces],
                "driver_loading": "disabled"
            }
        else:
            # Full discovery with optional system configuration
            enable_boot_config = args.configure_boot
            enable_dhcp_config = args.configure_startup and args.configure_dhcp
            
            result = manager.run_comprehensive_discovery(
                enable_boot_config=enable_boot_config,
                enable_dhcp_config=enable_dhcp_config
            )
        
        # Create wlan interfaces if requested
        if args.create_wlan and not args.no_driver_loading:
            wifi_interfaces = [
                NetworkInterface(**i) for i in result.get("interfaces", [])
                if i.get("interface_type") == DeviceType.WIFI.value
            ]
            
            if wifi_interfaces:
                created_wlans = manager.create_wlan_interfaces(wifi_interfaces)
                result["wlan_interfaces_created"] = created_wlans
                
                if not args.json_output:
                    if created_wlans:
                        print(f"📡 Created wlan interfaces: {', '.join(created_wlans)}")
                    else:
                        print("ℹ️  No wlan interfaces were created")
        
        # Show configuration changes preview
        if args.show_config_changes and manager.system_config:
            if result.get("driver_results"):
                interfaces_list = [NetworkInterface(**i) for i in result.get("interfaces", [])]
                successful_drivers = [r["driver"] for r in result["driver_results"].get("successful", [])]
                firmware_installed = [r["firmware"] for r in result["driver_results"].get("firmware_installed", [])]
                
                # Generate what would be added
                loader_entries = manager.system_config.generate_loader_conf_entries(
                    successful_drivers, firmware_installed
                )
                rc_entries = manager.system_config.generate_rc_conf_entries(
                    interfaces_list, enable_dhcp=args.configure_dhcp
                )
                
                preview = {
                    "loader_conf_entries": [{"key": e.key, "value": e.value, "comment": e.comment} for e in loader_entries],
                    "rc_conf_entries": [{"key": e.key, "value": e.value, "comment": e.comment} for e in rc_entries]
                }
                
                if args.json_output:
                    print(json.dumps(preview, indent=2))
                    return 0
                else:
                    print("\n📝 Configuration Changes Preview:")
                    if loader_entries:
                        print(f"\n/boot/loader.conf entries ({len(loader_entries)}):")
                        for entry in loader_entries:
                            print(f"  + {entry.key}=\"{entry.value}\"  # {entry.comment}")
                    
                    if rc_entries:
                        print(f"\n/etc/rc.conf entries ({len(rc_entries)}):")
                        for entry in rc_entries:
                            print(f"  + {entry.key}=\"{entry.value}\"  # {entry.comment}")
                    
                    print(f"\nTo apply these changes, run with --configure-boot and/or --configure-startup")
                    return 0
        
        # WiFi scanning
        if args.scan_wifi:
            wifi_interfaces = [i for i in result.get("interfaces", []) 
                             if i.get("interface_type") == DeviceType.WIFI.value]
            
            if wifi_interfaces:
                for wifi_if in wifi_interfaces:
                    networks = manager.scan_wireless_networks(wifi_if["name"])
                    wifi_if["available_networks"] = [asdict(n) for n in networks]
            elif not args.json_output:
                print("ℹ️  No WiFi interfaces found for scanning")
        
        # DHCP configuration (runtime)
        if args.configure_dhcp and not args.configure_startup:
            ethernet_interfaces = [i for i in result.get("interfaces", [])
                                 if i.get("interface_type") == DeviceType.ETHERNET.value]
            
            dhcp_results = []
            for eth_if in ethernet_interfaces:
                if args.interface and eth_if["name"] != args.interface:
                    continue
                
                success = manager.configure_interface_dhcp(eth_if["name"])
                dhcp_results.append({"interface": eth_if["name"], "success": success})
            
            result["dhcp_configuration"] = dhcp_results
        
        # Output results
        if args.json_output:
            print(json.dumps(result, indent=2, default=str))
        else:
            # Human-readable output
            stats = result.get("statistics", {})
            discovery_info = result.get("discovery_info", {})
            
            print(f"\n🌐 NetPilot Discovery Results")
            print(f"   Discovery time: {discovery_info.get('discovery_time_seconds', 0):.2f}s")
            print(f"   FreeBSD version: {discovery_info.get('freebsd_version', 'unknown')}")
            print(f"   Total devices: {stats.get('pci_devices', 0)} PCI + {stats.get('usb_devices', 0)} USB")
            print(f"   Interfaces: {stats.get('ethernet_interfaces', 0)} Ethernet + {stats.get('wifi_interfaces', 0)} WiFi")
            print(f"   Active interfaces: {stats.get('active_interfaces', 0)}")
            print(f"   Modules loaded: {stats.get('modules_loaded', 0)} (failed: {stats.get('modules_failed', 0)})")
            
            # Show interfaces
            interfaces = result.get("interfaces", [])
            if interfaces:
                print(f"\n📡 Network Interfaces:")
                for interface in interfaces:
                    status_icon = "🟢" if interface["status"] == "active" else "🔴"
                    type_icon = "📡" if interface["interface_type"] == "wifi" else "🔌"
                    speed_info = f" ({interface.get('speed', 'unknown')})" if interface.get('speed') else ""
                    
                    print(f"   {status_icon} {type_icon} {interface['name']}: {interface['status']}{speed_info}")
                    
                    if interface.get("mac_address"):
                        print(f"       MAC: {interface['mac_address']}")
                    
                    if interface.get("ip_addresses"):
                        print(f"       IPs: {', '.join(interface['ip_addresses'])}")
                    
                    if interface.get("wireless_info"):
                        wi = interface["wireless_info"]
                        if wi.get("ssid"):
                            print(f"       SSID: {wi['ssid']} (Ch {wi.get('channel', '?')})")
                    
                    if interface.get("available_networks"):
                        print(f"       Available networks: {len(interface['available_networks'])}")
            
            # Show driver results
            driver_results = result.get("driver_results", {})
            if driver_results.get("successful"):
                print(f"\n✅ Successfully loaded drivers:")
                for success in driver_results["successful"]:
                    print(f"   • {success['driver']} for {success['device']}")
            
            if driver_results.get("firmware_installed"):
                print(f"\n📦 Firmware installed:")
                for fw in driver_results["firmware_installed"]:
                    print(f"   • {fw['firmware']} for {fw['device']}")
            
            if driver_results.get("failed"):
                print(f"\n❌ Failed to load drivers:")
                for failure in driver_results["failed"]:
                    print(f"   • {failure['driver']} for {failure['device']}")
            
            # Show DHCP results
            dhcp_results = result.get("dhcp_configuration", [])
            if dhcp_results:
                print(f"\n🌍 DHCP Configuration:")
                for dhcp in dhcp_results:
                    status = "✅ Success" if dhcp["success"] else "❌ Failed"
                    print(f"   • {dhcp['interface']}: {status}")
            
            # Show system configuration results
            system_config = result.get("system_configuration", {})
            if system_config:
                print(f"\n⚙️  System Configuration:")
                
                loader_conf = system_config.get("loader_conf", {})
                if loader_conf:
                    status = "✅ Success" if loader_conf["success"] else "❌ Failed"
                    print(f"   • /boot/loader.conf: {status} ({loader_conf.get('entries_added', 0)} entries)")
                
                rc_conf = system_config.get("rc_conf", {})
                if rc_conf:
                    status = "✅ Success" if rc_conf["success"] else "❌ Failed"
                    print(f"   • /etc/rc.conf: {status} ({rc_conf.get('entries_added', 0)} entries)")
                
                summary = system_config.get("summary", {})
                if summary and summary.get("total_changes", 0) > 0:
                    print(f"   • Total changes: {summary['total_changes']}")
                    print(f"   • Backup directory: {summary['backup_directory']}")
            
            # Show created wlan interfaces
            wlan_created = result.get("wlan_interfaces_created", [])
            if wlan_created:
                print(f"\n📡 WiFi Interfaces Created:")
                for wlan in wlan_created:
                    print(f"   • {wlan}")
            
            # Show configuration advice
            if not args.no_driver_loading and not any([args.configure_boot, args.configure_startup]):
                has_drivers = bool(driver_results.get("successful"))
                has_interfaces = bool(interfaces)
                
                if has_drivers or has_interfaces:
                    print(f"\n💡 Configuration Recommendations:")
                    if has_drivers:
                        print(f"   • Run with --configure-boot to load drivers automatically at boot")
                    if has_interfaces:
                        print(f"   • Run with --configure-startup to enable interfaces at startup")
                    print(f"   • Use --show-config-changes to preview what would be configured")
        
        return 0
        
    except KeyboardInterrupt:
        logger.error("Operation cancelled by user")
        return 1
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
