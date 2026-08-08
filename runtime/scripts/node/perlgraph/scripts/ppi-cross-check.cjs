#!/usr/bin/env node
const { spawnSync } = require('node:child_process');
const { existsSync, readFileSync } = require('node:fs');

const filePath = process.argv[2];

if (!filePath) {
  console.error('Usage: node scripts/ppi-cross-check.cjs <perl-file>');
  process.exit(2);
}

if (!existsSync(filePath)) {
  console.error(`File does not exist: ${filePath}`);
  process.exit(2);
}

const availability = spawnSync('perl', ['-MPPI', '-e', 'print "ok"'], { encoding: 'utf8' });
if (availability.status !== 0) {
  console.log('SKIP: Perl PPI module is not available');
  process.exit(0);
}

const source = readFileSync(filePath, 'utf8');
const perl = spawnSync('perl', ['-MPPI', '-MJSON::PP', '-e', `
my $doc = PPI::Document->new(\\$ARGV[0]);
my @packages = map { $_->namespace } @{ $doc->find('PPI::Statement::Package') || [] };
my @subs = map { $_->name } @{ $doc->find('PPI::Statement::Sub') || [] };
print JSON::PP->new->canonical->encode({ packages => \\@packages, subs => \\@subs });
`, source], { encoding: 'utf8' });

if (perl.status !== 0) {
  console.error(perl.stderr.trim());
  process.exit(perl.status ?? 1);
}

console.log(perl.stdout.trim());
