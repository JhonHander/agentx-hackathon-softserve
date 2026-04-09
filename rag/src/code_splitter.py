from langchain_text_splitters import Language, RecursiveCharacterTextSplitter


LANGUAGE_BY_EXTENSION = {
    ".py": Language.PYTHON,
    ".js": Language.JS,
    ".jsx": Language.JS,
    ".ts": Language.TS,
    ".tsx": Language.TS,
    ".java": Language.JAVA,
    ".go": Language.GO,
    ".rs": Language.RUST,
    ".rb": Language.RUBY,
    ".php": Language.PHP,
    ".scala": Language.SCALA,
    ".swift": Language.SWIFT,
    ".sol": Language.SOL,
    ".cs": Language.CSHARP,
    ".c": Language.CPP,
    ".cc": Language.CPP,
    ".cpp": Language.CPP,
    ".h": Language.CPP,
    ".hpp": Language.CPP,
    ".md": Language.MARKDOWN,
    ".html": Language.HTML,
    ".tex": Language.LATEX,
}


def build_splitter(
    extension: str,
    chunk_size: int,
    chunk_overlap: int,
) -> RecursiveCharacterTextSplitter:
    language = LANGUAGE_BY_EXTENSION.get(extension.lower())
    if language is not None:
        return RecursiveCharacterTextSplitter.from_language(
            language=language,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            add_start_index=True,
        )

    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        add_start_index=True,
        separators=[
            "\n\n",
            "\n",
            " ",
            "",
        ],
    )
