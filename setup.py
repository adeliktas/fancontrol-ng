from setuptools import setup
from setuptools.command.install import install
import subprocess
import pwd
import grp
import os
import json
import re

class CustomInstall(install):
    def run(self):
        script_dir = os.path.dirname(os.path.abspath(__file__))

        # Create hwmon group + add user
        try:
            grp.getgrnam('hwmon')
        except KeyError:
            subprocess.run(['groupadd', 'hwmon'], check=True)

        username = os.environ.get('SUDO_USER')
        if not username:
            username = pwd.getpwuid(1000).pw_name
        subprocess.run(['usermod', '-aG', 'hwmon', username], check=True)

        # udev rules
        rules_content = '''
# Set permissions for thermal_zone0/mode (disable override, allow group write)
SUBSYSTEM=="thermal", KERNEL=="thermal_zone0", ATTR{mode}="disabled", RUN+="/bin/chmod 0664 /sys$devpath/mode", RUN+="/bin/chgrp hwmon /sys$devpath/mode"

# Set permissions for pwm-fan (manual mode, allow group write on pwm1 and pwm1_enable)
SUBSYSTEM=="hwmon", ATTR{name}=="pwmfan", ATTR{pwm1_enable}="1", RUN+="/bin/chmod 0664 /sys$devpath/pwm1", RUN+="/bin/chmod 0664 /sys$devpath/pwm1_enable", RUN+="/bin/chgrp hwmon /sys$devpath/pwm1", RUN+="/bin/chgrp hwmon /sys$devpath/pwm1_enable"
        '''.strip()

        with open('/etc/udev/rules.d/99-hc4-hwmon.rules', 'w') as f:
            f.write(rules_content)

        subprocess.run(['udevadm', 'control', '--reload-rules'], check=True)
        subprocess.run(['udevadm', 'trigger'], check=True)

        # Logs directory
        logs_dir = os.path.join(script_dir, 'logs')
        os.makedirs(logs_dir, exist_ok=True)
        log_path = os.path.join(logs_dir, 'log.txt')
        open(log_path, 'a').close()
        subprocess.run(['chown', '-R', f'{username}:{username}', logs_dir], check=True)

        # === Create fan_read_mappings.sh if missing (embedded) ===
        bash_script = os.path.join(script_dir, 'fan_read_mappings.sh')
        if not os.path.exists(bash_script):
            bash_content = '''#!/bin/bash
echo 1 > /sys/class/hwmon/hwmon2/pwm1_enable   # manual mode
for i in {0..255..15}; do
  echo $i > /sys/class/hwmon/hwmon2/pwm1
  sleep 4
  rpm=$(cat /sys/class/hwmon/hwmon2/fan1_input)
  echo "PWM $i → $rpm RPM"
done
'''
            with open(bash_script, 'w') as f:
                f.write(bash_content)
            subprocess.run(['chmod', '+x', bash_script], check=True)
            print("✅ Created fan_read_mappings.sh")

        # === Generate default config.json if missing ===
        config_path = os.path.join(script_dir, 'config.json')
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
            subprocess.run(['chown', f'{username}:{username}', config_path], check=True)
            print("✅ Generated default config.json")

        # === Generate fan_mapping.json (non-fatal) ===
        mapping_path = os.path.join(script_dir, 'fan_mapping.json')
        if not os.path.exists(mapping_path):
            print("Running fan calibration (takes ~1-2 minutes)...")
            try:
                result = subprocess.run([bash_script], capture_output=True, text=True, check=True)
                output = result.stdout
                pwm_rpm = {}
                for line in output.splitlines():
                    if line.startswith('PWM '):
                        match = re.search(r'PWM (\d+) → (\d+) RPM', line)
                        if match:
                            pwm = int(match.group(1))
                            rpm = int(match.group(2))
                            pwm_rpm[pwm] = rpm

                if pwm_rpm:
                    pwms = sorted(pwm_rpm.keys())
                    rpms = [pwm_rpm[p] for p in pwms]
                    max_rpm = max(rpms)

                    mapping = {}
                    for perc in range(0, 101):
                        desired_rpm = (perc / 100.0) * max_rpm
                        if desired_rpm <= 0:
                            pwm_val = 0
                        elif desired_rpm >= max_rpm:
                            pwm_val = 255
                        else:
                            for j in range(len(rpms) - 1):
                                if rpms[j] <= desired_rpm < rpms[j + 1]:
                                    frac = (desired_rpm - rpms[j]) / (rpms[j + 1] - rpms[j])
                                    pwm_val = pwms[j] + frac * (pwms[j + 1] - pwms[j])
                                    break
                            else:
                                pwm_val = pwms[-1]
                        mapping[str(perc)] = int(round(pwm_val))

                    with open(mapping_path, 'w') as f:
                        json.dump(mapping, f, indent=2)
                    subprocess.run(['chown', f'{username}:{username}', mapping_path], check=True)
                    print(f"✅ Generated fan_mapping.json (max RPM: {max_rpm})")
                else:
                    print("Warning: Could not parse fan data.")
            except Exception as e:
                print(f"Calibration skipped (non-critical): {e}. You can run it later manually.")

        # systemd service
        service_content = '''
[Unit]
Description=FanControl-NG - Custom Fan Control Service for ODROID-HC4
After=multi-user.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 {script_dir}/main.py
Restart=always
User={username}
WorkingDirectory={script_dir}
StandardOutput=append:{log_path}
StandardError=inherit

[Install]
WantedBy=multi-user.target
        '''.strip().format(script_dir=script_dir, username=username, log_path=log_path)

        with open('/etc/systemd/system/fancontrol-ng.service', 'w') as f:
            f.write(service_content)

        subprocess.run(['systemctl', 'daemon-reload'], check=True)

        # OpenRC service
        openrc_content = '''
#!/sbin/openrc-run

description="FanControl-NG - Custom Fan Control Service for ODROID-HC4"

command="/usr/bin/python3"
command_args="{script_dir}/main.py >> {log_path} 2>&1"
command_background="yes"
pidfile="/run/fancontrol-ng.pid"
command_user="{username}"

depend() {{
    need localmount
    after bootmisc
}}

start_pre() {{
    ebegin "Starting FanControl-NG"
}}

stop_pre() {{
    ebegin "Stopping FanControl-NG"
}}
        '''.strip().format(script_dir=script_dir, username=username, log_path=log_path)

        openrc_path = '/etc/init.d/fancontrol-ng'
        with open(openrc_path, 'w') as f:
            f.write(openrc_content)

        subprocess.run(['chmod', '+x', openrc_path], check=True)

        install.run(self)

setup(
    name='hc4-fan-setup',
    version='0.1',
    description='Setup script for ODROID-HC4 fan control permissions',
    packages=[],
    cmdclass={'install': CustomInstall},
)
