import React from 'react';
import { ArrowUp, TriangleAlert, Paperclip, Bug, Mic, Square } from 'lucide-react';
import './IncidentReporter.scss';

interface IncidentReporterProps {
  apiUrl: string;
  source: 'admin' | 'frontStore';
}

export default function IncidentReporter({ apiUrl, source }: IncidentReporterProps) {
  const fileInputRef = React.useRef<HTMLInputElement | null>(null);
  const mediaRecorderRef = React.useRef<MediaRecorder | null>(null);
  const chunksRef = React.useRef<BlobPart[]>([]);
  const [open, setOpen] = React.useState(false);
  const [message, setMessage] = React.useState('');
  const [files, setFiles] = React.useState<File[]>([]);
  const [isRecording, setIsRecording] = React.useState(false);
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [result, setResult] = React.useState<{
    type: 'success' | 'error';
    text: string;
  } | null>(null);

  const addFiles = (newFiles: FileList | null) => {
    if (!newFiles || newFiles.length === 0) return;
    setFiles((prev) => [...prev, ...Array.from(newFiles)].slice(0, 6));
  };

  const removeFile = (index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  };

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

  const submit = async () => {
    const hasText = message.trim().length > 0;
    if (!hasText && files.length === 0) {
      setResult({
        type: 'error',
        text: 'Write a short description or attach at least one file/audio.'
      });
      return;
    }

    try {
      setIsSubmitting(true);
      setResult(null);
      const formData = new FormData();
      formData.append('description', message.trim());
      formData.append(
        'page_url',
        typeof window !== 'undefined' ? window.location.href : ''
      );
      files.slice(0, 1).forEach((file) => formData.append('attachment', file));

      const response = await fetch(apiUrl, {
        method: 'POST',
        body: formData
      });
      const payload = await response.json();
      if (!response.ok || payload?.error) {
        throw new Error(payload?.error?.message || 'Request failed');
      }

      setResult({
        type: 'success',
        text: `Incident sent. Id: ${payload?.data?.incidentId || 'created'}`
      });
      setMessage('');
      setFiles([]);
    } catch (error) {
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
        <div className="incident-reporter-overlay" onClick={() => setOpen(false)}>
          <div className="incident-reporter-chat" onClick={(e) => e.stopPropagation()}>
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
