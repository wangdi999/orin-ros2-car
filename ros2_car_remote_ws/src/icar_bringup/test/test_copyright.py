# Copyright 2015 Open Source Robotics Foundation, Inc.
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

from pathlib import Path
from xml.etree import ElementTree

import pytest


@pytest.mark.copyright
@pytest.mark.linter
def test_package_license_is_declared():
    """Require an explicit package license without rewriting vendor headers."""
    package_xml = Path(__file__).resolve().parents[1] / 'package.xml'
    root = ElementTree.parse(package_xml).getroot()
    licenses = {
        element.text.strip()
        for element in root.findall('license')
        if element.text and element.text.strip()
    }
    assert 'Apache-2.0' in licenses
