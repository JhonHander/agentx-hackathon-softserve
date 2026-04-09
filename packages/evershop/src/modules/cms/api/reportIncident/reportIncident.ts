import { INVALID_PAYLOAD, INTERNAL_SERVER_ERROR, OK } from '../../../../lib/util/httpStatus.js';
import { pool } from '../../../../lib/postgres/connection.js';

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024;
const MAX_ATTACHMENTS = 6;
const PRIORITY_LEVELS = new Set(['high', 'low']);

type AttachmentPayload = {
  name: string;
  type: string | null;
  data: Buffer;
  size: number;
};

function normalizeTextField(value: unknown): string {
  if (Array.isArray(value)) {
    const first = value.find((v) => v !== null && v !== undefined && `${v}`.trim() !== '');
    return first !== undefined ? String(first).trim() : '';
  }
  if (value === null || value === undefined) return '';
  return String(value).trim();
}

function normalizePriorityLevel(value: unknown): 'high' | 'low' | null {
  const normalized = normalizeTextField(value).toLowerCase();
  if (normalized === 'alta' || normalized === 'alto') return 'high';
  if (normalized === 'baja' || normalized === 'bajo') return 'low';
  if (!PRIORITY_LEVELS.has(normalized)) return null;
  return normalized as 'high' | 'low';
}

function normalizeBoolean(value: unknown): boolean | null {
  if (value === true || value === false) return value;
  const normalized = normalizeTextField(value).toLowerCase();
  if (!normalized) return null;
  if (['true', '1', 'yes', 'si', 'high', 'alta', 'alto'].includes(normalized)) {
    return true;
  }
  if (['false', '0', 'no', 'low', 'baja', 'bajo'].includes(normalized)) {
    return false;
  }
  return null;
}

function normalizeMetadata(value: unknown): Record<string, unknown> {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  const text = normalizeTextField(value);
  if (!text) return {};
  try {
    const parsed = JSON.parse(text);
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
  } catch (e) {
    // Ignore malformed metadata and fallback to empty object.
  }
  return {};
}

function getAttachmentsFromRequest(request): AttachmentPayload[] {
  const filesByField = request.files as
    | Record<string, Express.Multer.File[]>
    | undefined;
  const allFiles = [
    ...(filesByField?.attachment || []),
    ...(filesByField?.attachments || [])
  ];

  const attachments: AttachmentPayload[] = [];
  allFiles.slice(0, MAX_ATTACHMENTS).forEach((file) => {
    if (!file?.buffer || file.buffer.length === 0) return;
    attachments.push({
      name: file.originalname || 'attachment.bin',
      type: file.mimetype || null,
      data: file.buffer,
      size: file.buffer.length
    });
  });
  return attachments;
}

function parseBase64Attachment(
  base64Raw: string,
  fallbackName: string,
  fallbackType: string | null
): AttachmentPayload | null {
  if (!base64Raw) return null;

  let mimeType = fallbackType;
  let payload = base64Raw;
  const dataUrlMatch = base64Raw.match(/^data:([^;]+);base64,(.+)$/);
  if (dataUrlMatch) {
    mimeType = mimeType || dataUrlMatch[1];
    payload = dataUrlMatch[2];
  }

  const buffer = Buffer.from(payload, 'base64');
  if (!buffer.length) return null;

  return {
    name: fallbackName || 'attachment.bin',
    type: mimeType || 'application/octet-stream',
    data: buffer,
    size: buffer.length
  };
}

function getBase64AttachmentFromRequest(request): AttachmentPayload | null {
  const base64Raw =
    normalizeTextField(request.body?.attachment_base64) ||
    normalizeTextField(request.body?.attachment_data_base64) ||
    '';
  if (!base64Raw) return null;

  return parseBase64Attachment(
    base64Raw,
    normalizeTextField(request.body?.attachment_name) || 'attachment.bin',
    normalizeTextField(request.body?.attachment_type) || null
  );
}

