declare module 'tree-sitter-perl' {
  import type Parser from 'tree-sitter';
  const language: Parser.Language;
  export = language;
}
