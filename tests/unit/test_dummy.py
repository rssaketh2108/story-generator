# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
from app.tools import save_artifact_file, read_artifact_file, generate_panel_image, ARTIFACTS_DIR

def test_save_and_read_artifact() -> None:
    """Test saving and reading markdown artifacts."""
    filename = "test_artifact_temp.md"
    content = "This is a temporary artifact test."
    
    # Test Save
    res_save = save_artifact_file(filename, content)
    assert res_save["status"] == "success"
    assert res_save["filepath"] == f"/artifacts/{filename}"
    
    # Test Read
    res_read = read_artifact_file(filename)
    assert res_read["status"] == "success"
    assert res_read["content"] == content
    
    # Clean up
    filepath = os.path.join(ARTIFACTS_DIR, filename)
    if os.path.exists(filepath):
        os.remove(filepath)

def test_generate_panel_image() -> None:
    """Test Pillow panel mockup generation."""
    filename = "test_panel_temp.png"
    prompt = "A detective looking at neon signs."
    
    # Test Generate
    res = generate_panel_image(filename, prompt)
    assert res["status"] == "success"
    assert res["filepath"] == f"/artifacts/{filename}"
    
    filepath = os.path.join(ARTIFACTS_DIR, filename)
    assert os.path.exists(filepath)
    
    # Clean up
    if os.path.exists(filepath):
        os.remove(filepath)
