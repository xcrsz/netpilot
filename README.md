# NetPilot

**Advanced Network Device Discovery and Automated System Configuration for FreeBSD/PGSD**

[![FreeBSD](https://img.shields.io/badge/FreeBSD-13%2B-red?logo=freebsd)](https://www.freebsd.org/)
[![PGSD](https://img.shields.io/badge/PGSD-0.0.1%2B-red?logo=pgsd)](https://www.pgsdf.org/)
[![Python](https://img.shields.io/badge/Python-3.7%2B-blue?logo=python)](https://python.org/)
[![License](https://img.shields.io/badge/License-BSD%202--Clause-green)](LICENSE)
[![Version](https://img.shields.io/badge/Version-0.0.4-brightgreen)](https://github.com/yourusername/netpilot)

NetPilot is a comprehensive network device discovery and automated system configuration tool specifically designed for FreeBSD and PGSD systems. It automatically detects network hardware, loads appropriate drivers, installs device-specific firmware, configures system files, and sets up network interfaces with **complete zero-touch automation**.

## Features

### **Intelligent Hardware Discovery**
- **Parallel device scanning** - PCI and USB devices discovered simultaneously
- **Modern hardware support** - WiFi 6E/7, latest Intel/Realtek/Qualcomm/MediaTek chipsets
- **Smart classification** - automatically distinguishes Ethernet vs WiFi devices
- **Comprehensive vendor database** - 60+ supported network device families

### **Automated Driver Management**
- **Dependency resolution** - automatically loads required kernel modules (linuxkpi, lindebugfs)
- **Intelligent load ordering** - Ethernet first, then WiFi for optimal setup
- **Conflict avoidance** - prevents loading incompatible drivers
- **Device-specific firmware** - installs exact firmware packages for each chipset

### **System Configuration Automation**
- **Boot-time driver loading** - automatically configures `/boot/loader.conf`
- **Interface startup configuration** - manages `/etc/rc.conf` entries
- **WiFi interface creation** - creates and configures wlan interfaces
- **DHCP auto-configuration** - sets up automatic network connectivity
- **Configuration preview** - see changes before applying them

### **Safety & Backup System**
- **Automatic backups** - timestamped backups of all modified files in `/var/backups/netpilot/`
- **Change tracking** - complete audit trail of all modifications
- **Rollback capability** - restore from backups if needed
- **Preview mode** - validate configuration changes before applying

### **Enterprise-Grade Diagnostics**
- **Performance timing** - sub-second discovery with detailed metrics
- **Comprehensive reporting** - JSON output for automation/scripting
- **Success tracking** - module load success/failure analytics
- **Hardware coverage reports** - see exactly what's supported

## Installation

### Prerequisites
- FreeBSD 13.0+ or PBSD
- Python 3.11+
- Root privileges (for driver loading and system configuration)

### Quick Install
```bash
# Clone the repository
git clone https://github.com/xcrsz/netpilot.git
cd netpilot

# Make executable
chmod +x netpilot.py

# Optional: Install system-wide
sudo cp netpilot.py /usr/local/bin/netpilot
```

### Package Dependencies
NetPilot automatically installs the correct firmware packages for your specific hardware:

**Modern WiFi Firmware Packages:**
```bash
# Intel WiFi firmware (device-specific)
wifi-firmware-iwlwifi-kmod-ax210    # WiFi 6E (AX210)
wifi-firmware-iwlwifi-kmod-22000    # WiFi 6 (AX200/AX201)  
wifi-firmware-iwlwifi-kmod-9000     # AC series (9560/9260)
wifi-firmware-iwlwifi-kmod-8000     # Legacy (8260/8265)
wifi-firmware-iwlwifi-kmod-7000     # Legacy (7260/7265)

# Qualcomm Atheros firmware (device-specific)
wifi-firmware-ath12k-kmod           # WiFi 6E/7 (WCN7850)
wifi-firmware-ath11k-kmod-qca6390_hw20  # WiFi 6E (QCA6390)
wifi-firmware-ath10k-kmod-qca988x_hw20  # WiFi AC (QCA988x)

# Realtek firmware (device-specific)  
wifi-firmware-rtw89-kmod-rtw8852a   # WiFi 6 (RTL8852A)
wifi-firmware-rtw88-kmod-rtw8822b   # WiFi 5 (RTL8822B)

# MediaTek firmware
wifi-firmware-mt76-kmod             # MT76xx series
wifi-firmware-mt7601u-kmod          # MT7601U USB
```

NetPilot automatically selects the most specific firmware package for your exact chipset, with intelligent fallbacks to generic packages when needed.

## Quick Start

### Zero-Touch System Setup
```bash
# Complete automated setup - discovers hardware, loads drivers, 
# configures boot files, creates interfaces, and enables DHCP
sudo ./netpilot.py --configure-boot --configure-startup --configure-dhcp --create-wlan -v

# Preview what would be configured (safe mode)
sudo ./netpilot.py --show-config-changes

# Basic discovery only
sudo ./netpilot.py
```

### Network Discovery & Configuration
```bash
# Discover devices and configure for automatic startup
sudo ./netpilot.py --configure-boot --configure-startup -v

# Runtime DHCP configuration (temporary)
sudo ./netpilot.py --configure-dhcp

# Scan for WiFi networks and create wlan interfaces  
sudo ./netpilot.py --scan-wifi --create-wlan
```

### System Integration
```bash
# Add drivers to /boot/loader.conf for boot-time loading
sudo ./netpilot.py --configure-boot

# Add interfaces to /etc/rc.conf for automatic startup
sudo ./netpilot.py --configure-startup --configure-dhcp

# Hardware support check
./netpilot.py --show-coverage
```

## Usage Examples

### Complete System Configuration
Perfect for new installations or system setup:
```bash
# Full zero-touch setup: discover, configure, and enable everything
sudo netpilot --configure-boot --configure-startup --configure-dhcp --create-wlan -v

# Preview all changes before applying (recommended first run)
sudo netpilot --show-config-changes
```

### Boot-Time Configuration
```bash
# Configure drivers to load automatically at boot
sudo netpilot --configure-boot

# What this adds to /boot/loader.conf:
# if_em_load="YES"              # Ethernet driver
# if_iwlwifi_load="YES"         # WiFi driver  
# linuxkpi_load="YES"           # Modern WiFi dependency
# lindebugfs_load="YES"         # WiFi debugging support
```

### Network Startup Configuration
```bash
# Configure interfaces to start automatically
sudo netpilot --configure-startup --configure-dhcp

# What this adds to /etc/rc.conf:
# ifconfig_em0="DHCP"           # Ethernet with DHCP
# wlans_iwm0="wlan0"            # Create wlan0 interface
# ifconfig_wlan0="WPA DHCP"     # WiFi with WPA and DHCP
```

### System Diagnostics
```bash
# Discovery without system modification (safe mode)
sudo netpilot --no-driver-loading

# Focus on specific interface
sudo netpilot --interface em0 --configure-dhcp

# Get detailed JSON report for automation
sudo netpilot --json-output > network-report.json
```

### WiFi Management
```bash
# Create wlan interfaces and scan for networks
sudo netpilot --create-wlan --scan-wifi

# Configure WiFi for automatic connection
sudo netpilot --configure-startup --create-wlan
```

### Integration with Scripts
```bash
#!/bin/sh
# Automated deployment script

echo "Configuring network hardware..."
if netpilot --configure-boot --configure-startup --quiet; then
    echo "✅ Network configured - reboot to activate"
    echo "📋 Review changes: /var/backups/netpilot/"
else
    echo "❌ Network configuration failed"
    exit 1
fi
```

## Command Reference

### Basic Options
| Option | Description |
|--------|-------------|
| `-v, --verbose` | Enable detailed logging and progress information |
| `-q, --quiet` | Suppress non-error output (for scripting) |
| `--json-output` | Machine-readable JSON output for automation |
| `--show-coverage` | Display supported hardware database |
| `--no-driver-loading` | Discovery only, skip driver loading (safe mode) |
| `--version` | Show NetPilot version information |

### System Configuration
| Option | Description |
|--------|-------------|
| `--configure-boot` | Add drivers to `/boot/loader.conf` for boot-time loading |
| `--configure-startup` | Add interfaces to `/etc/rc.conf` for automatic startup |
| `--show-config-changes` | Preview configuration changes without applying them |
| `--backup-configs` | Force creation of configuration file backups |

### Network Management  
| Option | Description |
|--------|-------------|
| `--configure-dhcp` | Auto-configure DHCP on discovered interfaces |
| `--scan-wifi` | Scan for available WiFi networks |
| `--create-wlan` | Create wlan interfaces for discovered WiFi devices |
| `--interface IFACE` | Target specific interface for operations |

### Advanced Options
| Option | Description |
|--------|-------------|
| `--retry-failed` | Retry previously failed module loads |

## Sample Output

### Complete System Configuration
```
NetPilot Discovery Results
   Discovery time: 3.21s
   FreeBSD version: 14.0-RELEASE
   Total devices: 2 PCI + 1 USB
   Interfaces: 1 Ethernet + 1 WiFi
   Active interfaces: 1
   Modules loaded: 4 (failed: 0)

Network Interfaces:
   🟢 🔌 em0: active (1G)
       MAC: 52:54:00:12:34:56
       IPs: 192.168.1.100

   🔴 📡 iwm0: inactive
       MAC: aa:bb:cc:dd:ee:ff

Successfully loaded drivers:
   • if_em for Intel Corporation 82574L Gigabit Ethernet
   • if_iwlwifi for Intel Corporation WiFi 6 AX210
   • linuxkpi for Linux KPI compatibility layer

Firmware installed:
   • wifi-firmware-iwlwifi-kmod-ax210 for Intel Corporation WiFi 6 AX210

System Configuration:
   • /boot/loader.conf: ✅ Success (4 entries)
   • /etc/rc.conf: ✅ Success (3 entries)
   • Total changes: 7
   • Backup directory: /var/backups/netpilot

WiFi Interfaces Created:
   • wlan0 (for iwm0)

💡 Reboot recommended to test automatic driver loading
```

### Configuration Preview Mode
```bash
sudo netpilot --show-config-changes
```
```
Configuration Changes Preview:

/boot/loader.conf entries (4):
  + if_em_load="YES"  # Load if_em network driver at boot
  + if_iwlwifi_load="YES"  # Load if_iwlwifi network driver at boot
  + linuxkpi_load="YES"  # Linux KPI compatibility layer for modern WiFi drivers
  + lindebugfs_load="YES"  # Linux debugfs compatibility for WiFi drivers

/etc/rc.conf entries (3):
  + ifconfig_em0="DHCP"  # Configure em0 for DHCP
  + wlans_iwm0="wlan0"  # Create wlan0 for iwm0 WiFi interface
  + ifconfig_wlan0="WPA DHCP"  # Configure wlan0 for WPA and DHCP

To apply these changes, run with --configure-boot and/or --configure-startup
```

### WiFi Network Scanning
```bash
sudo netpilot --scan-wifi --interface wlan0
```
```
Available WiFi Networks on wlan0:
   • MyNetwork-5G    | -45 dBm | Ch 36  | WPA2/WPA3
   • MyNetwork-2.4G  | -52 dBm | Ch 6   | WPA2  
   • Guest_Network   | -67 dBm | Ch 11  | Open
   • Neighbor_WiFi   | -78 dBm | Ch 1   | WPA2
```

## Hardware Support

NetPilot supports 60+ network device families with device-specific firmware:

### Ethernet Controllers
- **Intel**: 82571/82572/82573/82574/82575/82576/82580/I350/I354/I219/I225/I226
- **Realtek**: RTL8139/8169/8168/8111/8125 series
- **Broadcom**: BCM57xx Gigabit series
- **Qualcomm Atheros**: AR813x/AR815x/AR816x/AR817x series

### WiFi Controllers
- **Intel**: WiFi 6E/6/AC with device-specific firmware
  - AX210 series (WiFi 6E) → `wifi-firmware-iwlwifi-kmod-ax210`
  - AX200/AX201 (WiFi 6) → `wifi-firmware-iwlwifi-kmod-22000`
  - 9560/9260 (AC) → `wifi-firmware-iwlwifi-kmod-9000`
  - 8260/8265/3165 → `wifi-firmware-iwlwifi-kmod-8000`
  - 7260/7265 → `wifi-firmware-iwlwifi-kmod-7000`

- **Qualcomm Atheros**: Latest chipsets with targeted firmware
  - WCN7850 (WiFi 6E/7) → `wifi-firmware-ath12k-kmod`
  - QCA6390/QCA6490 (WiFi 6E) → `wifi-firmware-ath11k-kmod-qca6390_hw20`
  - QCA988x/QCA99x0 (802.11ac) → `wifi-firmware-ath10k-kmod-qca988x_hw20`
  - Legacy AR5xxx/AR9xxx → Native FreeBSD driver (no firmware)

- **Realtek**: Modern WiFi 6/5 with chipset-specific packages
  - RTL8852A/RTL8852B (WiFi 6) → `wifi-firmware-rtw89-kmod-rtw8852a`
  - RTL8822B/RTL8822C (WiFi 5) → `wifi-firmware-rtw88-kmod-rtw8822b`
  - RTL8188/RTL8192 (legacy) → Native FreeBSD driver

- **MediaTek**: WiFi 6/6E support
  - MT76xx series → `wifi-firmware-mt76-kmod-mt7915`
  - MT7601U USB → `wifi-firmware-mt7601u-kmod`

- **Broadcom**: BCM43xx series (native FreeBSD drivers)

### USB Adapters
- **ASIX**: AX88179/AX88178A USB 3.0 Gigabit, AX88x72 USB 2.0
- **Realtek**: RTL8152/RTL8153 USB Ethernet, RTL8188/RTL8192 USB WiFi with modern firmware
- **Ralink/MediaTek**: RT2870/RT3070/RT5370 USB WiFi, MT7601U with targeted firmware
- **Legacy USB**: RT2500/RT2501 series (native FreeBSD drivers)

*NetPilot automatically selects the most appropriate firmware package for each specific chipset, ensuring optimal compatibility and performance.*

*See `netpilot --show-coverage` for the complete list.*

## Architecture

### Core Components
- **CommandRunner**: Parallel command execution with intelligent caching
- **EnhancedDriverDatabase**: Intelligent driver matching with dependency resolution
- **AdvancedNetworkManager**: Comprehensive device discovery and configuration
- **SystemConfigManager**: Automated `/boot/loader.conf` and `/etc/rc.conf` management

### Key Features
- **Parallel Processing**: Device discovery and interface scanning run concurrently
- **Smart Caching**: Avoid redundant system calls for better performance
- **Dependency Management**: Automatically loads required kernel modules (linuxkpi, etc.)
- **Conflict Prevention**: Avoids loading incompatible drivers
- **Configuration Safety**: Automatic backups and change tracking for all system modifications
- **Persistent Configuration**: Ensures network setup survives reboots

### System File Management
- **Backup System**: Timestamped backups in `/var/backups/netpilot/`
- **Change Tracking**: Complete audit trail of all modifications
- **Atomic Updates**: Safe file modification with rollback capability
- **Intelligent Merging**: Preserves existing configuration while adding new entries

### Development Setup
```bash
git clone https://github.com/yourusername/netpilot.git
cd netpilot

# Run in development mode
sudo python3 netpilot.py -v
```

### Adding Hardware Support
1. Find your device IDs: `pciconf -lv` or `usbconfig dump_all_desc`
2. Add to `EnhancedDriverDatabase._load_comprehensive_rules()`
3. Add firmware package mapping if needed
4. Test on your hardware
5. Submit a pull request

### Testing
```bash
# Test discovery without loading drivers
sudo python3 netpilot.py --no-driver-loading -v

# Test configuration preview
sudo python3 netpilot.py --show-config-changes

# Test on specific hardware
sudo python3 netpilot.py --interface YOUR_INTERFACE -v
```

## Troubleshooting

### Common Issues

**Driver loading fails**
```bash
# Check kernel module availability
kldstat -v | grep network_driver

# Try manual loading
sudo kldload if_driver_name

# Check system logs
dmesg | tail -20

# Verify loader.conf entries
grep netpilot /boot/loader.conf
```

**No interfaces detected**
```bash
# Verify hardware detection
sudo netpilot --no-driver-loading -v

# Check PCI devices
pciconf -lv | grep network

# Show configuration preview
sudo netpilot --show-config-changes
```

**Configuration not persisting**
```bash
# Check if boot configuration was applied
sudo netpilot --configure-boot -v

# Verify loader.conf entries
cat /boot/loader.conf | grep -A5 "NetPilot"

# Check rc.conf for interface configuration
cat /etc/rc.conf | grep -A5 "NetPilot"
```

**WiFi interfaces not working**
```bash
# Create wlan interfaces manually
sudo netpilot --create-wlan -v

# Check if wlan entries are in rc.conf
grep wlans_ /etc/rc.conf

# Verify WiFi driver and firmware
kldstat | grep -E "(iwm|iwlwifi|ath)"
pkg info | grep -E "wifi-firmware.*kmod"
```

**Wrong firmware package installed**
```bash
# Check what firmware packages are installed
pkg info | grep wifi-firmware

# Remove incorrect firmware and re-run NetPilot
sudo pkg delete wifi-firmware-*
sudo netpilot --configure-boot -v
```

**Permission denied**
```bash
# NetPilot requires root for driver loading and system configuration
sudo netpilot

# Or run discovery-only as regular user
netpilot --no-driver-loading --show-coverage
```

### Configuration Recovery

**Restore from backup**
```bash
# List available backups
ls -la /var/backups/netpilot/

# Restore loader.conf from backup
sudo cp /var/backups/netpilot/loader.conf.YYYYMMDD_HHMMSS.backup /boot/loader.conf

# Restore rc.conf from backup  
sudo cp /var/backups/netpilot/rc.conf.YYYYMMDD_HHMMSS.backup /etc/rc.conf
```

**Check configuration changes**
```bash
# View change history
sudo netpilot --json-output | jq '.system_configuration.summary.changes'

# Compare current vs backup
diff /boot/loader.conf /var/backups/netpilot/loader.conf.*.backup
```

### Debug Mode
```bash
# Maximum verbosity with configuration preview
sudo netpilot --show-config-changes -v

# Full discovery with system configuration
sudo netpilot --configure-boot --configure-startup -v --json-output > debug.json

# Check the debug.json file for detailed information
```

## TODO

- [ ] **GUI Interface**: GTK-based graphical interface for desktop users
- [ ] **WPA Configuration**: Automated WiFi security setup with wpa_supplicant integration
- [ ] **Network Profiles**: Save and restore complete network configurations
- [ ] **Bridge/VLAN Support**: Advanced networking features for complex setups  
- [ ] **Container Integration**: Docker/jail networking support
- [ ] **Configuration Rollback**: One-command restoration of previous configurations
- [ ] **Service Integration**: systemd/rc.d service for continuous monitoring
- [ ] **Remote Management**: Web interface for headless system configuration
- [ ] **Configuration Templates**: Predefined setups for common deployment scenarios
- [ ] **Hardware Database Updates**: Online updates for latest device support

## License

NetPilot is released under the BSD 2-Clause License. See [LICENSE](LICENSE) for details.

*NetPilot v0.0.4 - Because network setup should just work™*
