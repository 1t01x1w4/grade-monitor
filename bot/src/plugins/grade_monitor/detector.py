import logging
import aiosqlite
from . import storage

logger = logging.getLogger(__name__)

# 标记是否已完成首次数据加载
_first_load_done = False


async def detect_new(db: aiosqlite.Connection, grades: list[dict]) -> list[dict]:
    """
    检测新成绩。
    首次加载时只存储不通知，之后只返回新增的成绩。
    返回: 新增的成绩列表
    """
    global _first_load_done

    new_grades = []
    for grade in grades:
        inserted = await storage.insert_grade(db, grade)
        if inserted:
            new_grades.append(grade)

    if not _first_load_done:
        _first_load_done = True
        logger.info("首次加载完成，已存储 %d 条成绩，跳过通知", len(grades))
        return []

    if new_grades:
        logger.info("检测到 %d 门新成绩", len(new_grades))

    return new_grades


def reset_first_load():
    """重置首次加载标记（用于调试）"""
    global _first_load_done
    _first_load_done = False
