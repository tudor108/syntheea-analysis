"""Central logging configuration."""
import logging


def configure_logging(level: str = "INFO") -> None:
    """Configure consistent timestamped pipeline logging."""
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        force=True,
    )