function getBase64AttachmentsFromRequest(request): AttachmentPayload[] {
  const rawAttachments = request.body?.attachments_base64;
  if (!rawAttachments) return [];

  let parsedAttachments = rawAttachments;
  if (typeof rawAttachments === 'string') {
    try {
      parsedAttachments = JSON.parse(rawAttachments);
    } catch (e) {
      parsedAttachments = [];
    }
  }

  const iterable = Array.isArray(parsedAttachments)
    ? parsedAttachments
    : parsedAttachments && typeof parsedAttachments === 'object'
    ? [parsedAttachments]
    : [];

  const attachments: AttachmentPayload[] = [];
  iterable.slice(0, MAX_ATTACHMENTS).forEach((item, index) => {
    if (!item || typeof item !== 'object') return;
    const record = item as Record<string, unknown>;
    const base64Raw =
      normalizeTextField(record.data_base64) ||
      normalizeTextField(record.base64) ||
      normalizeTextField(record.data) ||
      normalizeTextField(record.content);
    if (!base64Raw) return;

    const attachment = parseBase64Attachment(
      base64Raw,
      normalizeTextField(record.name) || `attachment-${index + 1}.bin`,
      normalizeTextField(record.type || record.mime_type) || null
    );
    if (attachment) {
      attachments.push(attachment);
    }
  });

  return attachments;
}

function dedupeAttachments(attachments: AttachmentPayload[]): AttachmentPayload[] {
  const unique = new Map<string, AttachmentPayload>();
  attachments.forEach((attachment) => {
    const key = `${attachment.name}|${attachment.type || ''}|${attachment.size}`;
    if (!unique.has(key)) {
      unique.set(key, attachment);
    }
  });
  return Array.from(unique.values());
}

function normalizeAttachments(request): AttachmentPayload[] {
  const fileAttachments = getAttachmentsFromRequest(request);
  const arrayBase64Attachments = getBase64AttachmentsFromRequest(request);
  const singleBase64Attachment = getBase64AttachmentFromRequest(request);
  return dedupeAttachments(
    [
      ...fileAttachments,
      ...arrayBase64Attachments,
      ...(singleBase64Attachment ? [singleBase64Attachment] : [])
    ].slice(0, MAX_ATTACHMENTS)
  );
}

function safeParseMetadataAttachmentCount(value: unknown): number | null {
  if (typeof value !== 'number') return null;
  if (!Number.isFinite(value)) return null;
  if (value < 0) return null;
  return Math.floor(value);
}

function mergeAttachmentMetadata(
  metadata: Record<string, unknown>,
  attachments: AttachmentPayload[]
): Record<string, unknown> {
  const existingCount = safeParseMetadataAttachmentCount(metadata.attachment_count);
  if (existingCount !== null && existingCount >= attachments.length) {
    return metadata;
  }
  return {
    ...metadata,
    attachment_count: attachments.length
  };
}

async function insertAttachments(
  incidentId: number,
  attachments: AttachmentPayload[]
): Promise<void> {
  if (!attachments.length) return;
  const insertAttachmentSql = `
    INSERT INTO incident_report_attachments (
      incident_report_id,
      attachment_name,
      attachment_type,
      attachment_size,
      attachment_data
    )
    VALUES ($1, $2, $3, $4, $5)
  `;

  for (const attachment of attachments) {
    await pool.query(insertAttachmentSql, [
      incidentId,
      attachment.name,
      attachment.type,
      attachment.size,
      attachment.data
    ]);
  }
}

