#!/usr/bin/env python3
import argparse, re, sys, os
from typing import List
import numpy as np

def load_sentences(path: str, per_line: bool = False) -> List[str]:
    if not os.path.isfile(path):
        sys.exit(f"File not found: {path}")
    text = open(path, "r", encoding="utf-8", errors="ignore").read()

    if per_line:
        items = [ln.strip() for ln in text.splitlines() if ln.strip()]
    else:
        # Simple sentence splitter for English punctuation.
        items = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]

    # De-duplicate while preserving order
    seen = set()
    uniq = []
    for s in items:
        if s not in seen:
            uniq.append(s)
            seen.add(s)
    return uniq

def main():
    ap = argparse.ArgumentParser(
        description="Semantic search over a text file using sentence embeddings."
    )
    ap.add_argument("path", help="Path to a text file.")
    ap.add_argument("query", help='Search phrase (wrap in quotes on the command line).')
    ap.add_argument("--topk", type=int, default=3, help="How many results to show.")
    ap.add_argument("--per-line", action="store_true",
                    help="Treat each non-empty line as an item (skip sentence splitting).")
    ap.add_argument("--model", default="sentence-transformers/all-MiniLM-L6-v2",
                    help="Sentence embedding model (default: all-MiniLM-L6-v2).")
    ap.add_argument("--batch-size", type=int, default=64, help="Embedding batch size.")

    args = ap.parse_args()

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        sys.exit(
            "Missing dependency: sentence-transformers. Install with:\n"
            "  pip install -U sentence-transformers torch numpy"
        )

    sentences = load_sentences(args.path, per_line=args.per_line)
    if not sentences:
        sys.exit("No sentences found in the input file.")

    # Load model
    model = SentenceTransformer(args.model)

    # Embed corpus and query; normalize so cosine = dot product.
    corpus_emb = model.encode(
        sentences, batch_size=args.batch_size, convert_to_numpy=True, normalize_embeddings=True
    )
    query_emb = model.encode([args.query], convert_to_numpy=True, normalize_embeddings=True)[0]

    # Cosine similarity via dot product (already normalized)
    sims = np.dot(corpus_emb, query_emb)

    # Get top-k indices
    k = max(1, min(args.topk, len(sentences)))
    top_idx = np.argpartition(-sims, k-1)[:k]
    # Sort those by score descending
    top_idx = top_idx[np.argsort(-sims[top_idx])]

    # Pretty print
    for rank, i in enumerate(top_idx, start=1):
        score = float(sims[i])
        # Clamp slight numerical drift
        score = max(min(score, 1.0), -1.0)
        print(f"{rank}. score={score:.4f}  |  {sentences[i]}")

if __name__ == "__main__":
    main()
