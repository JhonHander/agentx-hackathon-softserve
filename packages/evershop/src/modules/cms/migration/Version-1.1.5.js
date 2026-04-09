import { execute } from '@evershop/postgres-query-builder';

export default async (connection) => {
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
        'CREATE TABLE IF NOT EXISTS incident_report_recommendations (
          id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          incident_report_id %s NOT NULL,
          analysis_query text NOT NULL,
          analysis_summary text NOT NULL,
          probable_files jsonb NOT NULL DEFAULT ''[]''::jsonb,
          top_chunks jsonb NOT NULL DEFAULT ''[]''::jsonb,
          suggested_fixes jsonb NOT NULL DEFAULT ''[]''::jsonb,
          llm_model varchar DEFAULT NULL,
          run_status varchar NOT NULL DEFAULT ''completed'',
          error_message text DEFAULT NULL,
          created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )',
        id_type
      );
    END $$`
  );

  await execute(
    connection,
    `ALTER TABLE incident_report_recommendations
      DROP CONSTRAINT IF EXISTS incident_report_recommendations_incident_report_id_fkey`
  );

  await execute(
    connection,
    `DO $$
    BEGIN
      BEGIN
        ALTER TABLE incident_report_recommendations
          ADD CONSTRAINT incident_report_recommendations_incident_report_id_fkey
          FOREIGN KEY (incident_report_id)
          REFERENCES incident_reports(id)
          ON DELETE CASCADE;
      EXCEPTION
        WHEN others THEN
          RAISE NOTICE 'Could not add FK incident_report_recommendations -> incident_reports: %', SQLERRM;
      END;
    END $$`
  );

  await execute(
    connection,
    `CREATE INDEX IF NOT EXISTS incident_report_recommendations_report_id_idx
      ON incident_report_recommendations (incident_report_id)`
  );

  await execute(
    connection,
    `CREATE INDEX IF NOT EXISTS incident_report_recommendations_created_at_idx
      ON incident_report_recommendations (created_at DESC)`
  );
};
