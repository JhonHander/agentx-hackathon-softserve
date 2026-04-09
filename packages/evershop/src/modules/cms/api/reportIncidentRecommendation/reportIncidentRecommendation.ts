import {
  INTERNAL_SERVER_ERROR,
  INVALID_PAYLOAD,
  OK
} from '../../../../lib/util/httpStatus.js';
import { pool } from '../../../../lib/postgres/connection.js';

function normalizeText(value: unknown): string {
  if (value === null || value === undefined) return '';
  return String(value).trim();
}

function normalizeJsonArray(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  const text = normalizeText(value);
  if (!text) return [];
  try {
    const parsed = JSON.parse(text);
    return Array.isArray(parsed) ? parsed : [];
  } catch (e) {
    return [];
  }
}

function normalizeIncidentId(value: unknown): string {
  return normalizeText(value);
}

let ensuredTable = false;

async function ensureRecommendationsTableExists(): Promise<void> {
  if (ensuredTable) return;

  await pool.query(`
    DO $$
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
    END $$;
  `);

  await pool.query(`
    ALTER TABLE incident_report_recommendations
      DROP CONSTRAINT IF EXISTS incident_report_recommendations_incident_report_id_fkey;
  `);

  await pool.query(`
    DO $$
    BEGIN
      BEGIN
        ALTER TABLE incident_report_recommendations
          ADD CONSTRAINT incident_report_recommendations_incident_report_id_fkey
          FOREIGN KEY (incident_report_id)
          REFERENCES incident_reports(id)
          ON DELETE CASCADE;
      EXCEPTION
        WHEN others THEN
          NULL;
      END;
    END $$;
  `);

  await pool.query(`
    CREATE INDEX IF NOT EXISTS incident_report_recommendations_report_id_idx
      ON incident_report_recommendations (incident_report_id);
  `);

  ensuredTable = true;
}

export default async (request, response, next) => {
  try {
    await ensureRecommendationsTableExists();

    const incidentReportId = normalizeIncidentId(
      request.body?.incident_report_id ?? request.body?.incidentId
    );
    const analysisQuery = normalizeText(
      request.body?.analysis_query ?? request.body?.query
    );
    const analysisSummary = normalizeText(
      request.body?.analysis_summary ?? request.body?.summary
    );
    const probableFiles = normalizeJsonArray(request.body?.probable_files);
    const topChunks = normalizeJsonArray(request.body?.top_chunks);
    const suggestedFixes = normalizeJsonArray(request.body?.suggested_fixes);
    const llmModel = normalizeText(request.body?.llm_model) || null;
    const runStatus = normalizeText(request.body?.run_status || 'completed');
    const errorMessage = normalizeText(request.body?.error_message) || null;

    if (!incidentReportId) {
      response.status(INVALID_PAYLOAD);
      response.$body = {
        error: {
          status: INVALID_PAYLOAD,
          message: 'incident_report_id is required'
        }
      };
      next();
      return;
    }

    if (!analysisQuery) {
      response.status(INVALID_PAYLOAD);
      response.$body = {
        error: {
          status: INVALID_PAYLOAD,
          message: 'analysis_query is required'
        }
      };
      next();
      return;
    }

    if (!analysisSummary) {
      response.status(INVALID_PAYLOAD);
      response.$body = {
        error: {
          status: INVALID_PAYLOAD,
          message: 'analysis_summary is required'
        }
      };
      next();
      return;
    }

    const insertSql = `
      INSERT INTO incident_report_recommendations (
        incident_report_id,
        analysis_query,
        analysis_summary,
        probable_files,
        top_chunks,
        suggested_fixes,
        llm_model,
        run_status,
        error_message
      )
      VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6::jsonb, $7, $8, $9)
      RETURNING id
    `;

    const result = await pool.query(insertSql, [
      incidentReportId,
      analysisQuery,
      analysisSummary,
      JSON.stringify(probableFiles),
      JSON.stringify(topChunks),
      JSON.stringify(suggestedFixes),
      llmModel,
      runStatus || 'completed',
      errorMessage
    ]);

    response.status(OK);
    response.$body = {
      success: true,
      recommendationId: result.rows[0]?.id || null,
      incidentId: incidentReportId
    };
    next();
  } catch (error) {
    response.status(INTERNAL_SERVER_ERROR);
    response.$body = {
      error: {
        status: INTERNAL_SERVER_ERROR,
        message: 'Could not create incident recommendation',
        details: error instanceof Error ? error.message : `${error}`
      }
    };
    next();
  }
};
