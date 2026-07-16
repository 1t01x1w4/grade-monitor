import os
from typing import Optional


def get_credentials() -> tuple[Optional[str], Optional[str]]:
    """返回 (username, password)，未配置时返回 (None, None)"""
    username = os.getenv("JW_USERNAME", "").strip()
    password = os.getenv("JW_PASSWORD", "").strip()
    u = username if username and username != "your_student_id" else None
    p = password if password and password != "your_password" else None
    return u, p


def has_credentials() -> bool:
    u, p = get_credentials()
    return u is not None and p is not None


def get_tgt() -> Optional[str]:
    """从环境变量获取 TGT（可选的后备认证方式）"""
    tgt = os.getenv("JW_TGT", "").strip()
    return tgt if tgt else None


def get_qq_id() -> str:
    return os.getenv("QQ_ID", "").strip()


def get_check_interval() -> int:
    return int(os.getenv("CHECK_INTERVAL_MINUTES", "30"))


def get_base_url() -> str:
    return os.getenv("JW_BASE_URL", "https://jwglxt.gpnu.edu.cn").rstrip("/")


def get_auth_url() -> str:
    return os.getenv("JW_AUTH_URL", "https://webauth.gpnu.edu.cn").rstrip("/")
