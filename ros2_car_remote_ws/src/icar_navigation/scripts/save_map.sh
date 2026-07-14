#!/usr/bin/env bash
set -euo pipefail

basename="${1:-campus_map}"
output_dir="${2:-${ICAR_MAP_OUTPUT_DIR:-$PWD}}"

if [[ ! "$basename" =~ ^[A-Za-z0-9_-]+$ ]]; then
  echo "Map basename must contain only letters, numbers, underscore or hyphen." >&2
  exit 2
fi

mkdir -p "$output_dir"
tmp_dir="$(mktemp -d "${output_dir}/.${basename}.tmp.XXXXXX")"
trap 'rm -rf -- "$tmp_dir"' EXIT

pbstream="${tmp_dir}/${basename}.pbstream"
ros2 service call /write_state cartographer_ros_msgs/srv/WriteState \
  "{filename: '${pbstream}'}"
ros2 run nav2_map_server map_saver_cli -f "${tmp_dir}/${basename}"

# map_saver_cli records the temporary absolute PGM path. The temporary
# directory is atomically moved below, so normalize the YAML to a sibling
# image reference before validating and publishing the release.
sed -i -E "s|^image:[[:space:]].*$|image: ${basename}.pgm|" \
  "${tmp_dir}/${basename}.yaml"
if ! grep -Fxq "image: ${basename}.pgm" \
    "${tmp_dir}/${basename}.yaml"; then
  echo "Map save failed: YAML image reference was not normalized." >&2
  exit 4
fi

for extension in pgm yaml pbstream; do
  path="${tmp_dir}/${basename}.${extension}"
  if [[ ! -s "$path" ]]; then
    echo "Map save failed: ${path} is missing or empty." >&2
    exit 3
  fi
done

release_root="${output_dir}/.map-releases"
release_id="$(date -u +%Y%m%dT%H%M%SZ)-$$"
release_dir="${release_root}/${release_id}"
mkdir -p "$release_root"
mv -- "$tmp_dir" "$release_dir"

# The stable artifact links all resolve through one atomically replaced current
# link, so an existing map never observes a mixed PGM/YAML/PBStream release.
current_next="${release_root}/.${basename}.current.${release_id}"
ln -s "$release_id" "$current_next"
mv -Tf -- "$current_next" "${release_root}/${basename}.current"
for extension in pgm yaml pbstream; do
  artifact_next="${output_dir}/.${basename}.${extension}.${release_id}"
  ln -s ".map-releases/${basename}.current/${basename}.${extension}" \
    "$artifact_next"
  mv -Tf -- "$artifact_next" "${output_dir}/${basename}.${extension}"
done

echo "Saved atomic map release ${release_id} to ${output_dir}"
