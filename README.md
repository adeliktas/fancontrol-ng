# FanControl-NG

FanControl-NG is a custom fan control utility (for the ODROID-HC4 sbc).
It uses a Python script to manage fan speed based on a configurable temperature curve, ensuring optimal cooling without relying on the system's default `fancontrol`.
The project handles PWM fan control, thermal overrides, and permissions for non-root execution.

## Features
- Configurable temperature-to-fan-speed curve with interpolation (loaded from config.json at runtime).
- ASCII table and plot for visualizing the fan curve.
- Dynamic path detection for hardware sysfs files (handles variable hwmon indices).
- Error handling for permissions, guiding users to run setup.
- Support for running as a background service (systemd and OpenRC).
- Safe writes with permission checks.
- Realtime logging to logs/log.txt for service output (view with tail -f logs/log.txt).
- Automatic creation of missing files (config.json, fan_read_mappings.sh, fan_mapping.json) and one-time fan calibration on first setup.

## Requirements
- Python 3.x with NumPy (for interpolation).
- ODROID-HC4 running Armbian or similar (tested on Ubuntu Noble with kernel 6.12.x).
- Root access for initial setup (udev rules and group creation).

## Installation
1. Clone or download the project:
   ```
   git clone https://github.com/adeliktas/fancontrol-ng.git
   cd fancontrol-ng
   ```

2. Install Python dependencies:

   - Using apt (system-wide, recommended for simplicity):
     ```
     sudo apt update
     sudo apt install -y python3-numpy
     ```

   - Alternatively, using a virtual environment (for isolation):
     ```
     python3 -m venv venv
     source venv/bin/activate
     pip install -r requirements.txt
     ```
     (Deactivate with `deactivate` when done. Note: If using venv, adjust service ExecStart to use venv/bin/python.)

3. Run the setup script as root to configure groups, udev rules, reload, install services automatically, and create logs dir/file with proper ownership:
   ```
   sudo python3 setup.py install
   ```
   - This creates the `hwmon` group, adds the calling user (or UID 1000 fallback) to it.
   - Installs udev rules for permissions on sysfs files.
   - Reloads udev rules.
   - Installs systemd and OpenRC services with resolved paths and file logging (no manual edits needed).
   - Creates logs/ dir and log.txt with user ownership.
   - **Also automatically creates** `fan_read_mappings.sh`, default `config.json`, and runs a one-time fan calibration to generate `fan_mapping.json` (if missing).

4. If necessary, relogin as your user to apply group changes.

## Usage
- Edit the settings in `config.json` to customize the temperature-speed curve, sleep interval, sysfs paths (leave empty for runtime defaults), and plot parameters.
- Run the script as a non-root user (if using venv, activate it first):
  ```
  python3 main.py
  ```
  - It loads (or auto-creates) config.json, displays the curve table and ASCII plot.
  - Starts a loop to monitor CPU temp and adjust PWM based on the configured interval.
  - Press Ctrl+C to stop.

If permissions are missing, the script will prompt to run `setup.py` as admin.

## Configuration
- **config.json**: Edit this file for all runtime configurations (no hardcodes in script).
  Example:
  ```json
  {
    "curve": [
      [0, 0],    // 0°C: 0%
      [20, 30],  // 20°C: 30%
      [50, 100]  // 50°C: 100%
    ],
    "sleep_interval": 10,  // Seconds between updates
    "thermal_mode_path": "",  // Leave empty for default resolution at runtime
    "thermal_temp_path": "",
    "pwm_enable_glob": "",
    "pwm_glob": "",
    "plot_min_temp": 0,
    "plot_max_temp": 60,
    "plot_step": 5,
    "max_bar_width": 50
  }
  ```
  - Curve: List of [temp_C, percentage] pairs (temperatures in °C, percentages now map to **% of real maximum RPM** thanks to the auto-generated `fan_mapping.json`).
  - Paths/Globs: Leave empty ("") for automatic runtime defaults; set to custom values to override.

## Running as a Service

setup.py automatically installs the services with correct paths, user, and logging to logs/log.txt.

### Systemd
- Enable and start:
```
sudo systemctl enable fancontrol-ng.service
sudo systemctl start fancontrol-ng.service
```
- View logs: `tail -f logs/log.txt` or `journalctl -u fancontrol-ng.service`

### OpenRC
- Add to default and start:
```
rc-update add fancontrol-ng default
/etc/init.d/fancontrol-ng start
```
- View logs: `tail -f logs/log.txt`

If using venv, manually adjust ExecStart/command in the service file to point to venv/bin/python.

## Troubleshooting
- **PWM Not Found**: Ensure `overlays=i2cA g12-pwm-gpiox-5-fan` in `/boot/armbianEnv.txt`, reboot.
- **Permission Denied**: Rerun `setup.py` as root, relogin.
- **Fan Not Responding**: check `dmesg | grep pwm`.
- **Thermal Override**: Udev disables it automatically; verify with `cat /sys/class/thermal/thermal_zone0/mode`.
- **Variable hwmon Index**: Script uses glob to find paths automatically.
- **No fan_mapping.json or calibration needed later**: Delete `fan_mapping.json` and re-run `sudo python3 setup.py install`.

## License
MIT License. See [LICENSE](LICENSE) for details.

## Contributions
Pull requests welcome! For issues, open a ticket on the repository.