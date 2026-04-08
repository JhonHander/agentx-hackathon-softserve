import multer from 'multer';
import { INVALID_PAYLOAD } from '../../../../lib/util/httpStatus.js';
import customMemoryStorage from '../../services/CustomMemoryStorage.js';
import { generateFileName } from '../../services/generateFileName.js';

const storage = customMemoryStorage({ filename: generateFileName });
const MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024; // 10MB for hackathon usage

const ALLOWED_MIME_TYPES = new Set([
  // Images
  'image/jpeg',
  'image/png',
  'image/gif',
  'image/webp',
  'image/avif',
  'image/svg+xml',
  // Audio
  'audio/mpeg',
  'audio/wav',
  'audio/webm',
  'audio/ogg',
  'audio/mp4',
  // Video
  'video/mp4',
  'video/webm',
  'video/ogg',
  'video/quicktime',
  // Generic useful docs/logs
  'application/pdf',
  'text/plain'
]);

const upload = multer({
  storage,
  limits: {
    files: 1,
    fileSize: MAX_FILE_SIZE_BYTES
  },
  fileFilter: (request, file, cb) => {
    if (!ALLOWED_MIME_TYPES.has(file.mimetype)) {
      cb(new Error(`File type not allowed: ${file.mimetype}`));
      return;
    }
    cb(null, true);
  }
});

export default (request, response, next) => {
  // Support both field names:
  // - attachment (expected for this endpoint contract)
  // - attachments (backward compatibility with the current chat UI)
  upload.fields([
    { name: 'attachment', maxCount: 1 },
    { name: 'attachments', maxCount: 1 }
  ])(request, response, (error) => {
    if (error) {
      response.status(INVALID_PAYLOAD).json({
        error: {
          status: INVALID_PAYLOAD,
          message: error.message
        }
      });
      return;
    }
    next();
  });
};
