"""Validation helpers for a complete Cartographer map artifact set."""

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Tuple

import yaml


@dataclass(frozen=True)
class MapArtifactReport:
    """Validation result for one PGM/YAML/PBStream basename."""

    valid: bool
    errors: Tuple[str, ...]
    pgm_path: Path
    yaml_path: Path
    pbstream_path: Path


def validate_map_artifacts(directory, basename='campus_map'):
    """Require non-empty, mutually consistent map artifacts."""
    directory = Path(directory)
    pgm_path = directory / '{}.pgm'.format(basename)
    yaml_path = directory / '{}.yaml'.format(basename)
    pbstream_path = directory / '{}.pbstream'.format(basename)
    errors = []
    for path in (pgm_path, yaml_path, pbstream_path):
        if not path.is_file() or path.stat().st_size == 0:
            errors.append('{} is missing or empty'.format(path.name))

    if pgm_path.is_file() and pgm_path.stat().st_size:
        try:
            magic = pgm_path.read_bytes()[:2]
            if magic not in {b'P2', b'P5'}:
                errors.append('map PGM header must be P2 or P5')
        except OSError as exc:
            errors.append('map PGM cannot be read: {}'.format(exc))

    metadata = None
    if yaml_path.is_file() and yaml_path.stat().st_size:
        try:
            metadata = yaml.safe_load(yaml_path.read_text(encoding='utf-8'))
        except (OSError, yaml.YAMLError) as exc:
            errors.append('map YAML cannot be parsed: {}'.format(exc))
    if not isinstance(metadata, dict):
        if metadata is not None:
            errors.append('map YAML root must be a mapping')
    else:
        if Path(str(metadata.get('image', ''))).name != pgm_path.name:
            errors.append('map YAML image must reference {}'.format(pgm_path.name))
        resolution = metadata.get('resolution')
        if not _positive_finite(resolution):
            errors.append('map resolution must be a positive finite number')
        origin = metadata.get('origin')
        if (not isinstance(origin, list) or len(origin) != 3
                or not all(_finite(value) for value in origin)):
            errors.append('map origin must contain three finite numbers')
        for field in ('occupied_thresh', 'free_thresh'):
            value = metadata.get(field)
            if not _probability(value):
                errors.append('{} must be within [0, 1]'.format(field))
        if metadata.get('negate') not in {0, 1}:
            errors.append('negate must be 0 or 1')

    return MapArtifactReport(
        valid=not errors,
        errors=tuple(errors),
        pgm_path=pgm_path,
        yaml_path=yaml_path,
        pbstream_path=pbstream_path,
    )


def validate_reload_results(results):
    """Require two explicit successful Map Server reload results."""
    return isinstance(results, (list, tuple)) and results == [True, True]


def _finite(value):
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _positive_finite(value):
    return _finite(value) and float(value) > 0.0


def _probability(value):
    return _finite(value) and 0.0 <= float(value) <= 1.0
