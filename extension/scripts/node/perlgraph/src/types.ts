export type Confidence = 'high' | 'medium' | 'low' | 'dynamic';

export type SymbolKind =
  | 'file'
  | 'package'
  | 'sub'
  | 'method'
  | 'test'
  | 'constant'
  | 'variable';

export type RelationshipKind =
  | 'declares'
  | 'imports'
  | 'requires'
  | 'inherits'
  | 'uses_role'
  | 'calls'
  | 'tests'
  | 'references';

export type IndexState = 'ready' | 'degraded' | 'empty' | 'failed';

export interface SourceRange {
  file_path: string;
  line_start: number;
  line_end: number;
}

export interface PerlSymbol extends SourceRange {
  qualified_name: string;
  name: string;
  kind: SymbolKind;
  language: 'perl';
  signature?: string;
  provenance: string[];
}

export interface PerlRelationship {
  source: string;
  target: string;
  kind: RelationshipKind;
  file_path: string;
  line_start: number;
  confidence: Confidence;
  provenance: string[];
  notes?: string;
}

export interface UnsupportedPattern {
  kind: 'autoload' | 'eval_string' | 'symbolic_ref' | 'dynamic_require' | 'glob_assignment';
  file_path: string;
  line_start: number;
  snippet: string;
  notes: string;
}

export interface ParseFailure {
  file_path: string;
  error: string;
}

export interface IndexStats {
  total_files: number;
  parsed_files: number;
  failed_files: number;
  symbol_count: number;
  relationship_count: number;
  dynamic_pattern_count: number;
  index_state: IndexState;
}

export interface ModuleGraphEntry {
  source_module: string;
  target_module: string;
  source_file: string;
  target_file?: string;
  kind: 'use' | 'require' | 'parent' | 'base';
  confidence: Confidence;
}

export interface PerlGraphAnalysis {
  schema_version: 1;
  tool: 'perlgraph';
  generated_at: string;
  repo_path: string;
  supported: boolean;
  language_coverage: Record<string, 'supported'>;
  symbols: PerlSymbol[];
  relationships: PerlRelationship[];
  call_graph: Array<Pick<PerlRelationship, 'source' | 'target' | 'confidence' | 'provenance'>>;
  module_graph: ModuleGraphEntry[];
  unsupported_patterns: UnsupportedPattern[];
  parse_failures: ParseFailure[];
  index_stats: IndexStats;
}

export interface PerlGraphSummary {
  schema_version: 1;
  tool: 'perlgraph';
  generated_at: string;
  repo_path: string;
  index_state: IndexState;
  index_stats: IndexStats;
  symbol_kinds: Array<{ kind: SymbolKind; count: number }>;
  relationship_kinds: Array<{ kind: RelationshipKind; count: number }>;
  top_callers: Array<{ symbol: string; outgoing_calls: number }>;
  top_callees: Array<{ symbol: string; incoming_calls: number }>;
  top_modules: Array<{ module: string; outgoing_dependencies: number }>;
  dynamic_risk: {
    count: number;
    patterns: Array<{ kind: UnsupportedPattern['kind']; count: number }>;
  };
}
