from glob import glob
import os

from setuptools import setup


package_name = 'icar_bringup'

setup(
    name=package_name,
    version='1.0.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
         ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'),
         glob(os.path.join('launch', '*launch.py'))),
        (os.path.join('share', package_name, 'rviz'),
         glob(os.path.join('rviz', '*.rviz*'))),
        (os.path.join('share', package_name, 'param'),
         glob(os.path.join('param', '*.yaml'))),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='iCar maintainers',
    maintainer_email='maintainer@example.com',
    description='Hardware bringup and safe Rosmaster drivers for iCar.',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'Mcnamu_driver_X3 = icar_bringup.Mcnamu_driver_X3:main',
            'Mcnamu_driver_x1 = icar_bringup.Mcnamu_driver_x1:main',
            'calibrate_linear_X3 = icar_bringup.calibrate_linear_X3:main',
            'calibrate_angular_X3 = icar_bringup.calibrate_angular_X3:main',
            'patrol_4ROS = icar_bringup.patrol_4ROS:main',
            'patrol_a1_X3 = icar_bringup.patrol_a1_X3:main',
            'Ackman_driver_R2 = icar_bringup.Ackman_driver_R2:main',
            'calibrate_linear_R2 = icar_bringup.calibrate_linear_R2:main',
            'calibrate_angular_R2 = icar_bringup.calibrate_angular_R2:main',
            'patrol_4ROS_R2 = icar_bringup.patrol_4ROS_R2:main',
            'patrol_a1_R2 = icar_bringup.patrol_a1_R2:main',
        ],
    },
)
