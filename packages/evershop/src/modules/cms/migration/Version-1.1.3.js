import { execute } from '@evershop/postgres-query-builder';

export default async (connection) => {
  await execute(
    connection,
    `ALTER TABLE incident_reports
      ADD COLUMN IF NOT EXISTS priority_level varchar DEFAULT NULL`
  );

  await execute(
    connection,
    `ALTER TABLE incident_reports
      ADD COLUMN IF NOT EXISTS is_high_priority boolean DEFAULT NULL`
  );

  await execute(
    connection,
    `ALTER TABLE incident_reports
      ADD COLUMN IF NOT EXISTS priority_reason text DEFAULT NULL`
  );
};

