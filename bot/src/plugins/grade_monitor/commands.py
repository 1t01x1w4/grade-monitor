import logging
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent

from . import scraper, detector, notifier, storage, config_manager as cfg
from .scheduler import get_next_run_time, scheduler

logger = logging.getLogger(__name__)

cmd_check = on_command("查成绩", priority=5)
cmd_status = on_command("成绩状态", priority=5)
cmd_monitor = on_command("成绩监控", priority=5)
cmd_help = on_command("帮助", priority=5)


@cmd_check.handle()
async def handle_check(bot: Bot, event: MessageEvent):
    if not cfg.has_credentials():
        await cmd_check.finish(
            "❌ 未配置账号密码，请在 bot/.env 中设置 JW_USERNAME 和 JW_PASSWORD"
        )

    await cmd_check.send("⏳ 正在登录教务系统并查询成绩...")
    await _do_check(bot, event)


@cmd_status.handle()
async def handle_status(bot: Bot, event: MessageEvent):
    db = await storage.get_db()
    try:
        grades = await storage.get_all_grades(db)
        msg = notifier.format_current_grades(grades)
        await cmd_status.finish(msg)
    finally:
        await db.close()


@cmd_monitor.handle()
async def handle_monitor(bot: Bot, event: MessageEvent):
    db = await storage.get_db()
    try:
        grade_count = await storage.get_grade_count(db)

        if cfg.has_credentials():
            login_status = "✅ 已配置"
        else:
            login_status = "❌ 未配置账号密码"

        next_time = get_next_run_time() or "无定时任务"
        running = scheduler is not None and scheduler.running

        msg = notifier.format_status(running, next_time, login_status, grade_count)
        await cmd_monitor.finish(msg)
    finally:
        await db.close()


@cmd_help.handle()
async def handle_help(bot: Bot, event: MessageEvent):
    await cmd_help.finish(notifier.HELP_TEXT)


async def _do_check(bot: Bot, event: MessageEvent):
    """执行成绩检查并发送通知"""
    db = await storage.get_db()
    try:
        try:
            grades = await scraper.fetch_grades()
        except scraper.LoginError as e:
            await cmd_check.send(f"❌ 登录失败: {e}")
            return
        except scraper.CookieExpiredError:
            await cmd_check.send("❌ 会话已过期，下次检查会自动重新登录")
            return
        except Exception as e:
            logger.error("获取成绩失败: %s", e)
            await cmd_check.send(f"❌ 获取成绩失败: {e}")
            return

        if not grades:
            await cmd_check.send("未查询到任何成绩记录（可能页面为空或解析失败）")
            return

        new_grades = await detector.detect_new(db, grades)
        if new_grades:
            await cmd_check.send(notifier.format_new_grades(new_grades))
        else:
            await cmd_check.send(f"✅ 成绩无变化，当前共 {len(grades)} 门成绩")
    finally:
        await db.close()
