/*
# Create server activity log

1. New Tables
- `server_activity`: one row per management action taken from the ServerMaker panel (start, stop, RAM change, property change, backup, command sent).
  - `id` (bigint identity, primary key)
  - `created_at` (timestamptz, defaults to now)
  - `action` (text, not null) short machine-readable action name
  - `detail` (text) human-readable description

2. Security
- Enables row level security on `server_activity`.
- Grants SELECT and INSERT to `service_role` only. The panel runs server-side with the service key; the public web browser never touches this table.
- No policies for `anon` or `authenticated`, so the public anon key cannot read or write the log.

3. Notes
- Idempotent: safe to re-run.
- Index on created_at keeps the "recent activity" query fast.
*/

CREATE TABLE IF NOT EXISTS server_activity (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  created_at timestamptz NOT NULL DEFAULT now(),
  action text NOT NULL,
  detail text NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS server_activity_created_at_idx ON server_activity (created_at DESC);

ALTER TABLE server_activity ENABLE ROW LEVEL SECURITY;

GRANT SELECT, INSERT ON server_activity TO service_role;
