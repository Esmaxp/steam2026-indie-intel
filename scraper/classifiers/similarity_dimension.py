"""Offline nearest-neighbour dimension inference (no API key, no network).

A game whose 2D/3D dimension the tag map and the rule fallback both failed to
settle is compared against games that *are* settled, using TF-IDF over their
tags and store description plus cosine similarity. If a clear majority of the
nearest neighbours share one dimension, that dimension is proposed; otherwise
the game stays unknown, exactly as the rest of the pipeline behaves when
signals disagree.

This module is deliberately pure: it takes plain values, returns plain values,
touches no database and makes no HTTP call of any kind. scikit-learn runs
entirely locally — nothing here contacts a third-party service. The batch job
that feeds it from the database lives in workers/classify_dimension_local.py.

Why label tags are stripped: a known game tagged "2D" carries its own answer in
its text. Leaving those tokens in would let the index match on the label rather
than on what the game actually is — and an unknown game can never carry them
anyway (that is precisely why it is unknown), so they add noise to every vector
and signal to none.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

from app.models import Dimension

# Tags whose name states the dimension outright — see classify._DIMENSION_TAGS.
LABEL_TAGS = frozenset({"2d", "2.5d", "3d", "2d platformer", "3d platformer"})

# Tags are curated, vote-ranked signals; a description is dozens of loose words.
# Repeating tag tokens keeps them from being drowned out by prose.
TAG_REPEAT = 3

# Defaults chosen by holdout measurement over 2,000 games whose dimension is
# already settled (workers/classify_dimension_local.py --validate), not by feel:
#
#   k=5,  agree>=70%, min_sim 0.05 → 72% coverage, 87.4% accuracy
#   k=9,  agree>=70%, min_sim 0.10 → 68% coverage, 89.3% accuracy   <- default
#   k=9,  agree>=80%, min_sim 0.15 → 46% coverage, 92.0% accuracy
#   k=15, agree>=80%, min_sim 0.15 → 58% coverage, 91.1% accuracy
#
# The k=9 row buys ~2 points of accuracy for ~4 points of coverage; the 80%
# rows give up far too much reach for the next 3 points. All four are still
# reachable by flag — re-measure before changing these.
DEFAULT_K = 9
DEFAULT_THRESHOLD = 0.7
DEFAULT_MIN_SIMILARITY = 0.10
DEFAULT_MIN_NEIGHBOURS = 3


def build_document(tags: Sequence[str], description: str | None) -> str:
    """One text blob per game: weighted tag tokens + the store description."""
    tokens: list[str] = []
    for tag in tags:
        normalized = tag.strip().lower()
        if not normalized or normalized in LABEL_TAGS:
            continue
        # Multi-word tags become single tokens so "twin stick shooter" cannot
        # be matched by an unrelated game that merely says "shooter".
        tokens.extend([normalized.replace(" ", "_").replace("-", "_")] * TAG_REPEAT)
    return " ".join(tokens) + " " + (description or "").strip()


@dataclass(frozen=True)
class KnownGame:
    appid: int
    name: str
    dimension: Dimension
    document: str


@dataclass(frozen=True)
class Neighbour:
    appid: int
    name: str
    dimension: Dimension
    similarity: float


@dataclass(frozen=True)
class Prediction:
    """dimension is None when the neighbours do not justify a call."""

    dimension: Dimension | None
    agreement: float
    neighbours: tuple[Neighbour, ...]
    reason: str


class DimensionSimilarityIndex:
    """TF-IDF index over games whose dimension is already settled."""

    def __init__(self, known: Sequence[KnownGame], min_df: int = 2):
        if not known:
            raise ValueError("cannot build a similarity index with no known games")
        self.known = list(known)
        self.vectorizer = TfidfVectorizer(
            min_df=min_df,          # a token seen once carries no similarity signal
            max_df=0.6,             # drop boilerplate present in most store pages
            sublinear_tf=True,      # a word repeated 20× is not 20× more relevant
            stop_words="english",
        )
        # TfidfVectorizer L2-normalises rows, so a dot product IS cosine
        # similarity — that is why linear_kernel is used below rather than the
        # slower cosine_similarity wrapper.
        self.matrix = self.vectorizer.fit_transform(g.document for g in self.known)
        self.dimensions = [g.dimension for g in self.known]

    def predict(
        self,
        documents: Sequence[str],
        k: int = DEFAULT_K,
        threshold: float = DEFAULT_THRESHOLD,
        min_similarity: float = DEFAULT_MIN_SIMILARITY,
        min_neighbours: int = DEFAULT_MIN_NEIGHBOURS,
    ) -> list[Prediction]:
        """One prediction per input document, in the same order."""
        if not documents:
            return []
        queries = self.vectorizer.transform(documents)
        sims = linear_kernel(queries, self.matrix)  # (n_documents, n_known)

        predictions: list[Prediction] = []
        for row in sims:
            take = min(k, row.shape[0])
            # argpartition finds the k best without sorting all 20k scores.
            top = np.argpartition(row, -take)[-take:]
            top = top[np.argsort(row[top])[::-1]]
            neighbours = tuple(
                Neighbour(
                    appid=self.known[i].appid,
                    name=self.known[i].name,
                    dimension=self.dimensions[i],
                    similarity=float(row[i]),
                )
                for i in top
            )
            predictions.append(
                decide(neighbours, threshold, min_similarity, min_neighbours)
            )
        return predictions


def decide(
    neighbours: tuple[Neighbour, ...],
    threshold: float,
    min_similarity: float,
    min_neighbours: int,
) -> Prediction:
    """Majority vote over the neighbours that are actually similar."""
    close = tuple(n for n in neighbours if n.similarity >= min_similarity)
    if len(close) < min_neighbours:
        return Prediction(
            dimension=None,
            agreement=0.0,
            neighbours=neighbours,
            reason=(
                f"only {len(close)} neighbour(s) above similarity {min_similarity} "
                f"— too little to compare against"
            ),
        )

    votes: dict[Dimension, int] = {}
    for neighbour in close:
        votes[neighbour.dimension] = votes.get(neighbour.dimension, 0) + 1
    winner, count = max(votes.items(), key=lambda item: item[1])
    agreement = count / len(close)

    if agreement < threshold:
        breakdown = ", ".join(f"{d.value}×{c}" for d, c in sorted(votes.items(), key=str))
        return Prediction(
            dimension=None,
            agreement=agreement,
            neighbours=neighbours,
            reason=f"neighbours disagree ({breakdown}) — {agreement:.0%} below {threshold:.0%}",
        )

    return Prediction(
        dimension=winner,
        agreement=agreement,
        neighbours=neighbours,
        reason=(
            f"{count}/{len(close)} nearest games are {winner.value} "
            f"(top similarity {close[0].similarity:.2f})"
        ),
    )
