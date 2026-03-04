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

# Load configuration from config.json in current directory
config_path = 'config.json'
if not os.path.exists(config_path):
    logging.error(f"Error: Configuration file '{config_path}' not found. Please create it based on the sample.")
    sys.exit(1)

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

    # Use defaults if paths are empty (resolve at runtime)
    if not thermal_mode_path:
        thermal_mode_path = '/sys/class/thermal/thermal_zone0/mode'
    if not thermal_temp_path:
        thermal_temp_path = '/sys/class/thermal/thermal_zone0/temp'
    if not pwm_enable_glob:
        pwm_enable_glob = '/sys/class/hwmon/hwmon*/pwm1_enable'
    if not pwm_glob:
        pwm_glob = '/sys/class/hwmon/hwmon*/pwm1'

    # Validate curve: list of [temp, perc] pairs
    if not isinstance(curve, list) or not all(isinstance(point, list) and len(point) == 2 and isinstance(point[0], (int, float)) and isinstance(point[1], (int, float)) for point in curve):
        logging.error("Error: Invalid curve format in config.json. Expected list of [temp_C, percentage] pairs.")
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

# Display the table
logging.info("Temperature Curve Table:")
logging.info("Temp (°C)\tPercentage (%)\tPWM Value")
for t, p in cfg['curve']:
    pwm = int(p * 2.55)  # 100% = 255
    logging.info(f"{t}\t\t{p}\t\t{pwm}")

# Display ASCII plot in configurable steps
logging.info("\nASCII Plot of Fan Speed Curve (in {plot_step}°C steps):".format(plot_step=cfg['plot_step']))
logging.info("Temp (°C) | Speed Bar (scaled to {max_bar_width} chars max) | Percentage (%)".format(max_bar_width=cfg['max_bar_width']))
for t in range(cfg['plot_min_temp'], cfg['plot_max_temp'] + 1, cfg['plot_step']):
    perc = np.interp(t, cfg['temps'], cfg['percs'], left=0, right=100)
    pwm = int(perc * 2.55)
    bar_length = int(perc / 100 * cfg['max_bar_width'])
    bar = '#' * bar_length
    logging.info(f"{t:2d}       | {bar:<{cfg['max_bar_width']}} | {perc:.0f}% (PWM: {pwm})")

# Dynamically find paths using globs
try:
    pwm_enable_path = glob.glob(cfg['pwm_enable_glob'])[0]
    pwm_path = glob.glob(cfg['pwm_glob'])[0]
except IndexError:
    logging.error("Error: PWM paths not found. Ensure the fan driver is loaded and overlays are enabled.")
    sys.exit(1)

def safe_write(path, value):
    try:
        with open(path, 'w') as f:
            f.write(value)
    except PermissionError:
        logging.error("Error: Permission denied when writing to {}. Please run setup.py as admin to configure permissions.".format(path))
        sys.exit(1)
    except Exception as e:
        logging.error(f"Unexpected error writing to {path}: {str(e)}")
        raise

# Disable thermal mode
safe_write(cfg['thermal_mode_path'], 'disabled')

# Enable manual PWM
safe_write(pwm_enable_path, '1')

# Get initial mtime of config.json
last_mtime = os.path.getmtime(config_path)

# Main loop for fan control
logging.info("\nStarting fan control loop (Ctrl+C to stop)...")
while True:
    try:
        # Check for config changes
        current_mtime = os.path.getmtime(config_path)
        if current_mtime != last_mtime:
            logging.info("Config file changed. Reloading...")
            try:
                cfg = load_config()
                last_mtime = current_mtime
                # Re-resolve paths if changed
                pwm_enable_path = glob.glob(cfg['pwm_enable_glob'])[0]
                pwm_path = glob.glob(cfg['pwm_glob'])[0]
                safe_write(cfg['thermal_mode_path'], 'disabled')
                safe_write(pwm_enable_path, '1')
            except Exception as e:
                logging.error(f"Failed to reload config: {str(e)}. Continuing with previous config.")

        # Read CPU temperature (in °C)
        with open(cfg['thermal_temp_path'], 'r') as f:
            temp = int(f.read().strip()) / 1000
        
        # Interpolate percentage, clamp between 0-100
        perc = np.interp(temp, cfg['temps'], cfg['percs'], left=0, right=100)
        pwm = int(perc * 2.55)  # Convert to PWM (0-255)
        
        # Set PWM
        safe_write(pwm_path, str(pwm))
        
        logging.info(f"Current Temp: {temp:.1f}°C | Set PWM: {pwm} ({perc:.0f}%)")
        
        # Sleep for configurable interval
        time.sleep(cfg['sleep_interval'])
    except Exception as e:
        logging.error(f"Unexpected error in main loop: {str(e)}")
        time.sleep(cfg['sleep_interval'])  # Continue after error