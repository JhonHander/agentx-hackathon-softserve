import { execute } from '@evershop/postgres-query-builder';

export default async (connection) => {
  await execute(
    connection,
    `CREATE TABLE IF NOT EXISTS "incident_reports" (
      "id" INT GENERATED ALWAYS AS IDENTITY (START WITH 1 INCREMENT BY 1) PRIMARY KEY,
      "description" text NOT NULL,
      "reporter_name" varchar DEFAULT NULL,
      "reporter_email" varchar DEFAULT NULL,
      "page_url" text DEFAULT NULL,
      "attachment_name" varchar DEFAULT NULL,
      "attachment_type" varchar DEFAULT NULL,
      "attachment_data" bytea DEFAULT NULL,
      "created_at" TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    )`
  );
};
