"""Logging setup for the BytsOne bot."""

import logging
import os
import colorlog


def setup_logger(name: str) -> logging.Logger:
    """Create a named logger with color console output and file output."""
    from src.config.settings import settings

    os.makedirs(os.path.dirname(settings.log_file), exist_ok=True)

    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured

    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logger.setLevel(level)

    # Colored console handler
    console = colorlog.StreamHandler()
    console.setFormatter(colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    ))
    console.setLevel(level)

    # File handler
    file_handler = logging.FileHandler(settings.log_file, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))
    file_handler.setLevel(level)

    logger.addHandler(console)
    logger.addHandler(file_handler)
    return logger
