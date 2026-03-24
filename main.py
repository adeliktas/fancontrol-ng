import numpy as np
import time
import glob
import sys
import json
import os
import logging

# Setup logging early
log_dir = 'logs'
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'log.txt')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file, mode='a'),
        logging.StreamHandler(sys.stdout)
    ]
)

# === Create default config.json if it does not exist ===
config_path = 'config.json'
if not os.path.exists(config_path):
    default_config = {
        "curve": [
            [0, 0],
            [5, 1],
            [10, 2],
            [20, 3],
            [30, 9],
            [35, 15],
            [40, 20],
            [45, 30],
            [50, 45],
            [55, 100]
        ],
        "sleep_interval": 10,
        "thermal_mode_path": "",
        "thermal_temp_path": "",
        "pwm_enable_glob": "",
        "pwm_glob": "",
        "plot_min_temp": 0,
        "plot_max_temp": 60,
        "plot_step": 5,
        "max_bar_width": 50
    }
    with open(config_path, 'w') as f:
        json.dump(default_config, f, indent=2)
    logging.info("✅ Generated default config.json (you can edit the curve later)")

def load_config():
    with open(config_path, 'r') as f:
        config = json.load(f)

    curve = config['curve']
    sleep_interval = config['sleep_interval']
    thermal_mode_path = config.get('thermal_mode_path', '')
    thermal_temp_path = config.get('thermal_temp_path', '')
    pwm_enable_glob = config.get('pwm_enable_glob', '')
    pwm_glob = config.get('pwm_glob', '')
    plot_min_temp = config.get('plot_min_temp', 0)
    plot_max_temp = config.get('plot_max_temp', 60)
    plot_step = config.get('plot_step', 5)
    max_bar_width = config.get('max_bar_width', 50)

    # Use defaults if paths are empty
    if not thermal_mode_path:
        thermal_mode_path = '/sys/class/thermal/thermal_zone0/mode'
    if not thermal_temp_path:
        thermal_temp_path = '/sys/class/thermal/thermal_zone0/temp'
    if not pwm_enable_glob:
        pwm_enable_glob = '/sys/class/hwmon/hwmon*/pwm1_enable'
    if not pwm_glob:
        pwm_glob = '/sys/class/hwmon/hwmon*/pwm1'

    # Validate curve
    if not isinstance(curve, list) or not all(isinstance(point, list) and len(point) == 2 and isinstance(point[0], (int, float)) and isinstance(point[1], (int, float)) for point in curve):
        logging.error("Error: Invalid curve format in config.json.")
        sys.exit(1)

    temps = [t for t, p in curve]
    percs = [p for t, p in curve]

    return {
        'curve': curve,
        'temps': temps,
        'percs': percs,
        'sleep_interval': sleep_interval,
        'thermal_mode_path': thermal_mode_path,
        'thermal_temp_path': thermal_temp_path,
        'pwm_enable_glob': pwm_enable_glob,
        'pwm_glob': pwm_glob,
        'plot_min_temp': plot_min_temp,
        'plot_max_temp': plot_max_temp,
        'plot_step': plot_step,
        'max_bar_width': max_bar_width
    }

# Initial load
try:
    cfg = load_config()
except Exception as e:
    logging.error(f"Failed to load config: {str(e)}")
    sys.exit(1)

# Load fan_mapping.json (RPM-linear) if present
fan_mapping = None
perc_array = None
pwm_array = None
use_rpm_linear = False

mapping_path = 'fan_mapping.json'
if os.path.exists(mapping_path):
    try:
        with open(mapping_path, 'r') as f:
            fan_mapping = json.load(f)
        perc_list = [0]
        pwm_list = [0]
        for i in range(1, 101):
            perc_list.append(i)
            pwm_list.append(fan_mapping.get(str(i), 255))
        perc_array = np.array(perc_list)
        pwm_array = np.array(pwm_list)
        use_rpm_linear = True
        logging.info("✅ Loaded fan_mapping.json → using linear % of max RPM")
    except Exception as e:
        logging.warning(f"Failed to load fan_mapping.json: {e}. Falling back to linear PWM.")

