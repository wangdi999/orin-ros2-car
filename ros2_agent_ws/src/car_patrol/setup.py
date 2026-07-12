from glob import glob
from setuptools import find_packages, setup


package_name = "car_patrol"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/launch", glob("launch/*_launch.py")),
        (f"share/{package_name}/config", glob("config/*.yaml")),
    ],
    install_requires=["setuptools", "PyYAML"],
    zip_safe=True,
    maintainer="orin-ros2-car maintainers",
    maintainer_email="maintainer@example.com",
    description="Deterministic Nav2 patrol state machine",
    license="Apache-2.0",
    entry_points={"console_scripts": ["patrol_manager = car_patrol.patrol_manager:main"]},
)
