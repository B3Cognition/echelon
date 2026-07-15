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

  it('extracts multiple static parent and base inheritance targets', () => {
    const result = extractPerlFile('lib/My/Child.pm', [
      'package My::Child;',
      'use parent -norequire, "My::BaseOne", "My::BaseTwo";',
      'use base qw(My::LegacyOne My::LegacyTwo);',
      '1;'
    ].join('\n'));

    expect(result.dependencies).toEqual([
      { source_module: 'My::Child', target_module: 'My::BaseOne', source_file: 'lib/My/Child.pm', kind: 'parent', line_start: 2 },
      { source_module: 'My::Child', target_module: 'My::BaseTwo', source_file: 'lib/My/Child.pm', kind: 'parent', line_start: 2 },
      { source_module: 'My::Child', target_module: 'My::LegacyOne', source_file: 'lib/My/Child.pm', kind: 'base', line_start: 3 },
      { source_module: 'My::Child', target_module: 'My::LegacyTwo', source_file: 'lib/My/Child.pm', kind: 'base', line_start: 3 }
    ]);
  });

  it('detects dynamic patterns', () => {
    const result = extractPerlFile('lib/Dynamic.pm', [
      'package Dynamic;',
      'our $AUTOLOAD;',
      'our %AUTOLOAD_MAP = (run => "My::Service::run");',
      'sub AUTOLOAD { }',
      'eval $code;',
      'require $module;',
      '*{caller() . "::x"} = sub { 1 };',
      '${$symbol} = 1;',
      '$obj->$method();',
      '${$pkg}->run();'
    ].join('\n'));

    expect(result.unsupported_patterns.map((pattern) => pattern.kind)).toEqual([
      'autoload_dispatch_map',
      'autoload',
      'eval_string',
      'dynamic_require',
      'glob_assignment',
      'symbolic_ref',
      'dynamic_method',
      'symbolic_ref',
      'symbolic_method_receiver'
    ]);
  });

  it('ignores dynamic method syntax inside strings and comments', () => {
    const result = extractPerlFile('lib/Strings.pm', [
      'package Strings;',
      'sub run {',
      '  print STDERR "$key -> $value";',
      '  # $self->$commented;',
      '  return $self->$method();',
      '}'
    ].join('\n'));

    expect(result.unsupported_patterns).toEqual([{
      kind: 'dynamic_method',
      file_path: 'lib/Strings.pm',
      line_start: 5,
      snippet: 'return $self->$method();',
      notes: 'Dynamic method name cannot be statically resolved'
    }]);
  });

  it('attaches static target evidence to literal typeglob assignments', () => {
    const result = extractPerlFile('t/Glob.t', [
      'package Glob;',
      '*{"${caller}::qlog"} = sub { };',
      '*{"${caller}::${const}"} = sub () { 0 };'
    ].join('\n'));

    expect(result.unsupported_patterns).toEqual([
      {
        kind: 'glob_assignment',
        file_path: 't/Glob.t',
        line_start: 2,
        snippet: '*{"${caller}::qlog"} = sub { };',
        notes: 'Typeglob assignment may alter the symbol table; static target evidence for: qlog',
        targets: ['qlog']
      },
      {
        kind: 'glob_assignment',
        file_path: 't/Glob.t',
        line_start: 3,
        snippet: '*{"${caller}::${const}"} = sub () { 0 };',
        notes: 'Typeglob assignment may alter the symbol table'
      }
    ]);
  });

  it('classifies eval string require as dynamic require evidence', () => {
    const result = extractPerlFile('lib/DynamicRequire.pm', [
      'package DynamicRequire;',
      'eval "require $class" or die $@;',
      'eval "require ${ \\ $self->game_class }";',
      'eval "use JavaScript::Packer";',
      'eval $term;',
      'require 5.005_62;',
      'require $module;'
    ].join('\n'));

    expect(result.dependencies).toEqual([]);
    expect(result.unsupported_patterns).toEqual([
      {
        kind: 'dynamic_require',
        file_path: 'lib/DynamicRequire.pm',
        line_start: 2,
        snippet: 'eval "require $class" or die $@;',
        notes: 'String eval performs a dynamic require target that cannot be statically resolved'
      },
      {
        kind: 'dynamic_require',
        file_path: 'lib/DynamicRequire.pm',
        line_start: 3,
        snippet: 'eval "require ${ \\ $self->game_class }";',
        notes: 'String eval performs a dynamic require target that cannot be statically resolved'
      },
      {
        kind: 'dynamic_use',
        file_path: 'lib/DynamicRequire.pm',
        line_start: 4,
        snippet: 'eval "use JavaScript::Packer";',
        notes: 'String eval performs a dynamic use statement that cannot be statically resolved'
      },
      {
        kind: 'eval_string',
        file_path: 'lib/DynamicRequire.pm',
        line_start: 5,
        snippet: 'eval $term;',
        notes: 'String eval cannot be statically resolved'
      },
      {
        kind: 'dynamic_require',
        file_path: 'lib/DynamicRequire.pm',
        line_start: 7,
        snippet: 'require $module;',
        notes: 'Dynamic require target cannot be statically resolved'
      }
    ]);
  });

  it('extracts static AUTOLOAD accessor fields while keeping AUTOLOAD diagnostic', () => {
    const result = extractPerlFile('lib/Opta/Base.pm', [
      'package Opta::Base;',
      'our $AUTOLOAD;',
      'our %fields = (',
      '  competition_id => undef,',
      '  debug          => 0,',
      '  "game_id"      => undef,',
      ');',
      'sub new {',
      '  my ($class) = @_;',
      '  return bless { _permitted => \\%fields, %fields }, $class;',
      '}',
      'sub AUTOLOAD {',
      '  my $self = shift;',
      '  my $name = $AUTOLOAD;',
      '  $name =~ s/.*://;',
      '  unless ( exists $self->{_permitted}->{$name} ) { die $name }',
      '  return @_ ? $self->{$name} = shift : $self->{$name};',
      '}'
    ].join('\n'));

    expect(result.symbols).toContainEqual({
      qualified_name: 'Opta::Base::competition_id',
      name: 'competition_id',
      kind: 'method',
      language: 'perl',
      file_path: 'lib/Opta/Base.pm',
      line_start: 4,
      line_end: 4,
      signature: 'AUTOLOAD accessor competition_id',
      provenance: ['autoload-accessor', 'line-scan']
    });
    expect(result.symbols).toContainEqual({
      qualified_name: 'Opta::Base::game_id',
      name: 'game_id',
      kind: 'method',
      language: 'perl',
      file_path: 'lib/Opta/Base.pm',
      line_start: 6,
      line_end: 6,
      signature: 'AUTOLOAD accessor game_id',
      provenance: ['autoload-accessor', 'line-scan']
    });
    expect(result.unsupported_patterns).toContainEqual({
      kind: 'autoload',
      file_path: 'lib/Opta/Base.pm',
      line_start: 12,
      snippet: 'sub AUTOLOAD {',
      notes: 'AUTOLOAD dispatch cannot be statically resolved; static accessor evidence for: competition_id, debug, game_id',
      targets: ['competition_id', 'debug', 'game_id']
    });
  });

  it('does not report ordinary array and hash dereferences as symbolic refs', () => {
    const result = extractPerlFile('lib/Refs.pm', [
      'package Refs;',
      'sub run {',
      '  my ($rows, $task, $symbol) = @_;',
      '  push @{$rows}, 1;',
      '  my %copy = %{$task};',
      '  foreach my $row (@{$rows}) { }',
      '  ${$symbol} = 1;',
      '}'
    ].join('\n'));

    expect(result.unsupported_patterns).toEqual([{
      kind: 'symbolic_ref',
      file_path: 'lib/Refs.pm',
      line_start: 7,
      snippet: '${$symbol} = 1;',
      notes: 'Symbolic reference target cannot be statically resolved'
    }]);
  });

  it('annotates bare calls that match explicit import lists', () => {
    const result = extractPerlFile('lib/My/App.pm', [
      'package My::App;',
      'use JSON qw(decode_json encode_json);',
      'use Test::More qw(is use_ok);',
      'sub run {',
      '  decode_json($payload);',
      '  is($actual, $expected);',
      '  helper();',
      '}',
      'sub helper { return 1; }'
    ].join('\n'));

    expect(result.calls).toEqual([
      {
        caller: 'My::App::run',
        expression: 'decode_json',
        imported_from: 'JSON',
        file_path: 'lib/My/App.pm',
        line_start: 5
      },
      {
        caller: 'My::App::run',
        expression: 'is',
        imported_from: 'Test::More',
        file_path: 'lib/My/App.pm',
        line_start: 6
      },
      {
        caller: 'My::App::run',
        expression: 'helper',
        file_path: 'lib/My/App.pm',
        line_start: 7
      }
    ]);
  });

  it('expands bounded dynamic self dispatch over static qw lists', () => {
    const result = extractPerlFile('lib/My/App.pm', [
      'package My::App;',
      'sub run {',
      '  my ($self) = @_;',
      '  my ($game_id, $team_id) = map { $self->$_ } qw/_game_id team_id/;',
      '  my %kw = map { $_ => $self->$_ } qw[season_id competition_id];',
      '  return $self->$method(@args);',
      '}'
    ].join('\n'));

    expect(result.calls).toEqual([
      {
        caller: 'My::App::run',
        expression: '$self->_game_id',
        file_path: 'lib/My/App.pm',
        line_start: 4
      },
      {
        caller: 'My::App::run',
        expression: '$self->team_id',
        file_path: 'lib/My/App.pm',
        line_start: 4
      },
      {
        caller: 'My::App::run',
        expression: '$self->season_id',
        file_path: 'lib/My/App.pm',
        line_start: 5
      },
      {
        caller: 'My::App::run',
        expression: '$self->competition_id',
        file_path: 'lib/My/App.pm',
        line_start: 5
      }
    ]);
    expect(result.unsupported_patterns).toEqual([{
      kind: 'dynamic_method',
      file_path: 'lib/My/App.pm',
      line_start: 6,
      snippet: 'return $self->$method(@args);',
      notes: 'Dynamic method name cannot be statically resolved'
    }]);
  });

  it('expands bounded dynamic self dispatch from local static arrays', () => {
    const result = extractPerlFile('lib/My/App.pm', [
      'package My::App;',
      'sub report {',
      '  my ($self, $config) = @_;',
      '  my @attributes = qw(match_id team_id);',
      '  my %kw = map { $_ => $self->$_ } @attributes;',
      '  my @runtime = split /,/, $config;',
      '  my %dynamic = map { $_ => $self->$_ } @runtime;',
      '}'
    ].join('\n'));

    expect(result.calls).toEqual([
      {
        caller: 'My::App::report',
        expression: '$self->match_id',
        file_path: 'lib/My/App.pm',
        line_start: 5
      },
      {
        caller: 'My::App::report',
        expression: '$self->team_id',
        file_path: 'lib/My/App.pm',
        line_start: 5
      }
    ]);
    expect(result.unsupported_patterns).toEqual([{
      kind: 'dynamic_method',
      file_path: 'lib/My/App.pm',
      line_start: 7,
      snippet: 'my %dynamic = map { $_ => $self->$_ } @runtime;',
      notes: 'Dynamic method name cannot be statically resolved'
    }]);
  });

  it('expands bounded dynamic self dispatch from multiline static map lists', () => {
    const result = extractPerlFile('lib/My/App.pm', [
      'package My::App;',
      'sub load_from_omo {',
      '  my ($self) = @_;',
      '  my %meta = map {',
      '    $_ => $self->can("master")',
      '      ? $self->master->$_',
      '      : $self->$_',
      '    }',
      '    qw|season_id competition_id|;',
      '}'
    ].join('\n'));

    expect(result.calls).toEqual([
      {
        caller: 'My::App::load_from_omo',
        expression: '$self->can',
        file_path: 'lib/My/App.pm',
        line_start: 5
      },
      {
        caller: 'My::App::load_from_omo',
        expression: '$self->master',
        file_path: 'lib/My/App.pm',
        line_start: 6
      },
      {
        caller: 'My::App::load_from_omo',
        expression: '$self->season_id',
        file_path: 'lib/My/App.pm',
        line_start: 7
      },
      {
        caller: 'My::App::load_from_omo',
        expression: '$self->competition_id',
        file_path: 'lib/My/App.pm',
        line_start: 7
      }
    ]);
    expect(result.unsupported_patterns).toEqual([]);
  });

  it('expands bounded dynamic self dispatch from implicit foreach lists', () => {
    const result = extractPerlFile('lib/My/App.pm', [
      'package My::App;',
      'sub sync {',
      '  my ($self, $game) = @_;',
      '  foreach (qw|competition_id season_id game_system_id|) {',
      '    $self->$_($game->get($_));',
      '  }',
      '}'
    ].join('\n'));

    expect(result.calls).toEqual([
      {
        caller: 'My::App::sync',
        expression: '$self->competition_id',
        file_path: 'lib/My/App.pm',
        line_start: 5
      },
      {
        caller: 'My::App::sync',
        expression: '$self->season_id',
        file_path: 'lib/My/App.pm',
        line_start: 5
      },
      {
        caller: 'My::App::sync',
        expression: '$self->game_system_id',
        file_path: 'lib/My/App.pm',
        line_start: 5
      },
      {
        caller: 'My::App::sync',
        expression: '$game->get',
        file_path: 'lib/My/App.pm',
        line_start: 5
      }
    ]);
    expect(result.unsupported_patterns).toEqual([]);
  });

  it('expands can-guarded dynamic receiver dispatch from implicit foreach lists', () => {
    const result = extractPerlFile('lib/My/App.pm', [
      'package My::App;',
      'sub error_to_string {',
      '  my $error = shift;',
      '  foreach (qw/as_string to_string/) {',
      '    return $error->$_ if $error->can($_);',
      '  }',
      '  return $other->$method;',
      '}'
    ].join('\n'));

    expect(result.calls).toEqual([
      {
        caller: 'My::App::error_to_string',
        expression: '$error->as_string',
        file_path: 'lib/My/App.pm',
        line_start: 5
      },
      {
        caller: 'My::App::error_to_string',
        expression: '$error->to_string',
        file_path: 'lib/My/App.pm',
        line_start: 5
      },
      {
        caller: 'My::App::error_to_string',
        expression: '$error->can',
        file_path: 'lib/My/App.pm',
        line_start: 5
      }
    ]);
    expect(result.unsupported_patterns).toEqual([{
      kind: 'dynamic_method',
      file_path: 'lib/My/App.pm',
      line_start: 7,
      snippet: 'return $other->$method;',
      notes: 'Dynamic method name cannot be statically resolved'
    }]);
  });

  it('expands bounded dynamic self dispatch from static hash key loops', () => {
    const result = extractPerlFile('lib/My/App.pm', [
      'package My::App;',
      'our %parameters = (',
      '  competition_id => { column => "competition_id" },',
      '  season_id      => { column => "season_id" },',
      ');',
      'sub get_games {',
      '  my ($self, %runtime) = @_;',
      '  foreach my $param ( sort keys %parameters ) {',
      '    if ($self->$param()) {',
      '      return 1;',
      '    } elsif ($param eq "season_id" && $self->$param()) {',
      '      return 2;',
      '    }',
      '  }',
      '  foreach my $field ( keys %runtime ) {',
      '    $self->$field();',
      '  }',
      '}'
    ].join('\n'));

    expect(result.calls).toEqual([
      {
        caller: 'My::App::get_games',
        expression: '$self->competition_id',
        file_path: 'lib/My/App.pm',
        line_start: 9
      },
      {
        caller: 'My::App::get_games',
        expression: '$self->season_id',
        file_path: 'lib/My/App.pm',
        line_start: 9
      },
      {
        caller: 'My::App::get_games',
        expression: '$self->competition_id',
        file_path: 'lib/My/App.pm',
        line_start: 11
      },
      {
        caller: 'My::App::get_games',
        expression: '$self->season_id',
        file_path: 'lib/My/App.pm',
        line_start: 11
      }
    ]);
    expect(result.unsupported_patterns).toEqual([{
      kind: 'dynamic_method',
      file_path: 'lib/My/App.pm',
      line_start: 16,
      snippet: '$self->$field();',
      notes: 'Dynamic method name cannot be statically resolved'
    }]);
  });

  it('expands bounded dynamic self dispatch from local static variables and loops', () => {
    const result = extractPerlFile('lib/My/App.pm', [
      'package My::App;',
      'sub run {',
      '  my ($self, $runtime) = @_;',
      '  my $method = "build";',
      '  $self->$method();',
      '  my $read_method = $format eq "C" ? "read_uchar" : "read_short";',
      '  push @stats, $self->$read_method;',
      '  foreach my $reader (qw(read_header read_body)) {',
      '    $self->$reader();',
      '  }',
      '  foreach my $setting ("cipher", "header") {',
      '    if (defined $config->{$setting}) {',
      '      $self->$setting($config->{$setting});',
      '    }',
      '  }',
      '  return $self->$runtime();',
      '}'
    ].join('\n'));

    expect(result.calls).toEqual([
      {
        caller: 'My::App::run',
        expression: '$self->build',
        file_path: 'lib/My/App.pm',
        line_start: 5
      },
      {
        caller: 'My::App::run',
        expression: '$self->read_uchar',
        file_path: 'lib/My/App.pm',
        line_start: 7
      },
      {
        caller: 'My::App::run',
        expression: '$self->read_short',
        file_path: 'lib/My/App.pm',
        line_start: 7
      },
      {
        caller: 'My::App::run',
        expression: '$self->read_header',
        file_path: 'lib/My/App.pm',
        line_start: 9
      },
      {
        caller: 'My::App::run',
        expression: '$self->read_body',
        file_path: 'lib/My/App.pm',
        line_start: 9
      },
      {
        caller: 'My::App::run',
        expression: '$self->cipher',
        file_path: 'lib/My/App.pm',
        line_start: 13
      },
      {
        caller: 'My::App::run',
        expression: '$self->header',
        file_path: 'lib/My/App.pm',
        line_start: 13
      }
    ]);
    expect(result.unsupported_patterns).toEqual([{
      kind: 'dynamic_method',
      file_path: 'lib/My/App.pm',
      line_start: 16,
      snippet: 'return $self->$runtime();',
      notes: 'Dynamic method name cannot be statically resolved'
    }]);
  });

  it('reports tree-sitter parse diagnostics while preserving partial extraction', () => {
    const result = extractPerlFile('lib/Broken.pm', [
      'package Broken;',
      'sub ok { return 1; }',
      'sub broken { if ('
    ].join('\n'));

    expect(result.symbols.some((symbol) => symbol.qualified_name === 'Broken::ok')).toBe(true);
    expect(result.parse_diagnostics).toEqual([{
      file_path: 'lib/Broken.pm',
      error_count: expect.any(Number),
      notes: 'tree-sitter reported parse errors; extraction may be partial'
    }]);
    expect(result.parse_diagnostics[0]!.error_count).toBeGreaterThan(0);
  });

  it('annotates method calls with receiver types inferred from local constructor assignment', () => {
    const result = extractPerlFile('lib/My/App.pm', [
      'package My::App;',
      'sub make_service {',
      '  return My::Service->new();',
      '}',
      'sub run {',
      '  my ($self) = @_;',
      '  my $class = "My::Service";',
      '  my $svc = My::Service->new();',
      '  my $aliased = $class->new();',
      '  my $factory = make_service();',
      '  $svc->execute();',
      '  $aliased->execute();',
      '  return $factory->execute();',
      '}'
    ].join('\n'));

    expect(result.calls).toEqual([
      {
        caller: 'My::App::make_service',
        expression: 'My::Service->new',
        file_path: 'lib/My/App.pm',
        line_start: 3
      },
      {
        caller: 'My::App::run',
        expression: 'My::Service->new',
        file_path: 'lib/My/App.pm',
        line_start: 8
      },
      {
        caller: 'My::App::run',
        expression: '$class->new',
        receiver_type: 'My::Service',
        file_path: 'lib/My/App.pm',
        line_start: 9
      },
      {
        caller: 'My::App::run',
        expression: 'make_service',
        receiver_type: 'My::Service',
        file_path: 'lib/My/App.pm',
        line_start: 10
      },
      {
        caller: 'My::App::run',
        expression: '$svc->execute',
        receiver_type: 'My::Service',
        file_path: 'lib/My/App.pm',
        line_start: 11
      },
      {
        caller: 'My::App::run',
        expression: '$aliased->execute',
        receiver_type: 'My::Service',
        file_path: 'lib/My/App.pm',
        line_start: 12
      },
      {
        caller: 'My::App::run',
        expression: '$factory->execute',
        receiver_type: 'My::Service',
        file_path: 'lib/My/App.pm',
        line_start: 13
      }
    ]);
  });

  it('infers receiver types from database handle assignments', () => {
    const result = extractPerlFile('lib/My/App.pm', [
      'package My::App;',
      'sub run {',
      '  my ($self, $mc) = @_;',
      '  my $handle = $mc->dbh();',
      '  my $cursor = $handle->prepare($sql);',
      '  my $other = $mc->query($sql);',
      '  $handle->quote($value);',
      '  $cursor->fetchrow_hashref();',
      '  $other->finish();',
      '}'
    ].join('\n'));

    expect(result.calls).toContainEqual({
      caller: 'My::App::run',
      expression: '$handle->quote',
      receiver_type: 'DBI::db',
      file_path: 'lib/My/App.pm',
      line_start: 7
    });
    expect(result.calls).toContainEqual({
      caller: 'My::App::run',
      expression: '$cursor->fetchrow_hashref',
      receiver_type: 'DBI::st',
      file_path: 'lib/My/App.pm',
      line_start: 8
    });
    expect(result.calls).toContainEqual({
      caller: 'My::App::run',
      expression: '$other->finish',
      receiver_type: 'DBI::st',
      file_path: 'lib/My/App.pm',
      line_start: 9
    });
  });

  it('does not extract Perl syntax, builtins, quote operators, or heredoc text as calls', () => {
    const result = extractPerlFile('lib/My/App.pm', [
      'package My::App;',
      'sub run {',
      '  my ($self, $rows) = @_;',
      '  if (defined $rows) {',
      '    push @{$rows}, helper();',
      '  } elsif (ref $rows) {',
      '    my $name = qq(player_id);',
      '    $name =~ s/player/team/;',
      '  } unless (!$rows);',
      '  my $started = "NOW(3)";',
      '  my $select = "SELECT IFNULL(score, 0) FROM Result";',
      '  # example: COUNT(Player_Carry.carry_distance) AS carries',
      '  my $sql = <<SQL;',
      'SELECT SUM(score) AS score',
      'FROM Result',
      'WHERE team_id IN (1,2) AND game_id IS NOT NULL',
      'SQL',
      '}',
      'sub helper { return 1; }'
    ].join('\n'));

    expect(result.calls).toEqual([{
      caller: 'My::App::run',
      expression: 'helper',
      file_path: 'lib/My/App.pm',
      line_start: 5
    }]);
  });

  it('extracts Moose and Moo role applications and attribute accessors from literal declarations', () => {
    const result = extractPerlFile('lib/My/App.pm', [
      'package My::App;',
      'use Moo;',
      'with "My::Role", "Other::Role";',
      'with qw(My::QwRole Other::QwRole);',
      'has service => (is => "ro");',
      'has [qw(primary secondary)] => (is => "ro");',
      'requires "required_method";',
      'before "run" => sub { };',
      'around save => sub { };',
      'sub run {',
      '  my ($self) = @_;',
      '  return $self->service();',
      '}'
    ].join('\n'));

    expect(result.role_applications).toEqual([
      {
        source_package: 'My::App',
        target_role: 'My::Role',
        file_path: 'lib/My/App.pm',
        line_start: 3
      },
      {
        source_package: 'My::App',
        target_role: 'Other::Role',
        file_path: 'lib/My/App.pm',
        line_start: 3
      },
      {
        source_package: 'My::App',
        target_role: 'My::QwRole',
        file_path: 'lib/My/App.pm',
        line_start: 4
      },
      {
        source_package: 'My::App',
        target_role: 'Other::QwRole',
        file_path: 'lib/My/App.pm',
        line_start: 4
      }
    ]);
    expect(result.symbols).toContainEqual({
      qualified_name: 'My::App::service',
      name: 'service',
      kind: 'method',
      language: 'perl',
      file_path: 'lib/My/App.pm',
      line_start: 5,
      line_end: 5,
      signature: 'has service',
      provenance: ['moose-moo-attribute', 'line-scan']
    });
    expect(result.symbols).toContainEqual({
      qualified_name: 'My::App::primary',
      name: 'primary',
      kind: 'method',
      language: 'perl',
      file_path: 'lib/My/App.pm',
      line_start: 6,
      line_end: 6,
      signature: 'has primary',
      provenance: ['moose-moo-attribute', 'line-scan']
    });
    expect(result.symbols).toContainEqual({
      qualified_name: 'My::App::secondary',
      name: 'secondary',
      kind: 'method',
      language: 'perl',
      file_path: 'lib/My/App.pm',
      line_start: 6,
      line_end: 6,
      signature: 'has secondary',
      provenance: ['moose-moo-attribute', 'line-scan']
    });
    expect(result.symbols).toContainEqual({
      qualified_name: 'My::App::required_method',
      name: 'required_method',
      kind: 'method',
      language: 'perl',
      file_path: 'lib/My/App.pm',
      line_start: 7,
      line_end: 7,
      signature: 'requires required_method',
      provenance: ['moose-moo-requires', 'line-scan']
    });
    expect(result.unsupported_patterns).toContainEqual({
      kind: 'moose_modifier',
      file_path: 'lib/My/App.pm',
      line_start: 8,
      snippet: 'before "run" => sub { };',
      notes: 'Moose/Moo method modifier changes dispatch semantics for: run',
      targets: ['run']
    });
    expect(result.unsupported_patterns).toContainEqual({
      kind: 'moose_modifier',
      file_path: 'lib/My/App.pm',
      line_start: 9,
      snippet: 'around save => sub { };',
      notes: 'Moose/Moo method modifier changes dispatch semantics for: save',
      targets: ['save']
    });
  });

  it('extracts Moose and Moo modifier targets from qw lists', () => {
    const result = extractPerlFile('lib/My/App.pm', [
      'package My::App;',
      'use Moo;',
      'before qw( set_up_keywords competition_id season_id ) => sub { };'
    ].join('\n'));

    expect(result.unsupported_patterns).toEqual([{
      kind: 'moose_modifier',
      file_path: 'lib/My/App.pm',
      line_start: 3,
      snippet: 'before qw( set_up_keywords competition_id season_id ) => sub { };',
      notes: 'Moose/Moo method modifier changes dispatch semantics for: set_up_keywords, competition_id, season_id',
      targets: ['set_up_keywords', 'competition_id', 'season_id']
    }]);
  });

  it('uses Moose modifier bodies as bounded call scopes', () => {
    const result = extractPerlFile('lib/My/App.pm', [
      'package My::App;',
      'use Moose;',
      'before "to_xml" => sub {',
      '  my $self = shift;',
      '  my $game = $self->game;',
      '  foreach (qw|competition_id season_id game_system_id|) {',
      '    $self->$_($game->get($_));',
      '  }',
      '};'
    ].join('\n'));

    expect(result.unsupported_patterns).toEqual([{
      kind: 'moose_modifier',
      file_path: 'lib/My/App.pm',
      line_start: 3,
      snippet: 'before "to_xml" => sub {',
      notes: 'Moose/Moo method modifier changes dispatch semantics for: to_xml',
      targets: ['to_xml']
    }]);
    expect(result.calls).toEqual([
      {
        caller: 'My::App::__modifier_before_to_xml',
        expression: '$self->game',
        file_path: 'lib/My/App.pm',
        line_start: 5
      },
      {
        caller: 'My::App::__modifier_before_to_xml',
        expression: '$self->competition_id',
        file_path: 'lib/My/App.pm',
        line_start: 7
      },
      {
        caller: 'My::App::__modifier_before_to_xml',
        expression: '$self->season_id',
        file_path: 'lib/My/App.pm',
        line_start: 7
      },
      {
        caller: 'My::App::__modifier_before_to_xml',
        expression: '$self->game_system_id',
        file_path: 'lib/My/App.pm',
        line_start: 7
      },
      {
        caller: 'My::App::__modifier_before_to_xml',
        expression: '$game->get',
        file_path: 'lib/My/App.pm',
        line_start: 7
      }
    ]);
  });

  it('classifies Moose around orig dispatch separately from dynamic methods', () => {
    const result = extractPerlFile('lib/My/App.pm', [
      'package My::App;',
      'use Moose;',
      'around to_xml => sub {',
      '  my $orig = shift;',
      '  my $self = shift;',
      '  return $self->$orig(@_, 1);',
      '};'
    ].join('\n'));

    expect(result.unsupported_patterns).toEqual([
      {
        kind: 'moose_modifier',
        file_path: 'lib/My/App.pm',
        line_start: 3,
        snippet: 'around to_xml => sub {',
        notes: 'Moose/Moo method modifier changes dispatch semantics for: to_xml',
        targets: ['to_xml']
      },
      {
        kind: 'moose_around_orig',
        file_path: 'lib/My/App.pm',
        line_start: 6,
        snippet: 'return $self->$orig(@_, 1);',
        notes: 'Moose around modifier continuation cannot be resolved as a normal static method',
        targets: ['to_xml']
      }
    ]);
  });

  it('extracts simple multiline framework declarations', () => {
    const result = extractPerlFile('lib/My/App.pm', [
      'package My::App;',
      'use Moo;',
      'with',
      '  "My::Role";',
      'has',
      '  service => (is => "ro");',
      'require',
      '  "My/" . "Service.pm";'
    ].join('\n'));

    expect(result.role_applications).toContainEqual({
      source_package: 'My::App',
      target_role: 'My::Role',
      file_path: 'lib/My/App.pm',
      line_start: 3
    });
    expect(result.symbols).toContainEqual({
      qualified_name: 'My::App::service',
      name: 'service',
      kind: 'method',
      language: 'perl',
      file_path: 'lib/My/App.pm',
      line_start: 5,
      line_end: 5,
      signature: 'has service',
      provenance: ['moose-moo-attribute', 'line-scan']
    });
    expect(result.dependencies).toContainEqual({
      source_module: 'My::App',
      target_module: 'My::Service',
      source_file: 'lib/My/App.pm',
      kind: 'require',
      line_start: 7
    });
  });
});
