import {
  INTERNAL_SERVER_ERROR,
  INVALID_PAYLOAD,
  OK
} from '../../../../lib/util/httpStatus.js';

const LOCAL_ORCHESTRATOR_URL =
  'http://localhost:8008/agents/orchestrator/message';
const LOCAL_LOOPBACK_ORCHESTRATOR_URL =
  'http://127.0.0.1:8008/agents/orchestrator/message';

function getOrchestratorCandidates(): string[] {
  const configured = `${process.env.RAG_ORCHESTRATOR_MESSAGE_URL || ''}`.trim();
  if (configured) {
    return [configured];
  }
  return [
    LOCAL_ORCHESTRATOR_URL,
    LOCAL_LOOPBACK_ORCHESTRATOR_URL
  ];
}

export default async (request, response, next) => {
  try {
    const message = `${request.body?.message || ''}`.trim();
    const attachmentsBase64 = Array.isArray(request.body?.attachments_base64)
      ? request.body.attachments_base64
      : [];
    if (!message && attachmentsBase64.length === 0) {
      response.status(INVALID_PAYLOAD);
      response.$body = {
        error: {
          status: INVALID_PAYLOAD,
          message: 'message or attachments_base64 is required'
        }
      };
      next();
      return;
    }

    const payload = {
      session_id: request.body?.session_id || null,
      message,
      source: request.body?.source || null,
      page_url: request.body?.page_url || request.headers.referer || null,
      reporter_name: request.body?.reporter_name || null,
      reporter_email: request.body?.reporter_email || null,
      attachments_base64: attachmentsBase64
    };

    const timeoutMs = Number(process.env.RAG_ORCHESTRATOR_TIMEOUT_MS || 30000);

    let lastConnectionError: unknown = null;
    for (const orchestratorUrl of getOrchestratorCandidates()) {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), timeoutMs);

      let orchestratorResponse;
      try {
        orchestratorResponse = await fetch(orchestratorUrl, {
          method: 'POST',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json'
          },
          body: JSON.stringify(payload),
          signal: controller.signal
        });
      } catch (error) {
        lastConnectionError = error;
        continue;
      } finally {
        clearTimeout(timeout);
      }

      const responseBody = await orchestratorResponse.json().catch(() => ({}));
      if (!orchestratorResponse.ok) {
        response.status(orchestratorResponse.status || INTERNAL_SERVER_ERROR);
        response.$body = {
          error: {
            status: orchestratorResponse.status || INTERNAL_SERVER_ERROR,
            message:
              responseBody?.detail ||
              responseBody?.error?.message ||
              'Orchestrator service failed'
          }
        };
        next();
        return;
      }

      response.status(OK);
      response.$body = responseBody;
      next();
      return;
    }

    throw (
      lastConnectionError ||
      new Error('Could not connect to any orchestrator endpoint')
    );
  } catch (error) {
    response.status(INTERNAL_SERVER_ERROR);
    response.$body = {
      error: {
        status: INTERNAL_SERVER_ERROR,
        message:
          error instanceof Error
            ? error.message
            : 'Could not call orchestrator service'
      }
    };
    next();
  }
};
