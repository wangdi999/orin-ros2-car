"""Helpers for deterministic Foxy parameter-file composition."""

import yaml


def merge_node_parameters(config_path, node_name, overrides):
    """Merge one exact-node YAML mapping with launch-time overrides.

    Foxy gives an exact node-name mapping precedence over a later `/**`
    mapping, so passing a YAML file and a launch dictionary separately can
    silently discard overlapping launch overrides. Returning one mapping
    removes that precedence ambiguity.
    """
    with open(config_path, 'r', encoding='utf-8') as stream:
        document = yaml.safe_load(stream)
    try:
        parameters = document[node_name]['ros__parameters']
    except (KeyError, TypeError) as exc:
        raise ValueError(
            'missing ros__parameters for {}'.format(node_name)) from exc
    if not isinstance(parameters, dict):
        raise ValueError(
            'ros__parameters for {} must be a mapping'.format(node_name))
    merged = dict(parameters)
    merged.update(dict(overrides))
    return merged