export default async (request, response, next) => {
  try {
    const description =
      normalizeTextField(request.body?.description) ||
      normalizeTextField(request.body?.message) ||
      normalizeTextField(request.body?.text);
    const expectedResult = normalizeTextField(request.body?.expected_result) || null;
    const actualResult = normalizeTextField(request.body?.actual_result) || null;
    const stepsToReproduce = normalizeTextField(request.body?.steps_to_reproduce) || null;
    const source = normalizeTextField(request.body?.source) || null;
    const reporterName = normalizeTextField(request.body?.reporter_name) || null;
    const reporterEmail = normalizeTextField(request.body?.reporter_email) || null;
    const pageUrl =
      normalizeTextField(request.body?.page_url) ||
      normalizeTextField(request.body?.pageUrl) ||
      null;
    const priorityLevel = normalizePriorityLevel(
      request.body?.priority_level ?? request.body?.priorityLevel
    );
    const priorityReason =
      normalizeTextField(request.body?.priority_reason ?? request.body?.priorityReason) ||
      null;
    const normalizedIsHighPriority = normalizeBoolean(
      request.body?.is_high_priority ?? request.body?.isHighPriority
    );
    const isHighPriority =
      normalizedIsHighPriority !== null
        ? normalizedIsHighPriority
        : priorityLevel
        ? priorityLevel === 'high'
        : null;
    const incidentStatus = normalizeTextField(request.body?.status) || 'new';
    const attachments = normalizeAttachments(request);
    const metadata = mergeAttachmentMetadata(
      normalizeMetadata(request.body?.metadata),
      attachments
    );

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

    if (attachments.length > MAX_ATTACHMENTS) {
      response.status(INVALID_PAYLOAD).json({
        error: {
          status: INVALID_PAYLOAD,
          message: `attachments limit is ${MAX_ATTACHMENTS}`
        }
      });
      return;
    }

    const oversizedAttachment = attachments.find(
      (attachment) => attachment.size > MAX_FILE_SIZE_BYTES
    );
    if (oversizedAttachment) {
      response.status(INVALID_PAYLOAD).json({
        error: {
          status: INVALID_PAYLOAD,
          message: `attachment "${oversizedAttachment.name}" exceeds 10MB limit`
        }
      });
      return;
    }

    // Keep compatibility with existing schema by still populating legacy single-attachment columns.
    const primaryAttachment = attachments[0] || null;
    const attachmentName = primaryAttachment?.name || null;
    const attachmentType = primaryAttachment?.type || null;
    const attachmentData = primaryAttachment?.data || null;

    const insertSqlV3 = `
      INSERT INTO incident_reports (
        description,
        expected_result,
        actual_result,
        steps_to_reproduce,
        source,
        reporter_name,
        reporter_email,
        page_url,
        status,
        metadata,
        attachment_name,
        attachment_type,
        attachment_data,
        priority_level,
        is_high_priority,
        priority_reason
      )
      VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11, $12, $13, $14, $15, $16)
      RETURNING id
    `;

    const insertSqlV2 = `
      INSERT INTO incident_reports (
        description,
        reporter_name,
        reporter_email,
        page_url,
        attachment_name,
        attachment_type,
        attachment_data,
        priority_level,
        is_high_priority,
        priority_reason
      )
      VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
      RETURNING id
    `;

    const insertSqlV1 = `
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

    const valuesV3 = [
      description,
      expectedResult,
      actualResult,
      stepsToReproduce,
      source,
      reporterName,
      reporterEmail,
      pageUrl,
      incidentStatus,
      JSON.stringify(metadata),
      attachmentName,
      attachmentType,
      attachmentData,
      priorityLevel,
      isHighPriority,
      priorityReason
    ];

    const valuesV2 = [
      description,
      reporterName,
      reporterEmail,
      pageUrl,
      attachmentName,
      attachmentType,
      attachmentData,
      priorityLevel,
      isHighPriority,
      priorityReason
    ];

    const fallbackDescription =
      priorityLevel || priorityReason
        ? `${description}\n\nPriority: ${(priorityLevel || 'low').toUpperCase()}${
            priorityReason ? `\nPriorityReason: ${priorityReason}` : ''
          }`
        : description;
    const valuesV1 = [
      fallbackDescription,
      reporterName,
      reporterEmail,
      pageUrl,
      attachmentName,
      attachmentType,
      attachmentData
    ];

    let result;
    try {
      result = await pool.query(insertSqlV3, valuesV3);
    } catch (error) {
      const code = (error as { code?: string })?.code;
      if (code !== '42703') throw error;

      try {
        result = await pool.query(insertSqlV2, valuesV2);
      } catch (error2) {
        const code2 = (error2 as { code?: string })?.code;
        if (code2 !== '42703') throw error2;
        result = await pool.query(insertSqlV1, valuesV1);
      }
    }

    const incidentId = result.rows[0]?.id;
    if (incidentId && attachments.length > 0) {
      try {
        await insertAttachments(incidentId, attachments);
      } catch (error) {
        const code = (error as { code?: string })?.code;
        // If attachment table is not available yet, keep backward compatibility.
        if (code !== '42P01' && code !== '42703') throw error;
      }
    }

    response.status(OK);
    response.$body = {
      success: true,
      incidentId,
      attachmentCount: attachments.length
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
