"""中英文关键词 BM25；不把关键词召回称为语义向量检索。"""

import math
import re
from collections import Counter


def tokenize(text):
    tokens = re.findall(r"[a-z0-9_]+", text.lower())
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        tokens.extend(run[i : i + 2] for i in range(max(1, len(run) - 1)))
    return tokens


def retrieve(store, question, document_id=None, limit=6):
    condition = "WHERE c.document_id=?" if document_id else ""
    rows = store.query(
        f"SELECT c.*,d.title AS document_title,d.format,d.digest AS version FROM chunks c JOIN documents d ON d.id=c.document_id {condition}",
        (document_id,) if document_id else (),
    )
    qtokens = set(tokenize(question))
    counts = [Counter(tokenize(row["section"] + " " + row["text"])) for row in rows]
    frequencies = Counter(t for tokens in counts for t in tokens)
    average = sum(sum(c.values()) for c in counts) / max(len(counts), 1)
    ranked = []
    for row, tokens in zip(rows, counts, strict=True):
        size = sum(tokens.values())
        score = 0.0
        for token in qtokens:
            if token not in tokens:
                continue
            weight = math.log(
                1 + (len(rows) - frequencies[token] + 0.5) / (frequencies[token] + 0.5)
            )
            frequency = tokens[token]
            score += (
                weight
                * frequency
                * 2.2
                / (frequency + 1.2 * (0.25 + 0.75 * size / max(average, 1)))
            )
        if score > 0:
            ranked.append((score, row))
    ranked.sort(key=lambda value: (-value[0], value[1]["ordinal"]))
    return [{**row, "label": f"S{i + 1}"} for i, (_, row) in enumerate(ranked[:limit])]
