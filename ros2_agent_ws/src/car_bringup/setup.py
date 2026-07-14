from glob import glob
from setuptools import find_packages, setup


package_name = "car_bringup"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/launch", glob("launch/*_launch.py")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="orin-ros2-car maintainers",
    maintainer_email="maintainer@example.com",
    description="Inspection car orchestration bringup",
    license="Apache-2.0",
)
