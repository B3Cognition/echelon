#!/usr/bin/env bash

# Emit complete requirement tokens from stdin. The optional ordinal expression
# lets legacy metrics retain the exact three-digit lowercase suffix they accept.
extract_requirement_ids() {
  local prefixes="$1"
  local ordinal_expression="${2:-}"
  if [ -z "$ordinal_expression" ]; then
    ordinal_expression='[0-9]{3,}'
  fi
  grep -oE '[A-Za-z0-9_-]+' \
    | grep -E "^(${prefixes})-${ordinal_expression}$" \
    || true
}

line_has_element_id() {
  local line="$1"
  local element_id="$2"
  printf '%s\n' "$line" \
    | grep -oE '[A-Za-z0-9_-]+' \
    | grep -Fxq -- "$element_id"
}

first_line_with_element_id() {
  local path="$1"
  local element_id="$2"
  local line
  while IFS= read -r line; do
    if line_has_element_id "$line" "$element_id"; then
      printf '%s\n' "$line"
      return 0
    fi
  done < "$path"
  return 1
}

count_lines_with_element_id() {
  local path="$1"
  local element_id="$2"
  awk -v element_id="$element_id" '
    {
      line = $0
      gsub(/[^A-Za-z0-9_-]+/, " ", line)
      count = split(line, tokens, / +/)
      for (item = 1; item <= count; item++) {
        if (tokens[item] == element_id) {
          matches++
          break
        }
      }
    }
    END { print matches + 0 }
  ' "$path"
}
