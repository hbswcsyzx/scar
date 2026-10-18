#!/usr/bin/env bash
set -euo pipefail

archive="artifacts/experiments/b1_call_operands/model_protocol_followup/codec/legacy-source-v19.tar"
tree="artifacts/experiments/b1_call_operands/model_protocol_followup/codec/legacy-src"
tmp_archive_list="$(mktemp)"
tmp_tree_list="$(mktemp)"
trap 'rm -f "$tmp_archive_list" "$tmp_tree_list"' EXIT

tar -tf "$archive" | sed '/\/$/d' | sort > "$tmp_archive_list"
find "$tree" -type f -printf '%P\n' | sort > "$tmp_tree_list"
diff -u "$tmp_archive_list" "$tmp_tree_list"

while IFS= read -r path; do
    archived="$(tar -xOf "$archive" "$path" | sha256sum | cut -d' ' -f1)"
    extracted="$(sha256sum "$tree/$path" | cut -d' ' -f1)"
    if [[ "$archived" != "$extracted" ]]; then
        printf 'content mismatch: %s\n' "$path" >&2
        exit 1
    fi
done < "$tmp_archive_list"

printf 'verified_entries=%s\n' "$(wc -l < "$tmp_archive_list" | tr -d ' ')"
printf 'archive_sha256=%s\n' "$(sha256sum "$archive" | cut -d' ' -f1)"
