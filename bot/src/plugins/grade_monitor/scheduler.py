import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from . import config_manager as cfg

logger = logging.getLogger(__name__)

scheduler: AsyncIOScheduler | None = None
_next_run_time: datetime | None = None


async def _scheduled_check():
    """定时检查成绩，检测到新成绩时通过 QQ 通知"""
    from . import scraper, detector, storage

    if not cfg.has_credentials():
        logger.warning("定时检查: 未配置账号密码，跳过")
        return

    db = await storage.get_db()
    try:
        try:
            grades = await scraper.fetch_grades()
        except scraper.LoginError as e:
            logger.warning("定时检查: 登录失败 - %s", e)
            await _notify_admin(f"⚠️ 登录教务系统失败: {e}\n请检查 bot/.env 中的账号密码")
            return
        except Exception as e:
            logger.error("定时检查失败: %s", e)
            return

        if not grades:
            return

        new_grades = await detector.detect_new(db, grades)
        if new_grades:
            from .notifier import format_new_grades
            await _notify_admin(format_new_grades(new_grades))
    finally:
        await db.close()


async def _notify_admin(message: str):
    """向管理员 QQ 发送通知"""
    from nonebot import get_bot
    try:
        bot = get_bot()
        qq_id = cfg.get_qq_id()
        if qq_id:
            await bot.send_private_msg(user_id=int(qq_id), message=message)
        else:
            logger.warning("未配置 QQ_ID，无法发送通知")
    except Exception as e:
        logger.error("发送通知失败: %s", e)


def start_scheduler():
    global scheduler, _next_run_time
    interval = cfg.get_check_interval()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _scheduled_check,
        trigger=IntervalTrigger(minutes=interval),
        id="grade_check",
        name="成绩定时检查",
        replace_existing=True,
    )
    scheduler.start()
    _next_run_time = datetime.now() + timedelta(minutes=interval)
    logger.info("定时任务已启动，间隔 %d 分钟", interval)


def get_next_run_time() -> str:
    job = scheduler.get_job("grade_check") if scheduler else None
    if job and job.next_run_time:
        return job.next_run_time.strftime("%Y-%m-%d %H:%M:%S")
    return ""


def shutdown_scheduler():
    global scheduler
    if scheduler:
        scheduler.shutdown(wait=False)
        scheduler = None
