"""Echelon artifact tools over the shared Prosaic transport and agent loop."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from collections.abc import Mapping
import json
import socket
import urllib.request
import urllib.error

from prosaic_runtime import openai_compatible as _runtime
from prosaic_runtime.config import EndpointConfig
from prosaic_runtime.openai_compatible import (
    _OpenAITool, _object_schema, _feature_enabled, _feature_int, _feature_str,
    _str_arg, _int_arg, _mapping_str, _tool_error, _tool_result_message,
    _validate_web_url, _http_status, _raw_response_headers, _decode_web_body,
    _html_to_text, _http_get_text, _parse_search_results, _with_query_param,
)
from harness.llm_tool_policy import inject_llm_tool_policy_preamble
from harness.ai_cli_backends.openai_compatible_transcript import open_provider_transcript

# Tool-use guidance only. Final-response contracts belong to the caller's
# rendered prose; artifact reads and assignment-bound delivery are not legacy
# COMMANDER dispatches and must not be instructed to emit echelon_result YAML.
_OPENAI_COMPATIBLE_TOOL_GUIDANCE = (
    "Prefer bulk context tools first when inspecting Echelon RE or artifact runs. "
    "Use read_re_analysis_pack for run-level context, read_domain_pack for one "
    "source/domain, codegraph_context or perlgraph_context for graph summaries, "
    "grep_context for search with surrounding lines, read_many_files for known "
    "file sets, and list_tree_with_sizes before broad file reads. Keep tool calls "
    "purposeful and return the final artifact once enough evidence is available. "
    "Use sha256_file when an artifact requires an exact digest of an on-disk source, "
    "especially after writing or editing that source. "
    "Treat rejected out-of-scope reads and empty search results as authoritative; do "
    "not retry them or broaden scope. When owned tests are absent, report them as "
    "not-observed instead of searching elsewhere."
)


class OpenAICompatibleBackend(_runtime.OpenAICompatibleBackend):
    def __init__(self, config):
        self._echelon_config = config
        llm = config.llm
        super().__init__(EndpointConfig(
            base_url=llm.base_url, model=llm.model,
            api_key_env=llm.api_key_env, api_key_file=llm.api_key_file,
            temperature=llm.temperature, max_tokens=llm.max_tokens,
            features=llm.features,
        ))

    def prepare_constrained_prompt(self, request):
        policy = replace(self._echelon_config.llm.tool_policy,
                         allow_unsafe_host_execution=False, approval_reason=None)
        return inject_llm_tool_policy_preamble(request.prompt, policy)

    def make_registry(self, cwd, features, metadata):
        return _OpenAIToolRegistry(cwd, features, metadata)

    def open_transcript(self, request):
        return open_provider_transcript(Path(request.cwd), self._config.features, request.metadata)

    def tool_guidance(self):
        return _OPENAI_COMPATIBLE_TOOL_GUIDANCE


class _OpenAIToolRegistry(_runtime._OpenAIToolRegistry):
    """Legacy Echelon permissions remain caller-owned; explicit scopes narrow them."""
    def __init__(self, cwd, features, prompt_metadata=None):
        metadata = dict(prompt_metadata or {})
        if "allowed_tools" not in metadata:
            metadata["allowed_tools"] = [tool.name for tool in self._tools_for_features(features)] + ["echelon_result"]
        declaration = metadata.get("tools")
        if "tools" in metadata:
            allowed = set(metadata["allowed_tools"])
            if declaration == "read":
                allowed -= {"write_file", "edit_file"}
            elif declaration in ("", None, "none"):
                allowed = {"echelon_result"}
            elif declaration not in ("write", "full"):
                raise ValueError(f"Unsupported Prosaic tools declaration: {declaration}")
            metadata["allowed_tools"] = sorted(allowed)
        if not metadata.get("tool_read_roots"):
            metadata["tool_read_roots"] = [str(cwd)]
        self._exclusive = metadata.get("tool_write_scope_exclusive") is True
        super().__init__(cwd, features, metadata)

    def _tools_for_features(self, features):
        self._features = features
        return self._tools()

    def _require_write_scope(self, path):
        if not self._write_scope_paths and not self._exclusive:
            if self._inside_forbidden_scope(path):
                raise ValueError(f"Path is inside forbidden provider control plane: {self._rel(path)}")
            return
        super()._require_write_scope(path)

    def _execute(self, name, args):
        if name == "echelon_result":
            return {"status": "retry", "code": "result_contract_not_tool",
                    "instruction": "echelon_result is not a callable tool. Return it now as the final YAML response block. Do not call more tools and do not add prose around it."}
        handlers = {
            "read_re_analysis_pack": self._read_re_analysis_pack,
            "read_domain_pack": self._read_domain_pack,
            "codegraph_context": self._codegraph_context,
            "perlgraph_context": self._perlgraph_context,
            "fetch_url": self._fetch_url,
            "web_search": self._web_search,
        }
        if name in handlers:
            return handlers[name](args)
        return super()._execute(name, args)

    def _read_re_analysis_pack(self, args: dict[str, object]) -> dict[str, object]:
        run_dir = self._path_arg(args, key="run_dir")
        self._require_read_scope(run_dir)
        max_chars = _int_arg(
            args,
            "max_chars_per_file",
            default=80_000,
            minimum=1_000,
            maximum=500_000,
        )
        files, missing, truncated = self._read_pack_files(
            run_dir,
            [
                "re-execution-plan.json",
                "re-source-index.json",
                "re-workspace-inputs.json",
                "workspace/domain-catalog.md",
                "workspace/architecture-map.json",
                "workspace/workspace-manifest.json",
                "workspace/repos-manifest.json",
                "workspace/cross-repo.json",
                "analysis.json",
                "re-analysis-manifest.json",
            ],
            max_chars=max_chars,
        )
        return {
            "status": "ok",
            "run_dir": self._rel(run_dir),
            "files": files,
            "missing": missing,
            "truncated": truncated,
        }

    def _read_domain_pack(self, args: dict[str, object]) -> dict[str, object]:
        run_dir = self._path_arg(args, key="run_dir")
        self._require_read_scope(run_dir)
        source_id = _str_arg(args, "source_id", default="")
        domain_id = _str_arg(args, "domain_id", default="")
        if not source_id:
            raise ValueError("read_domain_pack requires source_id")
        if not domain_id:
            raise ValueError("read_domain_pack requires domain_id")
        max_files = _int_arg(args, "max_files", default=200, minimum=1, maximum=2_000)
        max_chars = _int_arg(
            args,
            "max_chars_per_file",
            default=80_000,
            minimum=1_000,
            maximum=500_000,
        )
        source_run_dir = run_dir / "sources" / source_id
        manifest_path = source_run_dir / "domain-manifest.json"
        manifest = self._read_json_file(manifest_path)
        domain_entry = self._domain_entry(manifest, domain_id)
        owned_root = _mapping_str(domain_entry, "root") or _mapping_str(
            domain_entry,
            "owned_root",
        )
        if not owned_root:
            owned_root = _mapping_str(domain_entry, "path") or "."
        source_root = self._source_root_from_index(run_dir, source_id)
        domain_source_root = (source_root / owned_root).resolve(strict=False)
        if not self._inside_root(domain_source_root):
            raise ValueError(f"Domain source root escapes provider root: {owned_root}")
        self._require_read_scope(domain_source_root)
        source_files = self._tree_files(domain_source_root, max_entries=max_files)
        target_spec = self._file_payload(
            source_run_dir / "specs" / domain_id / "spec.md",
            max_chars=max_chars,
        )
        analysis = self._file_payload(source_run_dir / "analysis.json", max_chars=max_chars)
        return {
            "status": "ok",
            "run_dir": self._rel(run_dir),
            "source_id": source_id,
            "domain_id": domain_id,
            "owned_root": owned_root,
            "domain_manifest": self._file_payload(manifest_path, max_chars=max_chars),
            "analysis": analysis,
            "target_spec": target_spec,
            "source_files": source_files,
            "truncated": len(source_files) >= max_files,
        }

    def _codegraph_context(self, args: dict[str, object]) -> dict[str, object]:
        return self._graph_context(
            args,
            [
                "codegraph-summary.json",
                "codegraph-analysis.json",
                "codegraph-index.json",
            ],
        )

    def _perlgraph_context(self, args: dict[str, object]) -> dict[str, object]:
        return self._graph_context(
            args,
            [
                "perlgraph-summary.json",
                "perlgraph-analysis.json",
                "perlgraph-index.json",
            ],
        )

    def _graph_context(
        self,
        args: dict[str, object],
        file_names: list[str],
    ) -> dict[str, object]:
        run_dir = self._path_arg(args, key="run_dir")
        self._require_read_scope(run_dir)
        source_id = _str_arg(args, "source_id", default="")
        if not source_id:
            raise ValueError("graph context tools require source_id")
        max_chars = _int_arg(
            args,
            "max_chars_per_file",
            default=80_000,
            minimum=1_000,
            maximum=500_000,
        )
        files: dict[str, str] = {}
        missing: list[str] = []
        truncated = False
        for file_name in file_names:
            path = run_dir / "sources" / source_id / file_name
            if not path.is_file() or not self._inside_root(path):
                missing.append(file_name)
                continue
            payload = self._file_payload(path, max_chars=max_chars)
            content = payload.get("content")
            if isinstance(content, str):
                files[file_name] = content
            truncated = truncated or bool(payload.get("truncated"))
        return {
            "status": "ok",
            "run_dir": self._rel(run_dir),
            "source_id": source_id,
            "files": files,
            "missing": missing,
            "truncated": truncated,
        }

    def _fetch_url(self, args: dict[str, object]) -> dict[str, object]:
        url = _str_arg(args, "url", default="")
        if not url:
            raise ValueError("fetch_url requires url")
        _validate_web_url(url)
        max_chars = _int_arg(
            args,
            "max_chars",
            default=20_000,
            minimum=1,
            maximum=100_000,
        )
        timeout_s = _feature_int(
            self._features,
            "web_timeout_s",
            default=10,
            minimum=1,
            maximum=60,
        )
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "EchelonOpenAICompatibleProvider/1.0"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                body = response.read()
                status = _http_status(response)
                headers = _raw_response_headers(response)
        except urllib.error.HTTPError as exc:
            body = exc.read()
            return {
                "status": "error",
                "url": url,
                "http_status": int(exc.code),
                "error": body.decode("utf-8", errors="replace")[:max_chars] or str(exc),
            }
        except (TimeoutError, socket.timeout) as exc:
            return _tool_error(f"fetch_url timed out: {exc}")
        except urllib.error.URLError as exc:
            return _tool_error(f"fetch_url failed: {exc.reason}")
        except OSError as exc:
            return _tool_error(f"fetch_url failed: {exc}")
        text = _decode_web_body(body)
        content = _html_to_text(text)
        return {
            "status": "ok",
            "url": url,
            "http_status": status,
            "headers": headers,
            "content": content[:max_chars],
            "truncated": len(content) > max_chars,
        }

    def _web_search(self, args: dict[str, object]) -> dict[str, object]:
        query = _str_arg(args, "query", default="")
        if not query:
            raise ValueError("web_search requires query")
        max_results = _int_arg(
            args,
            "max_results",
            default=5,
            minimum=1,
            maximum=10,
        )
        search_base = _feature_str(
            self._features,
            "web_search_url",
            default="https://duckduckgo.com/html/",
        )
        _validate_web_url(search_base)
        url = _with_query_param(search_base, "q", query)
        timeout_s = _feature_int(
            self._features,
            "web_timeout_s",
            default=10,
            minimum=1,
            maximum=60,
        )
        try:
            raw_html = _http_get_text(url, timeout_s=timeout_s)
        except ValueError as exc:
            return _tool_error(str(exc))
        except (TimeoutError, socket.timeout) as exc:
            return _tool_error(f"web_search timed out: {exc}")
        except urllib.error.HTTPError as exc:
            return _tool_error(f"web_search failed: HTTP {int(exc.code)}")
        except urllib.error.URLError as exc:
            return _tool_error(f"web_search failed: {exc.reason}")
        except OSError as exc:
            return _tool_error(f"web_search failed: {exc}")
        results = _parse_search_results(raw_html, max_results)
        return {
            "status": "ok",
            "query": query,
            "search_url": url,
            "results": results,
        }

    def _read_pack_files(
        self,
        base: Path,
        relative_paths: list[str],
        *,
        max_chars: int,
    ) -> tuple[dict[str, str], list[str], bool]:
        files: dict[str, str] = {}
        missing: list[str] = []
        truncated = False
        for relative in relative_paths:
            path = (base / relative).resolve(strict=False)
            if not self._inside_root(path) or not path.is_file():
                missing.append(relative)
                continue
            payload = self._file_payload(path, max_chars=max_chars)
            content = payload.get("content")
            if isinstance(content, str):
                files[relative] = content
            truncated = truncated or bool(payload.get("truncated"))
        return files, missing, truncated

    def _file_payload(self, path: Path, *, max_chars: int) -> dict[str, object]:
        if not self._inside_root(path):
            return {
                "status": "error",
                "path": str(path),
                "error": "path escapes provider root",
            }
        if not path.is_file():
            return {
                "status": "missing",
                "path": self._rel(path),
                "content": "",
                "truncated": False,
            }
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return {
                "status": "error",
                "path": self._rel(path),
                "error": str(exc),
            }
        return {
            "status": "ok",
            "path": self._rel(path),
            "content": content[:max_chars],
            "truncated": len(content) > max_chars,
        }

    def _read_json_file(self, path: Path) -> object:
        if not path.is_file() or not self._inside_root(path):
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _domain_entry(self, manifest: object, domain_id: str) -> Mapping[str, object]:
        if not isinstance(manifest, Mapping):
            return {}
        domains = manifest.get("domains")
        if not isinstance(domains, list):
            return {}
        for item in domains:
            if not isinstance(item, Mapping):
                continue
            item_id = (
                _mapping_str(item, "domain_id")
                or _mapping_str(item, "id")
                or _mapping_str(item, "name")
            )
            if item_id == domain_id:
                return item
        return {}

    def _source_root_from_index(self, run_dir: Path, source_id: str) -> Path:
        index = self._read_json_file(run_dir / "re-source-index.json")
        source_entry = self._source_index_entry(index, source_id)
        raw_path = _mapping_str(source_entry, "absolute_path")
        if not raw_path:
            raw_path = _mapping_str(source_entry, "path")
        if not raw_path:
            raw_path = f"sources/{source_id}"
        return self._resolve_path_value(raw_path)

    def _source_index_entry(self, index: object, source_id: str) -> Mapping[str, object]:
        if not isinstance(index, Mapping):
            return {}
        sources = index.get("sources")
        if not isinstance(sources, list):
            return {}
        for item in sources:
            if not isinstance(item, Mapping):
                continue
            item_id = (
                _mapping_str(item, "id")
                or _mapping_str(item, "source_id")
                or _mapping_str(item, "name")
            )
            if item_id == source_id:
                return item
        return {}

    def _tree_files(self, base: Path, *, max_entries: int) -> list[dict[str, object]]:
        files: list[dict[str, object]] = []
        if not base.exists():
            return files
        candidates = [base] if base.is_file() else sorted(base.rglob("*"))
        for path in candidates:
            if len(files) >= max_entries:
                break
            if (
                not path.is_file()
                or not self._inside_root(path)
                or not self._path_filter.visible_file(path)
            ):
                continue
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            files.append({"path": self._rel(path), "size": size})
        return files

    def _tools(self):
        tools = super()._tools() + [
            _OpenAITool(
                "read_domain_pack",
                "Read an RE source/domain context pack: manifest, analysis, target spec, and source file list.",
                _object_schema({
                    "run_dir": {"type": "string"},
                    "source_id": {"type": "string"},
                    "domain_id": {"type": "string"},
                    "max_files": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 2000,
                    },
                    "max_chars_per_file": {
                        "type": "integer",
                        "minimum": 1000,
                        "maximum": 500000,
                    },
                }, required=["run_dir", "source_id", "domain_id"]),
            ),
            _OpenAITool(
                "read_re_analysis_pack",
                "Read high-value RE run-level planning, index, workspace, and catalog files in one call.",
                _object_schema({
                    "run_dir": {"type": "string"},
                    "max_chars_per_file": {
                        "type": "integer",
                        "minimum": 1000,
                        "maximum": 500000,
                    },
                }, required=["run_dir"]),
            ),
            _OpenAITool(
                "codegraph_context",
                "Read available codegraph summary, analysis, and index files for one RE source.",
                _object_schema({
                    "run_dir": {"type": "string"},
                    "source_id": {"type": "string"},
                    "max_chars_per_file": {
                        "type": "integer",
                        "minimum": 1000,
                        "maximum": 500000,
                    },
                }, required=["run_dir", "source_id"]),
            ),
            _OpenAITool(
                "perlgraph_context",
                "Read available perlgraph summary, analysis, and index files for one RE source.",
                _object_schema({
                    "run_dir": {"type": "string"},
                    "source_id": {"type": "string"},
                    "max_chars_per_file": {
                        "type": "integer",
                        "minimum": 1000,
                        "maximum": 500000,
                    },
                }, required=["run_dir", "source_id"]),
            ),
        ]
        if _feature_enabled(self._features, "web_tools", default=False):
            tools.extend([
                _OpenAITool(
                    "web_search",
                    "Search the public web and return a small list of result titles and URLs.",
                    _object_schema({
                        "query": {"type": "string"},
                        "max_results": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 10,
                        },
                    }, required=["query"]),
                ),
                _OpenAITool(
                    "fetch_url",
                    "Fetch a public HTTP(S) URL and return bounded readable text.",
                    _object_schema({
                        "url": {"type": "string"},
                        "max_chars": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 100000,
                        },
                    }, required=["url"]),
                ),
            ])
        return tools

def __getattr__(name):
    # Transitional compatibility for existing Echelon diagnostics and tests.
    return getattr(_runtime, name)
