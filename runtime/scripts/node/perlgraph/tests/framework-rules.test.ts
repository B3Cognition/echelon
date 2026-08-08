import { describe, expect, it } from 'vitest';
import {
  attributeNames,
  frameworkDeclaration,
  frameworkForModule,
  staticListValues
} from '../src/extraction/framework-rules.js';

describe('framework rules', () => {
  it('recognizes supported Moose and Moo modules explicitly', () => {
    expect(frameworkForModule('Moose')).toBe('Moose');
    expect(frameworkForModule('Moose::Role')).toBe('Moose');
    expect(frameworkForModule('Moo')).toBe('Moo');
    expect(frameworkForModule('Moo::Role')).toBe('Moo');
    expect(frameworkForModule('Role::Tiny')).toBeUndefined();
  });

  it('extracts static list values without evaluating Perl', () => {
    expect(staticListValues('-norequire, "My::Base", "Other::Base"')).toEqual(['My::Base', 'Other::Base']);
    expect(staticListValues('qw(My::Role Other::Role)')).toEqual(['My::Role', 'Other::Role']);
    expect(staticListValues('qw|competition_id season_id|')).toEqual(['competition_id', 'season_id']);
  });

  it('extracts static attribute names', () => {
    expect(attributeNames('service')).toEqual(['service']);
    expect(attributeNames('"service"')).toEqual(['service']);
    expect(attributeNames('[qw(primary secondary)]')).toEqual(['primary', 'secondary']);
    expect(attributeNames('$dynamic')).toEqual([]);
  });

  it('classifies framework declarations', () => {
    expect(frameworkDeclaration('with qw(My::Role Other::Role);')).toEqual({
      kind: 'role',
      values: ['My::Role', 'Other::Role']
    });
    expect(frameworkDeclaration('extends "My::Base";')).toEqual({
      kind: 'extends',
      values: ['My::Base']
    });
    expect(frameworkDeclaration('around run => sub { };')).toEqual({
      kind: 'modifier',
      values: ['run']
    });
  });
});
