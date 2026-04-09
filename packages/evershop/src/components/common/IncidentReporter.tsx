import {
  ArrowUp,
  TriangleAlert,
  Paperclip,
  Bug,
  Mic,
  Square
} from 'lucide-react';
import React from 'react';
import './IncidentReporter.scss';

interface IncidentReporterProps {
  apiUrl: string;
  orchestratorApiUrl?: string;
  source: 'admin' | 'frontStore';
}

type ChatTurn = {
  role: 'assistant' | 'user';
  text: string;
};

type ReporterResult = {
  type: 'success' | 'error';
  text: string;
};

type OrchestratorAttachmentPayload = {
  name: string;
  type: string;
  data_base64: string;
  size: number;
};

function extractPayloadData(payload: unknown): unknown {
  if (!payload || typeof payload !== 'object') return payload;
  return (payload as { data?: unknown }).data ?? payload;
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result !== 'string') {
        reject(new Error(`Could not read file: ${file.name}`));
        return;
      }
      const commaIndex = reader.result.indexOf(',');
      const base64 =
        commaIndex >= 0 ? reader.result.slice(commaIndex + 1) : reader.result;
      if (!base64) {
        reject(new Error(`Could not encode file: ${file.name}`));
        return;
      }
      resolve(base64);
    };
    reader.onerror = () => reject(new Error(`Could not read file: ${file.name}`));
    reader.readAsDataURL(file);
  });
}

