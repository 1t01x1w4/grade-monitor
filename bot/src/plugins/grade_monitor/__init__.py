import logging
from nonebot import get_driver
from .scheduler import start_scheduler, shutdown_scheduler
from .detector import reset_first_load

logger = logging.getLogger(__name__)

driver = get_driver()


@driver.on_startup
async def _on_startup():
    logger.info("成绩监控插件启动中...")
    start_scheduler()
    reset_first_load()
    logger.info("成绩监控插件已就绪")


@driver.on_shutdown
async def _on_shutdown():
    logger.info("成绩监控插件正在关闭...")
    shutdown_scheduler()
    logger.info("成绩监控插件已关闭")
