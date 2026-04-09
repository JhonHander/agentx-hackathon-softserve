import { execute } from '@evershop/postgres-query-builder';

export default async (connection) => {
  await execute(
    connection,
    `ALTER TABLE incident_reports
      ADD COLUMN IF NOT EXISTS source varchar DEFAULT NULL`
  );

  await execute(
    connection,
    `ALTER TABLE incident_reports
      ADD COLUMN IF NOT EXISTS expected_result text DEFAULT NULL`
  );

  await execute(
    connection,
    `ALTER TABLE incident_reports
      ADD COLUMN IF NOT EXISTS actual_result text DEFAULT NULL`
  );

  await execute(
    connection,
    `ALTER TABLE incident_reports
      ADD COLUMN IF NOT EXISTS steps_to_reproduce text DEFAULT NULL`
  );

  await execute(
    connection,
    `ALTER TABLE incident_reports
      ADD COLUMN IF NOT EXISTS status varchar DEFAULT 'new'`
  );

  await execute(
    connection,
    `ALTER TABLE incident_reports
      ADD COLUMN IF NOT EXISTS metadata jsonb DEFAULT '{}'::jsonb`
  );

  await execute(
    connection,
    `ALTER TABLE incident_reports
      ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP`
  );

  await execute(
    connection,
    `DO $$
    DECLARE
      id_type text;
    BEGIN
      SELECT format_type(a.atttypid, a.atttypmod)
      INTO id_type
      FROM pg_attribute a
      JOIN pg_class c ON c.oid = a.attrelid
      JOIN pg_namespace n ON n.oid = c.relnamespace
      WHERE c.relname = 'incident_reports'
        AND n.nspname = 'public'
        AND a.attname = 'id'
        AND a.attnum > 0
        AND NOT a.attisdropped;

      IF id_type IS NULL THEN
        id_type := 'integer';
      END IF;

      EXECUTE format(
        'CREATE TABLE IF NOT EXISTS incident_report_attachments (
          id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          incident_report_id %s NOT NULL,
          attachment_name varchar NOT NULL,
          attachment_type varchar DEFAULT NULL,
          attachment_size INT NOT NULL DEFAULT 0,
          attachment_data bytea NOT NULL,
          created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )',
        id_type
      );
    END $$`
  );

  await execute(
    connection,
    `ALTER TABLE incident_report_attachments
      DROP CONSTRAINT IF EXISTS incident_report_attachments_incident_report_id_fkey`
  );

  await execute(
    connection,
    `DO $$
    BEGIN
      BEGIN
        ALTER TABLE incident_report_attachments
          ADD CONSTRAINT incident_report_attachments_incident_report_id_fkey
          FOREIGN KEY (incident_report_id)
          REFERENCES incident_reports(id)
          ON DELETE CASCADE;
      EXCEPTION
        WHEN others THEN
          RAISE NOTICE 'Could not add FK incident_report_attachments -> incident_reports: %', SQLERRM;
      END;
    END $$`
  );

  await execute(
    connection,
    `CREATE INDEX IF NOT EXISTS incident_report_attachments_report_id_idx
      ON incident_report_attachments (incident_report_id)`
  );
};
