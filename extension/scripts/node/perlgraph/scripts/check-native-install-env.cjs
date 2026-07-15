const nodeMajor = Number.parseInt(process.versions.node.split('.')[0] ?? '0', 10);
const cxxflags = process.env.CXXFLAGS ?? '';
const isDryRun = process.env.npm_config_dry_run === 'true';
const hasCxx20 = /(?:^|\s)-std=(?:c\+\+20|gnu\+\+20)(?:\s|$)/.test(cxxflags);

if (!isDryRun && nodeMajor >= 26 && !hasCxx20) {
  console.error([
    'PerlGraph uses tree-sitter@0.25.0 because tree-sitter-perl@1.1.2 is generated with Tree-sitter ABI 15.',
    'On Node 26, tree-sitter may need a native rebuild with C++20 enabled.',
    '',
    'Run installs with:',
    '  CXXFLAGS=-std=c++20 npm install',
    '  CXXFLAGS=-std=c++20 npm ci',
    '',
    'This guard intentionally fails before node-gyp emits a long compiler error.'
  ].join('\n'));
  process.exit(1);
}
