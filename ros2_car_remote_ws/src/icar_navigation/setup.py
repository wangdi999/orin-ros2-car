from glob import glob
import os
from pathlib import Path

from setuptools import setup


package_name = 'icar_navigation'


def install_tree(source, destination):
    """Preserve nested/hidden map release files in setuptools data_files."""
    groups = {}
    root = Path(source)
    if not root.exists():
        return []
    for path in root.rglob('*'):
        if not (path.is_file() or path.is_symlink()):
            continue
        relative_parent = path.parent.relative_to(root)
        install_directory = os.path.join(destination, str(relative_parent))
        groups.setdefault(install_directory, []).append(str(path))
    return sorted(groups.items())

setup(
    name=package_name,
    version='1.0.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'config'), glob('config/*')),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
    ] + install_tree('maps', os.path.join('share', package_name, 'maps')),
    scripts=[
        'scripts/save_map.sh',
        'scripts/verify_navigation.sh',
    ],
    install_requires=['setuptools', 'PyYAML'],
    zip_safe=True,
    maintainer='iCar maintainers',
    maintainer_email='maintainer@example.com',
    description='Safe ROS2 Foxy navigation stack for the X3 car.',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'cmd_vel_arbiter = icar_navigation.cmd_vel_arbiter:main',
            'safety_manager = icar_navigation.safety_manager:main',
            'patrol_manager = icar_navigation.patrol_manager:main',
        ],
    },
)
