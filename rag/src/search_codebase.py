import argparse
import json

from rag_config import RagConfig
from retriever import search_code_chunks


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search indexed code chunks in Qdrant.")
    parser.add_argument("--query", required=True, help="Semantic query text.")
    parser.add_argument("--k", type=int, default=8, help="Number of chunks to retrieve.")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    config = RagConfig.from_env()
    results = search_code_chunks(query=args.query, config=config, k=args.k)
    print(json.dumps(results, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
