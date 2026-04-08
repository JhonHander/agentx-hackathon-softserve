import { INVALID_PAYLOAD, INTERNAL_SERVER_ERROR, OK } from '../../../../lib/util/httpStatus.js';
import { pool } from '../../../../lib/postgres/connection.js';

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024;

function normalizeTextField(value: unknown): string {
  if (Array.isArray(value)) {
    const first = value.find((v) => v !== null && v !== undefined && `${v}`.trim() !== '');
    return first !== undefined ? String(first).trim() : '';
  }
  if (value === null || value === undefined) return '';
  return String(value).trim();
}

function getAttachmentFromRequest(
  request
): Express.Multer.File | undefined {
  // Multer "fields" stores files under request.files.<fieldName>
  // We support both "attachment" and "attachments" to keep backward compatibility.
  const files = request.files as
    | Record<string, Express.Multer.File[]>
    | undefined;

  if (!files) return undefined;
  return files.attachment?.[0] || files.attachments?.[0];
}

function getBase64AttachmentFromRequest(request): {
  name: string | null;
  type: string | null;
  data: Buffer | null;
} {
  const base64Raw =
    normalizeTextField(request.body?.attachment_base64) ||
    normalizeTextField(request.body?.attachment_data_base64) ||
    '';
  if (!base64Raw) {
    return { name: null, type: null, data: null };
  }

  // Accept plain base64 or Data URL format: data:<mime>;base64,<data>
  let mimeType = normalizeTextField(request.body?.attachment_type) || null;
  let payload = base64Raw;
  const dataUrlMatch = base64Raw.match(/^data:([^;]+);base64,(.+)$/);
  if (dataUrlMatch) {
    mimeType = mimeType || dataUrlMatch[1];
    payload = dataUrlMatch[2];
  }

  const buffer = Buffer.from(payload, 'base64');
  return {
    name: normalizeTextField(request.body?.attachment_name) || 'attachment.bin',
    type: mimeType || 'application/octet-stream',
    data: buffer.length > 0 ? buffer : null
  };
}

export default async (request, response, next) => {
  try {
    const description =
      normalizeTextField(request.body?.description) ||
      normalizeTextField(request.body?.message) ||
      normalizeTextField(request.body?.text);
    const reporterName = normalizeTextField(request.body?.reporter_name) || null;
    const reporterEmail = normalizeTextField(request.body?.reporter_email) || null;
    const pageUrl =
      normalizeTextField(request.body?.page_url) ||
      normalizeTextField(request.body?.pageUrl) ||
      null;
    const attachment = getAttachmentFromRequest(request);
    const jsonAttachment = getBase64AttachmentFromRequest(request);

    if (!description) {
      response.status(INVALID_PAYLOAD).json({
        error: {
          status: INVALID_PAYLOAD,
          message: 'description is required'
        },
        receivedFields: Object.keys(request.body || {})
      });
      return;
    }

    if (reporterEmail && !EMAIL_REGEX.test(reporterEmail)) {
      response.status(INVALID_PAYLOAD).json({
        error: {
          status: INVALID_PAYLOAD,
          message: 'reporter_email must be a valid email address'
        }
      });
      return;
    }

    const attachmentName =
      attachment?.originalname || jsonAttachment.name || null;
    const attachmentType = attachment?.mimetype || jsonAttachment.type || null;
    const attachmentData = attachment?.buffer || jsonAttachment.data || null;

    if (attachmentData && attachmentData.length > MAX_FILE_SIZE_BYTES) {
      response.status(INVALID_PAYLOAD).json({
        error: {
          status: INVALID_PAYLOAD,
          message: 'attachment exceeds 10MB limit'
        }
      });
      return;
    }

    const insertSql = `
      INSERT INTO incident_reports (
        description,
        reporter_name,
        reporter_email,
        page_url,
        attachment_name,
        attachment_type,
        attachment_data
      )
      VALUES ($1, $2, $3, $4, $5, $6, $7)
      RETURNING id
    `;

    const values = [
      description,
      reporterName,
      reporterEmail,
      pageUrl,
      attachmentName,
      attachmentType,
      attachmentData
    ];

    const result = await pool.query(insertSql, values);
    const incidentId = result.rows[0]?.id;

    response.status(OK);
    response.$body = {
      success: true,
      incidentId
    };
    next();
  } catch (error) {
    response.status(INTERNAL_SERVER_ERROR).json({
      error: {
        status: INTERNAL_SERVER_ERROR,
        message: 'Could not create incident report'
      }
    });
  }
};
