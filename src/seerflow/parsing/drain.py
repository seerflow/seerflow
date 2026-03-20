"""Drain3 parser wrapper — streaming log template extraction."""
from __future__ import annotations

import re

_IP_RE = re.compile(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}")
_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def _mask_tokens(message: str) -> str:
    """Pre-process message by masking IPs and UUIDs for better template stability."""
    message = _IP_RE.sub("<IP>", message)
    return _UUID_RE.sub("<UUID>", message)


def _extract_params(message: str, template: str) -> tuple[str, ...]:
    """Extract parameter values by comparing message tokens with template wildcards."""
    return ()  # implemented in Task 4


class DrainParser:
    """Streaming log template extractor wrapping drain3.TemplateMiner.

    Masks IPs and UUIDs before parsing to improve template stability.
    """

    __slots__ = ("_miner",)

    def __init__(
        self,
        *,
        sim_th: float = 0.4,
        depth: int = 4,
        max_clusters: int = 1000,
    ) -> None:
        from drain3 import TemplateMiner
        from drain3.template_miner_config import TemplateMinerConfig

        config = TemplateMinerConfig()
        config.drain_sim_th = sim_th
        config.drain_depth = depth
        config.drain_max_clusters = max_clusters
        config.parametrize_numeric_tokens = True

        self._miner = TemplateMiner(config=config)

    def parse(self, message: str) -> tuple[int, str, tuple[str, ...]]:
        """Extract template from a log message.

        Returns:
            (template_id, template_str, params) where params are the
            variable parts replaced by ``<*>`` in the template.
        """
        masked = _mask_tokens(message)
        result: dict[str, object] = self._miner.add_log_message(masked)
        template = str(result["template_mined"])
        cluster_id = int(result["cluster_id"])  # type: ignore[arg-type]
        params = _extract_params(masked, template)
        return cluster_id, template, params

    @property
    def template_count(self) -> int:
        """Number of unique templates discovered so far."""
        return len(self._miner.drain.clusters)
