import { describe, expect, it } from 'vitest';
import { extractPerlFile } from '../src/extraction/perl-extractor.js';

const SOURCE = `package My::App;
use strict;
use warnings;
use My::Service;
use parent 'My::Base';

sub new {
  my ($class) = @_;
  return bless {}, $class;
}

sub run {
  my ($self) = @_;
  return My::Service::execute();
}

package My::App::Util;

sub helper {
  return 1;
}
`;

describe('Perl extractor', () => {
  it('extracts packages, subs, methods, and dependencies', () => {
    const result = extractPerlFile('lib/My/App.pm', SOURCE);

    expect(result.symbols.map((symbol) => [symbol.kind, symbol.qualified_name, symbol.line_start])).toEqual([
      ['file', 'lib/My/App.pm', 1],
      ['package', 'My::App', 1],
      ['method', 'My::App::new', 7],
      ['method', 'My::App::run', 12],
      ['package', 'My::App::Util', 17],
      ['sub', 'My::App::Util::helper', 19]
    ]);

    expect(result.dependencies).toEqual([
      { source_module: 'My::App', target_module: 'strict', source_file: 'lib/My/App.pm', kind: 'use', line_start: 2 },
      { source_module: 'My::App', target_module: 'warnings', source_file: 'lib/My/App.pm', kind: 'use', line_start: 3 },
      { source_module: 'My::App', target_module: 'My::Service', source_file: 'lib/My/App.pm', kind: 'use', line_start: 4 },
      { source_module: 'My::App', target_module: 'My::Base', source_file: 'lib/My/App.pm', kind: 'parent', line_start: 5 }
    ]);
  });

  it('detects dynamic patterns', () => {
    const result = extractPerlFile('lib/Dynamic.pm', [
      'package Dynamic;',
      'our $AUTOLOAD;',
      'sub AUTOLOAD { }',
      'eval $code;',
      'require $module;',
      '*{caller() . "::x"} = sub { 1 };'
    ].join('\n'));

    expect(result.unsupported_patterns.map((pattern) => pattern.kind)).toEqual([
      'autoload',
      'eval_string',
      'dynamic_require',
      'glob_assignment'
    ]);
  });
});
