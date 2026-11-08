CREATE TABLE pilot_interest (
  id TEXT PRIMARY KEY NOT NULL,
  email TEXT NOT NULL UNIQUE,
  school TEXT NOT NULL,
  role TEXT NOT NULL,
  language TEXT NOT NULL,
  consent_version TEXT NOT NULL,
  created_at TEXT NOT NULL
);
--> statement-breakpoint
CREATE INDEX pilot_interest_created_at_idx ON pilot_interest (created_at);
