# Copyright 2017 Open Source Robotics Foundation, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from ament_flake8.main import main_with_errors
import pytest


MAINTAINED_FILES = [
    'icar_bringup/driver_safety.py',
    'icar_bringup/Mcnamu_driver_X3.py',
    'launch/icar_bringup_X3_launch.py',
    'test/test_driver_safety.py',
]


@pytest.mark.flake8
@pytest.mark.linter
def test_flake8():
    """Lint the maintained X3 safety surface, not inherited vendor tools."""
    rc, errors = main_with_errors(argv=MAINTAINED_FILES)
    assert rc == 0, \
        'Found %d code style errors / warnings:\n' % len(errors) + \
        '\n'.join(errors)
