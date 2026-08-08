# CodeGraph Upstream Notes

PerlGraph is intentionally shaped as an incubator for future CodeGraph Perl support.

## Mapping

- `.pl`, `.pm`, `.t`, `.psgi` map to language `perl`.
- `package Foo::Bar` maps to a namespace/module node.
- `sub name` maps to a function node unless method evidence is present.
- constructor-style and `$self` subs map to method nodes.
- `use` and `require` map to import/require edges.
- `use parent` and `use base` map to inheritance edges.
- direct calls and package-qualified calls map to calls edges.

## Contribution Strategy

Port the smallest high-confidence subset first:

1. grammar registration and extension mapping
2. package and sub extraction
3. use/require dependency extraction
4. direct and package-qualified calls
5. fixture snapshots

Method dispatch, Moose/Moo, AUTOLOAD, symbolic references, and string eval should remain diagnostic or low-confidence behavior until CodeGraph has an explicit confidence model for Perl edges.
