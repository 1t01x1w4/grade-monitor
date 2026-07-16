import json
import logging
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def parse_grade_response(body: str) -> list[dict]:
    """
    解析教务系统返回的成绩数据。
    支持 HTML 表格和 JSON 两种格式。
    返回: [{course_name, course_id, score, credit, gpa, semester, exam_type}, ...]
    """
    if not body or not body.strip():
        return []

    # 尝试 JSON 格式
    if body.strip().startswith("{"):
        return _parse_json(body)

    # 尝试 HTML 格式
    if "<table" in body.lower() or "<tr" in body.lower():
        return _parse_html_table(body)

    # 尝试直接作为纯 JSON 数组
    try:
        data = json.loads(body)
        if isinstance(data, list):
            return _parse_json_list(data)
    except json.JSONDecodeError:
        pass

    logger.warning("无法识别的响应格式，前200字符: %s", body[:200])
    return []


def _parse_json(body: str) -> list[dict]:
    """解析 JSON 格式响应"""
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        logger.error("JSON 解析失败")
        return []

    # 正方教务系统常见 JSON 结构
    # 可能是 {"items": [...]} 或 {"data": [...]} 或直接 [...]
    items = None
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = (
            data.get("items")
            or data.get("data")
            or data.get("list")
            or data.get("rows")
            or []
        )

    if not isinstance(items, list):
        return []

    return _parse_json_list(items)


def _parse_json_list(items: list) -> list[dict]:
    """从 JSON 对象列表中提取成绩字段"""
    grades = []
    for item in items:
        if not isinstance(item, dict):
            continue

        # Preserve original API fields + normalize common names
        grade = dict(item)
        grade.update({
            "course_name": _find_field(item, ["kcmc", "coursename", "course_name", "name", "课程名称", "课程"]),
            "course_id": _find_field(item, ["kch", "courseid", "course_id", "id", "课程编号", "编号"]),
            "score": _find_field(item, ["cj", "score", "grade", "chengji", "成绩", "总成绩"]),
            "credit": _to_float(_find_field(item, ["xf", "credit", "xuefen", "credits", "学分"])),
            "gpa": _to_float(_find_field(item, ["jd", "gpa", "jidian", "绩点"])),
            "semester": _find_field(item, ["xq", "xqm", "semester", "term", "学期"]),
            "exam_type": _find_field(item, ["ksxz", "exam_type", "examtype", "考试性质", "考试类型"]),
        })
        if grade["course_name"]:
            grades.append(grade)

    return grades


def _parse_html_table(body: str) -> list[dict]:
    """解析 HTML 表格格式成绩数据"""
    soup = BeautifulSoup(body, "lxml")
    grades = []

    # 查找成绩表格
    table = soup.find("table")
    if not table:
        logger.warning("HTML 中未找到 table 元素")
        return []

    rows = table.find_all("tr")
    if len(rows) < 2:
        return []

    # 从表头推断列索引
    header_row = rows[0]
    headers = [th.get_text(strip=True) for th in header_row.find_all(["th", "td"])]

    col_map = _map_columns(headers)

    # 解析数据行
    for row in rows[1:]:
        cells = row.find_all(["td", "th"])
        if len(cells) < len(headers):
            continue

        texts = [cell.get_text(strip=True) for cell in cells]

        grade = {
            "course_name": _cell(texts, col_map.get("course_name")),
            "course_id": _cell(texts, col_map.get("course_id")),
            "score": _cell(texts, col_map.get("score")),
            "credit": _to_float(_cell(texts, col_map.get("credit"))),
            "gpa": _to_float(_cell(texts, col_map.get("gpa"))),
            "semester": _cell(texts, col_map.get("semester")),
            "exam_type": _cell(texts, col_map.get("exam_type")),
        }
        if grade["course_name"]:
            grades.append(grade)

    return grades


def _map_columns(headers: list[str]) -> dict:
    """根据表头文本映射到字段名"""
    mapping = {}
    keywords = {
        "course_name": ["课程名称", "课程", "名称", "kcmc"],
        "course_id": ["课程编号", "编号", "kch"],
        "score": ["成绩", "总成绩", "分数", "cj"],
        "credit": ["学分", "xf"],
        "gpa": ["绩点", "jd", "gpa"],
        "semester": ["学期", "xq", "term"],
        "exam_type": ["考试性质", "考试类型", "ksxz", "备注"],
    }
    for i, h in enumerate(headers):
        h_lower = h.lower()
        for field, keys in keywords.items():
            if any(k in h_lower for k in keys):
                mapping[field] = i
                break
    return mapping


def _find_field(obj: dict, keys: list[str]) -> str:
    """从字典中按优先级查找字段值"""
    for k in keys:
        val = obj.get(k)
        if val is not None and str(val).strip():
            return str(val).strip()
    return ""


def _cell(texts: list[str], idx: int | None) -> str:
    if idx is not None and idx < len(texts):
        return texts[idx].strip()
    return ""


def _to_float(val: str) -> float | None:
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
