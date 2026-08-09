---
description: Generate entity relationship diagrams from spec requirements — extract actors, actions, and objects and visualize their relationships.
---

## Role

You are COMMANDER generating entity relationship diagrams from spec requirements — extract actors, actions, and objects and visualize their relationships.

---

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty).

## Goal

Extract entities (actors, actions, objects) from requirements and generate a relationship diagram. This visualizes who does what to whom — useful for validating spec completeness and finding missing interactions.

## Prerequisites

The `understanding` CLI tool must be installed. For image export, the system `graphviz` package is also needed:

```bash
# macOS
brew install graphviz

# Ubuntu/Debian
sudo apt-get install graphviz
```

## Execution Steps

### 1. Locate Spec

```bash
SPEC_PATH="${ARGUMENTS:-}"

if [ -z "$SPEC_PATH" ]; then
  SPECS_DIR="specs"
  if [ -d "$SPECS_DIR" ]; then
    LATEST=$(ls -d "$SPECS_DIR"/[0-9]*/ 2>/dev/null | sort -r | head -1)
    SPEC_PATH="${LATEST}spec.md"
  fi
fi

if [ ! -f "$SPEC_PATH" ]; then
  echo "No spec.md found. Provide a path: /echelon.understanding-diagram path/to/spec.md"
  exit 1
fi
```

### 2. Determine Output Format

Check user $ARGUMENTS for an explicit output path or format, then fall back to extension config:

- If $ARGUMENTS contains a file path (e.g., `diagram.png`), use `--diagram <path>`
- If config `diagram` is a string path, use `--diagram <config value>`
- Otherwise, default to `--diagram text` for ASCII output in terminal

Supported export formats (determined by file extension): `.png`, `.svg`, `.pdf`

### 3. Run Diagram Generation

```bash
# ASCII in terminal
understanding "$SPEC_PATH" --diagram text

# Export to file
understanding "$SPEC_PATH" --diagram diagram.png
```

### 4. Interpret Results

The diagram shows:
- **Actors** (boxes): Who performs actions — users, systems, services
- **Actions** (edges): What is done — verbs extracted from requirements
- **Objects** (boxes): What is acted upon — data, resources, components
- **Relationships**: Actor → Action → Object connections

Review the diagram for:
- **Orphan actors**: Actors mentioned but with no actions (incomplete spec)
- **Orphan objects**: Objects with no actor acting on them (missing requirements)
- **Missing actors**: Actions without a clear subject ("the system" is often implicit)
- **Clusters**: Groups of related entities that might represent distinct features

### 5. Suggest Improvements

If the diagram reveals gaps:
- Suggest adding requirements to cover orphan entities
- Identify implicit actors that should be made explicit
- Flag objects that appear in many relationships (potential coupling risk)

## Notes

- ASCII (`text`) output works everywhere — no graphviz system package needed
- Image export requires the `graphviz` system package
- Entity extraction uses NLP by default; `--basic` mode uses regex patterns only
- Combine with `--json` to get entity data as structured JSON
