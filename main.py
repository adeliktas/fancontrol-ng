import numpy as np
import time
import glob
import sys
import json
import os

# Load configuration from config.json in current directory
config_path = 'config.json'
if not os.path.exists(config_path):
    print(f"Error: Configuration file '{config_path}' not found. Please create it based on the sample.")
    sys.exit(1)

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
    print("Error: Invalid curve format in config.json. Expected list of [temp_C, percentage] pairs.")
    sys.exit(1)

# Extract temps and percs for interpolation
temps = [t for t, p in curve]
percs = [p for t, p in curve]

# Display the table
print("Temperature Curve Table:")
print("Temp (°C)\tPercentage (%)\tPWM Value")
for t, p in curve:
    pwm = int(p * 2.55)  # 100% = 255
    print(f"{t}\t\t{p}\t\t{pwm}")

# Display ASCII plot in configurable steps
print("\nASCII Plot of Fan Speed Curve (in {plot_step}°C steps):".format(plot_step=plot_step))
print("Temp (°C) | Speed Bar (scaled to {max_bar_width} chars max) | Percentage (%)".format(max_bar_width=max_bar_width))
for t in range(plot_min_temp, plot_max_temp + 1, plot_step):
    perc = np.interp(t, temps, percs, left=0, right=100)
    pwm = int(perc * 2.55)
    bar_length = int(perc / 100 * max_bar_width)
    bar = '#' * bar_length
    print(f"{t:2d}       | {bar:<{max_bar_width}} | {perc:.0f}% (PWM: {pwm})")

# Dynamically find paths using globs
try:
    pwm_enable_path = glob.glob(pwm_enable_glob)[0]
    pwm_path = glob.glob(pwm_glob)[0]
except IndexError:
    print("Error: PWM paths not found. Ensure the fan driver is loaded and overlays are enabled.")
    sys.exit(1)

def safe_write(path, value):
    try:
        with open(path, 'w') as f:
            f.write(value)
    except PermissionError:
        print("Error: Permission denied when writing to {}. Please run setup.py as admin to configure permissions.".format(path))
        sys.exit(1)

# Disable thermal mode
safe_write(thermal_mode_path, 'disabled')

# Enable manual PWM
safe_write(pwm_enable_path, '1')

# Main loop for fan control
print("\nStarting fan control loop (Ctrl+C to stop)...")
while True:
    # Read CPU temperature (in °C)
    with open(thermal_temp_path, 'r') as f:
        temp = int(f.read().strip()) / 1000
    
    # Interpolate percentage, clamp between 0-100
    perc = np.interp(temp, temps, percs, left=0, right=100)
    pwm = int(perc * 2.55)  # Convert to PWM (0-255)
    
    # Set PWM
    safe_write(pwm_path, str(pwm))
    
    print(f"Current Temp: {temp:.1f}°C | Set PWM: {pwm} ({perc:.0f}%)")
    
    # Sleep for configurable interval
    time.sleep(sleep_interval)