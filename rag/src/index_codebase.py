import argparse
import json

from indexer import run_indexing
from rag_config import RagConfig


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Index a codebase into Qdrant.")
    parser.add_argument(
        "--repo-path",
        default="/workspace/repo",
        help="Path to the code repository to index.",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append to an existing collection instead of recreating it.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=64,
        help="Batch size for vector upserts.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    config = RagConfig.from_env()

    result = run_indexing(
        repo_path=args.repo_path,
        config=config,
        recreate_collection=not args.append,
        batch_size=args.batch_size,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
