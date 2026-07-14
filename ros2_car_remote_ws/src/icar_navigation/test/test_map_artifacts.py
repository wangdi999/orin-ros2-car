"""Tests for complete and internally consistent map files."""

from pathlib import Path
import tempfile
import unittest

from icar_navigation.map_artifacts import (
    validate_map_artifacts,
    validate_reload_results,
)


class TestMapArtifacts(unittest.TestCase):
    """Verify map basename, metadata and reload evidence requirements."""

    def create_map(self, directory, image='campus_map.pgm'):
        Path(directory, 'campus_map.pgm').write_bytes(b'P5\n1 1\n255\n\x00')
        Path(directory, 'campus_map.pbstream').write_bytes(b'pbstream')
        Path(directory, 'campus_map.yaml').write_text(
            'image: {}\nresolution: 0.05\norigin: [0.0, 0.0, 0.0]\n'
            'negate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.25\n'.format(
                image),
            encoding='utf-8')

    def test_complete_matching_artifacts_pass(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            self.create_map(directory)
            report = validate_map_artifacts(directory)
            self.assertTrue(report.valid, report.errors)

    def test_missing_pbstream_and_wrong_image_fail(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            self.create_map(directory, image='other.pgm')
            Path(directory, 'campus_map.pbstream').unlink()
            report = validate_map_artifacts(directory)
            self.assertFalse(report.valid)
            self.assertTrue(any('pbstream' in error for error in report.errors))
            self.assertTrue(any('image' in error for error in report.errors))

    def test_reload_gate_requires_exactly_two_successes(self):
        self.assertTrue(validate_reload_results([True, True]))
        self.assertFalse(validate_reload_results([True]))
        self.assertFalse(validate_reload_results([True, False]))

    def test_save_script_promotes_only_a_complete_atomic_release(self):
        script = Path(
            __file__).resolve().parents[1] / 'scripts' / 'save_map.sh'
        text = script.read_text(encoding='utf-8')
        self.assertIn('for extension in pgm yaml pbstream', text)
        self.assertIn('.map-releases', text)
        self.assertIn('mv -Tf', text)
        self.assertLess(
            text.index('is missing or empty'),
            text.index('release_root='))


if __name__ == '__main__':
    unittest.main()