label_perc = "% max RPM" if use_rpm_linear else "% (linear PWM)"

# Display table & plot (unchanged from before)
logging.info(f"Temperature Curve Table ({label_perc}):")
logging.info("Temp (°C)\tPercentage\tPWM Value")
for t, p in cfg['curve']:
    if use_rpm_linear and perc_array is not None:
        pwm = int(np.interp(p, perc_array, pwm_array))
    else:
        pwm = int(p * 2.55)
    logging.info(f"{t}\t\t{p}\t\t{pwm}")

logging.info(f"\nASCII Plot of Fan Speed Curve (in {cfg['plot_step']}°C steps):")
logging.info(f"Temp (°C) | Speed Bar (scaled to {cfg['max_bar_width']} chars max) | {label_perc}")
for t in range(cfg['plot_min_temp'], cfg['plot_max_temp'] + 1, cfg['plot_step']):
    perc = np.interp(t, cfg['temps'], cfg['percs'], left=0, right=100)
    if use_rpm_linear and perc_array is not None:
        pwm = int(np.interp(perc, perc_array, pwm_array))
        label = f"{perc:.0f}% max RPM (PWM: {pwm})"
    else:
        pwm = int(perc * 2.55)
        label = f"{perc:.0f}% (PWM: {pwm})"
    bar_length = int(perc / 100 * cfg['max_bar_width'])
    bar = '#' * bar_length
    logging.info(f"{t:2d}       | {bar:<{cfg['max_bar_width']}} | {label}")

# Dynamically find paths
try:
    pwm_enable_path = glob.glob(cfg['pwm_enable_glob'])[0]
    pwm_path = glob.glob(cfg['pwm_glob'])[0]
except IndexError:
    logging.error("Error: PWM paths not found.")
    sys.exit(1)

def safe_write(path, value):
    try:
        with open(path, 'w') as f:
            f.write(value)
    except PermissionError:
        logging.error(f"Permission denied on {path}. Run setup.py as admin.")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Unexpected error writing to {path}: {str(e)}")
        raise

# Disable thermal mode + enable manual PWM
safe_write(cfg['thermal_mode_path'], 'disabled')
safe_write(pwm_enable_path, '1')

# Main loop
last_mtime = os.path.getmtime(config_path)
logging.info("\nStarting fan control loop (Ctrl+C to stop)...")

while True:
    try:
        current_mtime = os.path.getmtime(config_path)
        if current_mtime != last_mtime:
            logging.info("Config changed. Reloading...")
            cfg = load_config()
            last_mtime = current_mtime
            pwm_enable_path = glob.glob(cfg['pwm_enable_glob'])[0]
            pwm_path = glob.glob(cfg['pwm_glob'])[0]
            safe_write(cfg['thermal_mode_path'], 'disabled')
            safe_write(pwm_enable_path, '1')

        with open(cfg['thermal_temp_path'], 'r') as f:
            temp = int(f.read().strip()) / 1000

        perc = np.interp(temp, cfg['temps'], cfg['percs'], left=0, right=100)
        perc = max(0, min(100, perc))

        if use_rpm_linear and perc_array is not None:
            pwm = int(np.interp(perc, perc_array, pwm_array))
        else:
            pwm = int(perc * 2.55)

        safe_write(pwm_path, str(pwm))

        rpm_label = "max RPM" if use_rpm_linear else ""
        logging.info(f"Current Temp: {temp:.1f}°C | Set PWM: {pwm} ({perc:.0f}% {rpm_label})")

        time.sleep(cfg['sleep_interval'])

    except Exception as e:
        logging.error(f"Unexpected error: {str(e)}")
        time.sleep(cfg['sleep_interval'])
