from setuptools import setup

package_name = 'car_ai_vision'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='member-b',
    maintainer_email='member-b@smartcar.local',
    description='YOLOv8-TensorRT边缘推理节点：人员检测 + 异常行为识别 + 报警发布',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'yolov8_inference = car_ai_vision.yolov8_inference:main',
            'mjpeg_bridge = car_ai_vision.mjpeg_bridge:main',
            'ai_web_bridge = car_ai_vision.ai_web_bridge:main',
        ],
    },
)