export default function IncidentReporter({
  apiUrl,
  orchestratorApiUrl,
  source
}: IncidentReporterProps) {
  const fileInputRef = React.useRef<HTMLInputElement | null>(null);
  const conversationRef = React.useRef<HTMLDivElement | null>(null);
  const mediaRecorderRef = React.useRef<MediaRecorder | null>(null);
  const chunksRef = React.useRef<BlobPart[]>([]);
  const [open, setOpen] = React.useState(false);
  const [message, setMessage] = React.useState('');
  const [files, setFiles] = React.useState<File[]>([]);
  const [isRecording, setIsRecording] = React.useState(false);
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [sessionId, setSessionId] = React.useState<string | null>(null);
  const [chatTurns, setChatTurns] = React.useState<ChatTurn[]>([]);
  const [result, setResult] = React.useState<ReporterResult | null>(null);

  const addFiles = (newFiles: FileList | null) => {
    if (!newFiles || newFiles.length === 0) return;
    setFiles((prev) => [...prev, ...Array.from(newFiles)].slice(0, 6));
  };

  const removeFile = (index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const appendTurn = (turn: ChatTurn) => {
    setChatTurns((prev) => [...prev, turn]);
  };

  const scrollConversationToBottom = React.useCallback(() => {
    if (!conversationRef.current) return;
    conversationRef.current.scrollTop = conversationRef.current.scrollHeight;
  }, []);

  React.useEffect(() => {
    if (!open) return;
    // Wait for DOM paint after turn updates.
    requestAnimationFrame(() => {
      scrollConversationToBottom();
    });
  }, [open, chatTurns, result, isSubmitting, scrollConversationToBottom]);

  const stopRecording = () => {
    const recorder = mediaRecorderRef.current;
    if (!recorder) return;
    recorder.stop();
    setIsRecording(false);
  };

  const startRecording = async () => {
    if (typeof window === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      setResult({
        type: 'error',
        text: 'Audio recording is not supported in this browser.'
      });
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType });
        const extension = recorder.mimeType.includes('ogg') ? 'ogg' : 'webm';
        const audioFile = new File([blob], `voice-note-${Date.now()}.${extension}`, {
          type: recorder.mimeType || 'audio/webm'
        });
        setFiles((prev) => [...prev, audioFile].slice(0, 6));
        stream.getTracks().forEach((track) => track.stop());
      };
      recorder.start();
      mediaRecorderRef.current = recorder;
      setIsRecording(true);
      setResult(null);
    } catch (error) {
      setResult({
        type: 'error',
        text: error instanceof Error ? error.message : 'Could not start recording'
      });
    }
  };

  const submitToOrchestrator = async (text: string, attachedFiles: File[]) => {
    const trimmedText = text.trim();
    const filesToSend = attachedFiles.slice(0, 6);
    if (!trimmedText && filesToSend.length === 0) {
      throw new Error('Write a message or attach a file before sending.');
    }
    if (!orchestratorApiUrl) {
      throw new Error('Orchestrator endpoint is not configured');
    }

    const attachmentPayload: OrchestratorAttachmentPayload[] = await Promise.all(
      filesToSend.map(async (file) => ({
        name: file.name || `attachment-${Date.now()}.bin`,
        type: file.type || 'application/octet-stream',
        data_base64: await fileToBase64(file),
        size: file.size
      }))
    );

    const userTurnText = trimmedText
      ? attachmentPayload.length > 0
        ? `${trimmedText}\n\n(Adjuntos: ${attachmentPayload
            .map((item) => item.name)
            .join(', ')})`
        : trimmedText
      : `Adjunte ${attachmentPayload.length} archivo(s): ${attachmentPayload
          .map((item) => item.name)
          .join(', ')}`;

    appendTurn({ role: 'user', text: userTurnText });
    const requestBody = {
      session_id: sessionId,
      message: trimmedText,
      source,
      page_url: typeof window !== 'undefined' ? window.location.href : '',
      reporter_name: null,
      reporter_email: null,
      attachments_base64: attachmentPayload
    };

    const response = await fetch(orchestratorApiUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(requestBody)
    });

    const payload = await response.json().catch(() => ({}));
    const data = extractPayloadData(payload) as
      | {
          session_id?: string;
          status?: string;
          assistant_message?: string;
          incident_id?: string | number;
          jira?: { issue_key?: string };
          error?: { message?: string };
        }
      | undefined;

    const errorMessage =
      data?.error?.message ||
      payload?.error?.message ||
      payload?.detail ||
      (!response.ok ? 'Orchestrator request failed' : '');
    if (errorMessage) {
      throw new Error(errorMessage);
    }

    if (data?.session_id) {
      setSessionId(data.session_id);
    }

    if (data?.assistant_message) {
      appendTurn({ role: 'assistant', text: data.assistant_message });
    }

    if (data?.status === 'completed') {
      const jiraKey = data?.jira?.issue_key;
      setResult({
        type: 'success',
        text: `Incident sent. Id: ${data?.incident_id || 'created'}${
          jiraKey ? ` | Jira: ${jiraKey}` : ''
        }`
      });
    } else {
      setResult(null);
    }

    setMessage('');
    if (attachmentPayload.length > 0) {
      setFiles([]);
    }
  };

  const submitToLegacyIncident = async (text: string) => {
    const hasText = text.trim().length > 0;
    if (!hasText) {
      throw new Error('Write a short description before sending the incident.');
    }

    const formData = new FormData();
    formData.append('description', text.trim());
    formData.append(
      'page_url',
      typeof window !== 'undefined' ? window.location.href : ''
    );
    files.slice(0, 6).forEach((file) => formData.append('attachments', file));

    const response = await fetch(apiUrl, {
      method: 'POST',
      body: formData
    });

    const payload = await response.json().catch(() => ({}));
    const data = extractPayloadData(payload) as
      | { incidentId?: string | number; error?: { message?: string } }
      | undefined;
    if (!response.ok || payload?.error || data?.error) {
      throw new Error(
        data?.error?.message || payload?.error?.message || 'Request failed'
      );
    }

    setResult({
      type: 'success',
      text: `Incident sent. Id: ${data?.incidentId || 'created'}`
    });
    setMessage('');
    setFiles([]);
  };

  const submit = async () => {
    const text = message.trim();
    try {
      setIsSubmitting(true);
      setResult(null);
      setMessage('');

      const shouldUseOrchestrator = Boolean(orchestratorApiUrl);

      if (shouldUseOrchestrator) {
        await submitToOrchestrator(text, files);
      } else {
        await submitToLegacyIncident(text);
      }
    } catch (error) {
      // Restore user input if request fails.
      setMessage(text);
      setResult({
        type: 'error',
        text: error instanceof Error ? error.message : 'Could not send incident'
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <>
      <button
        type="button"
        className="incident-reporter-trigger"
        onClick={() => setOpen(true)}
        aria-label="Open incident reporter"
      >
        <TriangleAlert size={16} />
        <span>Report incident</span>
      </button>

      {open && (
        <div
          className="incident-reporter-overlay"
          role="button"
          tabIndex={0}
          onClick={(event) => {
            if (event.target === event.currentTarget) {
              setOpen(false);
            }
          }}
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              setOpen(false);
            }
          }}
          aria-label="Close incident reporter"
        >
          <div className="incident-reporter-chat">
            <div className="incident-reporter-hero">
              <div className="incident-reporter-logo">
                <Bug size={22} />
              </div>
              <h3>Hi there!</h3>
              <p>
                Tell us what happened and we will create an incident report for the
                team.
              </p>
              <button type="button" onClick={() => setOpen(false)}>
                Close
              </button>
            </div>

            <div className="incident-reporter-chat-body">
              <input
                ref={fileInputRef}
                type="file"
                hidden
                multiple
                accept="image/*,video/*,audio/*"
                onChange={(e) => addFiles(e.target.files)}
              />

              {files.length > 0 && (
                <div className="incident-reporter-files">
                  {files.map((file, index) => (
                    <div key={`${file.name}-${index}`} className="incident-file-item">
                      <span title={file.name}>{file.name}</span>
                      <button type="button" onClick={() => removeFile(index)}>
                        Remove
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {result && (
                <div className={`incident-reporter-result ${result.type}`}>
                  {result.text}
                </div>
              )}

              {chatTurns.length > 0 && (
                <div className="incident-reporter-conversation" ref={conversationRef}>
                  {chatTurns.map((turn, index) => (
                    <div
                      key={`${turn.role}-${index}`}
                      className={`incident-turn ${turn.role}`}
                    >
                      {turn.text}
                    </div>
                  ))}
                </div>
              )}

              <div className="incident-reporter-composer">
                <button
                  type="button"
                  className="icon-btn"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={files.length >= 6 || isSubmitting}
                  title="Attach photo/video"
                  aria-label="Attach photo or video"
                >
                  <Paperclip size={18} />
                </button>

                <textarea
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && !event.shiftKey) {
                      event.preventDefault();
                      event.stopPropagation();
                      if (
                        !isSubmitting &&
                        (message.trim().length > 0 || files.length > 0)
                      ) {
                        void submit();
                      }
                    }
                  }}
                  placeholder="Describe the issue..."
                  rows={1}
                  maxLength={4000}
                />

                {!isRecording ? (
                  <button
                    type="button"
                    className="icon-btn"
                    onClick={startRecording}
                    disabled={isSubmitting}
                    title="Record audio"
                    aria-label="Record audio"
                  >
                    <Mic size={18} />
                  </button>
                ) : (
                  <button
                    type="button"
                    className="icon-btn danger"
                    onClick={stopRecording}
                    title="Stop recording"
                    aria-label="Stop recording"
                  >
                    <Square size={16} />
                  </button>
                )}

                <button
                  type="button"
                  className="send-btn"
                  disabled={isSubmitting}
                  onClick={submit}
                  title="Send"
                  aria-label="Send"
                >
                  {isSubmitting ? '...' : <ArrowUp size={18} />}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
