import os
from dataclasses import dataclass
from typing import Iterable


DEFAULT_CODE_EXTENSIONS = (
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".mjs",
    ".cjs",
    ".json",
    ".graphql",
    ".gql",
    ".md",
    ".yml",
    ".yaml",
    ".sql",
    ".css",
    ".scss",
)

DEFAULT_CODE_FILENAMES = (
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "package.json",
    "tsconfig.json",
    "jest.config.js",
    "eslint.config.js",
)

DEFAULT_EXCLUDED_DIRS = (
    ".git",
    "node_modules",
    "dist",
    "build",
    "coverage",
    ".next",
    ".turbo",
    ".vscode",
    ".idea",
    "media",
    "public",
)


def _parse_csv(raw: str | None, fallback: Iterable[str]) -> tuple[str, ...]:
    if not raw:
        return tuple(fallback)
    return tuple(item.strip() for item in raw.split(",") if item.strip())


@dataclass(frozen=True)
class RagConfig:
    qdrant_url: str
    qdrant_collection: str
    openai_embedding_model: str
    chunk_size: int
    chunk_overlap: int
    max_file_bytes: int
    include_extensions: tuple[str, ...]
    include_filenames: tuple[str, ...]
    exclude_dirs: tuple[str, ...]

    @staticmethod
    def from_env() -> "RagConfig":
        return RagConfig(
            qdrant_url=os.getenv("QDRANT_URL", "http://qdrant:6333"),
            qdrant_collection=os.getenv("QDRANT_COLLECTION", "evershop_codebase"),
            openai_embedding_model=os.getenv(
                "OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"
            ),
            chunk_size=int(os.getenv("RAG_CHUNK_SIZE", "1200")),
            chunk_overlap=int(os.getenv("RAG_CHUNK_OVERLAP", "200")),
            max_file_bytes=int(os.getenv("RAG_MAX_FILE_BYTES", "800000")),
            include_extensions=_parse_csv(
                os.getenv("RAG_INCLUDE_EXTENSIONS"), DEFAULT_CODE_EXTENSIONS
            ),
            include_filenames=_parse_csv(
                os.getenv("RAG_INCLUDE_FILENAMES"), DEFAULT_CODE_FILENAMES
            ),
            exclude_dirs=_parse_csv(
                os.getenv("RAG_EXCLUDE_DIRS"), DEFAULT_EXCLUDED_DIRS
            ),
        )
