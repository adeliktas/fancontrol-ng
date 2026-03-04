from setuptools import setup
from setuptools.command.install import install
import subprocess
import pwd
import grp
import os

class CustomInstall(install):
    def run(self):
        script_dir = os.path.dirname(os.path.abspath(__file__))

        try:
            grp.getgrnam('hwmon')
        except KeyError:
            subprocess.run(['groupadd', 'hwmon'], check=True)

        username = os.environ.get('SUDO_USER')
        if not username:
            username = pwd.getpwuid(1000).pw_name
        subprocess.run(['usermod', '-aG', 'hwmon', username], check=True)

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

        # Create systemd service
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
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
        '''.strip().format(script_dir=script_dir, username=username)

        with open('/etc/systemd/system/fancontrol-ng.service', 'w') as f:
            f.write(service_content)

        subprocess.run(['systemctl', 'daemon-reload'], check=True)

        # Create OpenRC script
        openrc_content = '''
#!/sbin/openrc-run

description="FanControl-NG - Custom Fan Control Service for ODROID-HC4"

command="/usr/bin/python3"
command_args="{script_dir}/main.py"
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
        '''.strip().format(script_dir=script_dir, username=username)

        openrc_path = '/etc/init.d/fancontrol-ng'
        with open(openrc_path, 'w') as f:
            f.write(openrc_content)

        subprocess.run(['chmod', '+x', openrc_path], check=True)

        install.run(self)

setup(
    name='hc4-fan-setup',
    version='0.1',
    description='Setup script for ODROID-HC4 fan control permissions',
    cmdclass={'install': CustomInstall},
)