"""GuardianLens — on-device AI child safety monitor powered by Gemma 4 + Ollama.

The package keeps ``__init__`` deliberately empty (no eager imports) so that
leaf modules like :mod:`guardlens.schema` can be imported in environments
that don't have every optional dep installed (e.g. a Kaggle eval notebook
that only needs the Pydantic models). Reach for the submodules directly:

>>> from guardlens.pipeline import ConversationPipeline
>>> from guardlens.config import load_config
>>> from guardlens.schema import ConversationStatus
"""

__version__ = "0.1.0"
