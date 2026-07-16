def format_new_grades(grades: list[dict]) -> str:
    """格式化新成绩通知消息"""
    if not grades:
        return ""

    lines = [f"出新成绩了！共 {len(grades)} 门：\n"]
    for g in grades:
        name = g.get("course_name", "未知课程")
        score = g.get("score", "—")
        credit = g.get("credit")
        gpa = g.get("gpa")
        semester = g.get("semester", "")

        parts = [f"📖 {name}"]
        if semester:
            parts.append(f"学期: {semester}")
        parts.append(f"成绩: {score}")
        if credit is not None:
            parts.append(f"学分: {credit}")
        if gpa is not None:
            parts.append(f"绩点: {gpa}")

        lines.append(" | ".join(parts))

    return "\n".join(lines)


def format_current_grades(grades: list[dict]) -> str:
    """格式化已有成绩概览"""
    if not grades:
        return "暂无成绩记录"

    lines = [f"📋 当前已有 {len(grades)} 门成绩：\n"]
    for g in grades:
        name = g.get("course_name", "未知")
        score = g.get("score", "—")
        gpa = g.get("gpa", "—")
        lines.append(f"  {name} | 成绩: {score} | 绩点: {gpa}")

    return "\n".join(lines)


def format_status(running: bool, next_check: str, login_ok: str, grade_count: int) -> str:
    """格式化监控状态消息"""
    status_icon = "🟢" if running else "🔴"
    return (
        f"{status_icon} 成绩监控状态\n"
        f"运行状态: {'运行中' if running else '已停止'}\n"
        f"登录状态: {login_ok}\n"
        f"已记录成绩: {grade_count} 门\n"
        f"下次检查: {next_check}"
    )


HELP_TEXT = (
    "📋 成绩监控机器人命令：\n"
    "/查成绩 — 手动触发成绩检查\n"
    "/成绩状态 — 查看已有成绩\n"
    "/成绩监控 — 查看监控运行状态\n"
    "/帮助 — 显示本帮助"
)
