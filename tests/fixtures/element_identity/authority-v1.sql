-- Frozen from reviewed allocation authority d877e339, before lifecycle schema work.
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
CREATE TABLE counters (spec_id TEXT NOT NULL, kind TEXT NOT NULL, high_water TEXT NOT NULL CHECK (high_water NOT GLOB '*[^0-9]*' AND (high_water = '0' OR high_water GLOB '[1-9]*')), PRIMARY KEY (spec_id, kind)) WITHOUT ROWID;
CREATE TABLE operations (operation_id TEXT PRIMARY KEY, method TEXT NOT NULL, spec_id TEXT NOT NULL, digest TEXT NOT NULL) WITHOUT ROWID;
CREATE TABLE reservations (operation_id TEXT PRIMARY KEY REFERENCES operations(operation_id), spec_id TEXT NOT NULL, kind TEXT NOT NULL, first_ordinal TEXT NOT NULL CHECK (first_ordinal NOT GLOB '*[^0-9]*' AND (first_ordinal = '0' OR first_ordinal GLOB '[1-9]*') AND first_ordinal != '0'), first_length INTEGER NOT NULL, last_ordinal TEXT NOT NULL CHECK (last_ordinal NOT GLOB '*[^0-9]*' AND (last_ordinal = '0' OR last_ordinal GLOB '[1-9]*')), count TEXT NOT NULL CHECK (count NOT GLOB '*[^0-9]*' AND (count = '0' OR count GLOB '[1-9]*') AND count != '0')) WITHOUT ROWID;
CREATE UNIQUE INDEX reservation_ranges ON reservations (spec_id, kind, first_length, first_ordinal);
CREATE INDEX reservation_maxima ON reservations (spec_id, kind, length(last_ordinal), last_ordinal);
CREATE TABLE entities (spec_id TEXT NOT NULL, element_id TEXT NOT NULL, kind TEXT NOT NULL, subject TEXT NOT NULL, ordinal TEXT CHECK (ordinal IS NULL OR (ordinal NOT GLOB '*[^0-9]*' AND (ordinal = '0' OR ordinal GLOB '[1-9]*') AND ordinal != '0')), PRIMARY KEY (spec_id, element_id)) WITHOUT ROWID;
CREATE UNIQUE INDEX entity_ordinals ON entities (spec_id, kind, ordinal);
CREATE INDEX entity_maxima ON entities (spec_id, kind, length(ordinal), ordinal) WHERE ordinal IS NOT NULL;
PRAGMA user_version=1;
