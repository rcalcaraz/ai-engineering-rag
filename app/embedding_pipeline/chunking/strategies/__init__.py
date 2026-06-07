"""Chunking strategies behind the common :class:`~app.embedding_pipeline.chunking.base.Chunker`
interface (the structural chunker lives in ``app.embedding_pipeline.chunking.structural``).
"""

from app.embedding_pipeline.chunking.strategies.fixed_size import FixedSizeChunker

__all__ = ["FixedSizeChunker"]
