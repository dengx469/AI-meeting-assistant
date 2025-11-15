import logging, sys, os

LOGGER_NAME = "gmail_push_logger"
logger = logging.getLogger(LOGGER_NAME)

if not logger.handlers:
    level = os.getenv("LOG_LEVEL", "DEBUG").upper()
    logger.setLevel(level)
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

logger.info(f"✅ Logger initialized, level={logging.getLevelName(logger.level)}")
