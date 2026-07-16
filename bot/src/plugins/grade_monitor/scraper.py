"""
教务系统成绩抓取模块。

认证流程（CAS SSO，基于 Burp 抓包确认）:
1. RSA 加密密码 → POST /lyuapServer/v1/tickets → 获取 TGT
2. POST /lyuapServer/v1/tickets/<TGT> → 获取 ST (Service Ticket)
3. GET jwglxt/sso/lyiotlogin?ticket=ST-xxx → 跟随重定向 → 获取 JSESSIONID
4. POST cjcx_cxXsgrcj.html → 获取成绩 JSON

支持两种认证方式:
- 用户名密码（JW_USERNAME/JW_PASSWORD），自动 RSA 加密
- TGT 票据（JW_TGT），长期有效，跳过密码加密步骤
"""

import logging
import uuid
from urllib.parse import quote

import httpx
from . import config_manager as cfg

logger = logging.getLogger(__name__)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36 Edg/150.0.0.0")

TIMEOUT = 15
MAX_RETRIES = 3

CAS_BASE = "https://cas.gpnu.edu.cn/lyuapServer"
CAS_TICKETS_URL = f"{CAS_BASE}/v1/tickets"

# RSA 公钥参数，从 CAS 登录页 webpack JS 中提取
_RSA_MODULUS = int(
    "00b5eeb166e069920e80bebd1fea4829d3d1f3216f2aabe79b6c47a3c18dcee5"
    "fd22c2e7ac519cab59198ece036dcf289ea8201e2a0b9ded307f8fb704136eaeb"
    "670286f5ad44e691005ba9ea5af04ada5367cd724b5a26fdb5120cc95b6431604"
    "bd219c6b7d83a6f8f24b43918ea988a76f93c333aa5a20991493d4eb1117e7b1",
    16,
)
_RSA_EXPONENT = 0x010001  # 65537
GRADE_PAGE_PATH = "/jwglxt/cjcx/cjcx_cxDgXscj.html"
GRADE_QUERY_PATH = "/jwglxt/cjcx/cjcx_cxXsgrcj.html"

_session: httpx.AsyncClient | None = None
_tgt_cache: str | None = None


def _build_client() -> httpx.AsyncClient:
    base = cfg.get_base_url()
    return httpx.AsyncClient(
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
        timeout=TIMEOUT,
        follow_redirects=False,
        verify=False,
    )


def _build_json_client() -> httpx.AsyncClient:
    base = cfg.get_base_url()
    return httpx.AsyncClient(
        headers={
            "User-Agent": UA,
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Origin": base,
            "Referer": f"{base}{GRADE_PAGE_PATH}?gnmkdm=N305005&layout=default",
        },
        timeout=TIMEOUT,
        follow_redirects=False,
        verify=False,
    )


# ─── TGT 管理 ───────────────────────────────────────────

async def _get_tgt(client: httpx.AsyncClient | None = None) -> str:
    """获取 TGT。优先使用缓存的 TGT，否则尝试用户名密码登录获取。"""
    global _tgt_cache
    if _tgt_cache:
        return _tgt_cache

    tgt = cfg.get_tgt()
    if tgt:
        _tgt_cache = tgt
        return tgt

    # 尝试用户名密码登录获取 TGT
    username, password = cfg.get_credentials()
    if username and password:
        tgt = await _login_with_password(username, password, client=client)
        if tgt:
            _tgt_cache = tgt
            return tgt

    raise LoginError("未配置 TGT (JW_TGT) 或账号密码 (JW_USERNAME/JW_PASSWORD)，无法登录")


def _get_chunk_size() -> int:
    """计算 RSA 加密块大小，与 JS 的 2 * biHighIndex(modulus) 一致。"""
    n_bits = _RSA_MODULUS.bit_length()
    n_digits = (n_bits + 15) // 16
    bi_high_index = n_digits - 1
    return 2 * bi_high_index


def _rsa_encrypt(plaintext: str) -> str:
    """
    使用与 CAS 登录页 JS 完全一致的 RSA 加密方式。

    JS 实现（util_rsa.c / 函数 W）：
    - 零填充（trailing zeros），非 PKCS1v15
    - Little-endian 字节序转整数
    - 确定性加密（相同输入 → 相同输出）
    """
    data = plaintext.encode("utf-8")
    chunk_size = _get_chunk_size()

    # 零填充到 chunkSize（与 JS for(;a.length%chunkSize;) a[o++]=0 一致）
    if len(data) < chunk_size:
        data = data + b'\x00' * (chunk_size - len(data))

    # Little-endian 字节序转整数（匹配 JS 的 digit 构造方式：
    #   c.digits[r] = a[l++] + (a[l++] << 8)）
    m = int.from_bytes(data, 'little')

    # 原始 RSA: c = m^e mod n
    c = pow(m, _RSA_EXPONENT, _RSA_MODULUS)

    # 确保 256 hex chars（1024-bit），前导零补齐（匹配 JS BigInt hex 输出）
    return hex(c)[2:].zfill(256)


def _generate_login_token() -> str:
    """生成 Loginusertoken = RSA_encrypt('lyasp' + 当前毫秒时间戳)"""
    import time
    plaintext = f"lyasp{int(time.time() * 1000)}"
    return _rsa_encrypt(plaintext)


def _random_id() -> str:
    """生成 32 位 hex 随机 ID（UUID 去连字符），用于登录请求的 id 参数。"""
    return uuid.uuid4().hex


async def _get_captcha(client: httpx.AsyncClient | None = None) -> tuple[str | None, str | None]:
    """
    获取 CAS 算术验证码，返回 (captcha_uid, captcha_answer)。

    通过 ddddocr 自动识别算术验证码图片。
    验证码来自 GET /lyuapServer/kaptcha，返回 {uid, content(base64图片), timeout}。
    答案为 0-82 之间的整数。

    如果传入 client，则复用其 cookie 会话。
    """
    import base64

    close_client = False
    if client is None:
        client = httpx.AsyncClient(
            timeout=TIMEOUT, follow_redirects=False, verify=False
        )
        close_client = True

    try:
        resp = await client.get(
            f"{CAS_BASE}/kaptcha",
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/plain, */*",
            },
        )
        if resp.status_code != 200:
            logger.error("获取验证码失败: HTTP %d", resp.status_code)
            return None, None

        captcha = resp.json()
        uid = captcha.get("uid")
        content = captcha.get("content", "")

        if not uid or not content:
            logger.error("验证码响应缺少 uid 或 content")
            return None, None

        # 解码 base64 图片
        if "," in content:
            img_data = base64.b64decode(content.split(",", 1)[1])
        else:
            img_data = base64.b64decode(content)

        # OCR 识别
        answer = _solve_arithmetic_captcha(img_data)
        if answer is not None:
            logger.info("OCR 识别验证码成功: uid=%s answer=%s", uid, answer)
            return uid, str(answer)

    except Exception as e:
        logger.warning("OCR 验证码识别失败: %s", e)
    finally:
        if close_client:
            await client.aclose()

    return None, None


_ddddocr_instance = None


def _get_ddddocr():
    """返回 ddddocr 单例，延迟加载以避免启动时加载模型。"""
    global _ddddocr_instance
    if _ddddocr_instance is None:
        import ddddocr
        _ddddocr_instance = ddddocr.DdddOcr(show_ad=False)
    return _ddddocr_instance


def _solve_arithmetic_captcha(img_data: bytes) -> int | None:
    """
    使用 ddddocr 识别算术验证码图片，计算答案。

    验证码格式: "A+B=", "A-B=", "A*B=" 等简单算术表达式，答案范围 0-82。
    """
    import re

    try:
        import ddddocr
    except ImportError:
        logger.warning("ddddocr 未安装，无法自动识别验证码")
        return None

    try:
        ocr = _get_ddddocr()
        text = ocr.classification(img_data)
        if not text:
            return None

        text = text.strip()
        logger.debug("OCR 原始结果: %s", text)

        # 纠正常见 OCR 错误: o/O → 0, l/I → 1, S → 5, Z → 2, B → 8
        corrections = str.maketrans({
            'o': '0', 'O': '0',
            'l': '1', 'I': '1',
            'S': '5', 's': '5',
            'Z': '2', 'z': '2',
            'B': '8',
        })
        text_corrected = text.translate(corrections)
        if text_corrected != text:
            logger.debug("OCR 纠错后: %s", text_corrected)
            text = text_corrected

        # 解析表达式: 数字 运算符 数字 = (可能带 ? 或空格)
        # 支持: 5+2=, 6*3=, 12-7=?, 8+4
        match = re.match(r'(\d+)\s*([+\-*/])\s*(\d+)', text)
        if not match:
            logger.warning("无法解析验证码表达式: %s", text)
            return None

        a, op, b = int(match.group(1)), match.group(2), int(match.group(3))

        if op == '+':
            result = a + b
        elif op == '-':
            result = a - b
        elif op == '*':
            result = a * b
        elif op == '/':
            result = a // b if b != 0 else None
        else:
            return None

        if result is not None and 0 <= result <= 82:
            return result

        logger.warning("验证码答案超出范围: %d", result)
        return None

    except Exception as e:
        logger.warning("验证码识别异常: %s", e)
        return None


async def _login_with_password(
    username: str, password: str, client: httpx.AsyncClient | None = None
) -> str | None:
    """
    使用用户名密码向 CAS 登录获取 TGT。

    登录 API: POST /lyuapServer/v1/tickets
    参数: username, password(RSA加密), service, loginType, id, code
    返回 JSON: {"tgt": "TGT-xxx", "ticket": "ST-xxx"}

    如果提供 client，则复用其会话（CAS cookies 会被保留给调用方）。
    """
    encrypted_pwd = _rsa_encrypt(password)
    login_token = _generate_login_token()
    logger.info("密码已 RSA 加密 (%d hex chars)", len(encrypted_pwd))

    # 教务系统的 service URL
    service = f"{cfg.get_base_url()}/sso/lyiotlogin"

    headers = {
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "Logintoken": "loginToken",
        "Loginusertoken": login_token,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://cas.gpnu.edu.cn",
        "Referer": f"{CAS_BASE}/login?service={quote(service, safe='')}",
    }

    _close = False
    if client is None:
        client = httpx.AsyncClient(
            timeout=TIMEOUT,
            follow_redirects=False,
            verify=False,
            headers={
                "User-Agent": UA,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
        )
        _close = True

    try:
        # Step 0: 请求登录页建立会话（获取 CAS cookies）
        login_page_url = f"{CAS_BASE}/login?service={quote(service, safe='')}"
        try:
            page_resp = await client.get(login_page_url)
            logger.debug("获取 CAS 登录页: HTTP %d", page_resp.status_code)
        except Exception as e:
            logger.warning("获取 CAS 登录页失败: %s，继续尝试登录", e)

        # Step 1: 获取验证码（复用同一 client 的 cookie 会话）
        captcha_uid, captcha_answer = await _get_captcha(client=client)
        if not captcha_uid or not captcha_answer:
            logger.error("无法获取验证码")
            return None

        data = {
            "username": username,
            "password": encrypted_pwd,
            "service": service,
            "loginType": "",
            "id": captcha_uid,
            "code": captcha_answer,
        }

        resp = await client.post(
            CAS_TICKETS_URL,
            data=data,
            headers=headers,
        )

        if resp.status_code != 200:
            logger.error("CAS 登录失败: HTTP %d, body: %s", resp.status_code, resp.text[:500])
            return None

        try:
            result = resp.json()
        except ValueError:
            logger.error("CAS login response not JSON: %s", resp.text[:1000])
            return None

        tgt = result.get("tgt")
        if tgt:
            logger.info("密码登录成功，获取 TGT: %s", tgt)
            return tgt

        # Check for CODEFALSE - captcha was wrong
        resp_data = result.get("data", {})
        if resp_data.get("code") == "CODEFALSE":
            logger.error("CAS 验证码错误 (CODEFALSE)")
            return None

        # Check error info
        meta = result.get("meta", {})
        msg = meta.get("message", str(result))
        logger.error("CAS 登录失败: %s", msg)
        return None

    finally:
        if _close:
            await client.aclose()


def invalidate_tgt():
    """使缓存的 TGT 失效（用于重新登录）"""
    global _tgt_cache
    _tgt_cache = None


# ─── CAS 认证 ───────────────────────────────────────────

async def _get_st(client: httpx.AsyncClient, tgt: str, service: str) -> str:
    """使用 TGT 向 CAS 申请 Service Ticket"""
    resp = await client.post(
        f"{CAS_TICKETS_URL}/{tgt}",
        data={"service": service, "loginToken": "loginToken"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp.raise_for_status()
    st = resp.text.strip()
    if not st or not st.startswith("ST-"):
        raise LoginError(f"获取 Service Ticket 失败: {st}")
    logger.info("获取 ST 成功: %s", st)
    return st


async def _follow_redirects(
    client: httpx.AsyncClient, start_url: str, max_steps: int = 10
) -> httpx.Response:
    """跟随 302 重定向链，返回最终响应。相对 URL 基于当前请求的域名解析。"""
    from urllib.parse import urljoin
    url = start_url
    for _ in range(max_steps):
        resp = await client.get(url)
        if resp.status_code in (302, 301):
            location = resp.headers.get("location", "")
            if not location:
                return resp
            # 使用 urljoin 正确解析相对 URL
            url = location if location.startswith("http") else urljoin(url, location)
            continue
        return resp
    return resp


# ─── 主登录流程 ─────────────────────────────────────────

_WENGINE_AUTH = "https://webauth.gpnu.edu.cn/wengine-auth"
_WENGINE_CALLBACK = f"{_WENGINE_AUTH}/login?cas_login=true"


async def login() -> httpx.AsyncClient:
    """
    执行完整 SSO 登录，返回已认证的 httpx 客户端（带 JSESSIONID Cookie）。

    流程:
    1. CAS 密码登录 → 获取 TGT + ST_jwglxt（直接返回的 ST）
    2. 用 TGT 向 CAS 申请 ST_webauth（webauth 回调用）
    3. 访问 webauth 登录页建立会话上下文
    4. webauth CAS 回调（ST_webauth）→ 跟随重定向链
    5. 重定向链到达 CAS 时，改用 ST_jwglxt 直接访问教务系统
    6. 跟随最终重定向 → 获取 JSESSIONID
    """
    global _session

    client = _build_client()
    tgt = None

    try:
        # ── Step 1: CAS 密码登录，获取 TGT + ST ──
        username, password = cfg.get_credentials()
        if not username or not password:
            raise LoginError("未配置账号密码")

        encrypted_pwd = _rsa_encrypt(password)
        login_token = _generate_login_token()
        logger.info("密码已 RSA 加密 (%d hex chars)", len(encrypted_pwd))

        service_jwglxt = f"{cfg.get_base_url()}/sso/lyiotlogin"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "Logintoken": "loginToken",
            "Loginusertoken": login_token,
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://cas.gpnu.edu.cn",
            "Referer": f"{CAS_BASE}/login?service={quote(service_jwglxt, safe='')}",
        }

        # 获取 CAS 登录页建立会话
        login_page_url = f"{CAS_BASE}/login?service={quote(service_jwglxt, safe='')}"
        try:
            await client.get(login_page_url)
        except Exception as e:
            logger.warning("获取 CAS 登录页失败: %s", e)

        # 获取验证码
        captcha_uid, captcha_answer = await _get_captcha(client=client)
        if not captcha_uid or not captcha_answer:
            raise LoginError("无法获取验证码")

        # 登录 POST
        resp = await client.post(
            CAS_TICKETS_URL,
            data={
                "username": username,
                "password": encrypted_pwd,
                "service": service_jwglxt,
                "loginType": "",
                "id": captcha_uid,
                "code": captcha_answer,
            },
            headers=headers,
        )
        if resp.status_code != 200:
            raise LoginError(f"CAS 登录失败: HTTP {resp.status_code}")

        try:
            result = resp.json()
        except ValueError:
            raise LoginError(f"CAS 登录响应非 JSON: {resp.text[:500]}")

        tgt = result.get("tgt")
        st_jwglxt = result.get("ticket")
        if not tgt or not st_jwglxt:
            # 检查错误
            resp_data = result.get("data", {})
            if resp_data.get("code") == "CODEFALSE":
                raise LoginError("CAS 验证码错误 (CODEFALSE)")
            msg = result.get("meta", {}).get("message", str(result))
            raise LoginError(f"CAS 登录失败: {msg}")

        logger.info("CAS 登录成功，TGT: %s", tgt)
        _tgt_cache = tgt

        # ── Step 2: 用 TGT 获取 ST_webauth ──
        service_webauth = f"{_WENGINE_AUTH}/login?cas_login=true"
        st_resp = await client.post(
            f"{CAS_TICKETS_URL}/{tgt}",
            data={"service": service_webauth, "loginToken": "loginToken"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        st_resp.raise_for_status()
        st_webauth = st_resp.text.strip()
        if not st_webauth or not st_webauth.startswith("ST-"):
            raise LoginError(f"获取 ST_webauth 失败: {st_webauth}")
        logger.info("ST_webauth: %s, ST_jwglxt: %s", st_webauth[:30], st_jwglxt[:30])

        # ── Step 3: 访问 webauth 登录页建立会话上下文 ──
        from_url = service_jwglxt
        await client.get(
            f"{_WENGINE_AUTH}/login?id=683&path=/&from={from_url}"
        )

        # ── Step 4-6: webauth CAS 回调 → 跟随重定向 → 拦截 CAS → ST_jwglxt ──
        url = f"{service_webauth}&ticket={st_webauth}"
        from urllib.parse import urljoin

        for _ in range(15):
            resp = await client.get(url)
            if resp.status_code in (302, 301):
                location = resp.headers.get("location", "")
                if not location:
                    break
                # 当重定向到 CAS 时，用 ST_jwglxt 直接完成教务系统认证
                if "cas.gpnu.edu.cn/lyuapServer/login" in location:
                    logger.info("拦截 CAS 重定向，使用 ST_jwglxt")
                    url = f"{service_jwglxt}?ticket={st_jwglxt}"
                    continue
                url = location if location.startswith("http") else urljoin(url, location)
                continue
            break

        # ── 检查结果 ──
        jsessionid = None
        for cookie in client.cookies.jar:
            if cookie.name == "JSESSIONID" and "jwglxt" in cookie.domain and cookie.path == "/jwglxt":
                jsessionid = cookie.value
                break
        if jsessionid:
            logger.info("登录成功，获得 JSESSIONID (path=/jwglxt)")
        else:
            raise LoginError("未获取到 JSESSIONID")

        # 创建新的 JSON 客户端，只复制必要的 cookies（避免重名冲突）
        json_client = _build_json_client()
        seen = set()
        for cookie in client.cookies.jar:
            key = (cookie.name, cookie.domain, cookie.path)
            if key not in seen:
                seen.add(key)
                json_client.cookies.set(
                    cookie.name, cookie.value, domain=cookie.domain, path=cookie.path
                )
        _session = json_client
        return json_client

    except LoginError:
        await client.aclose()
        raise
    except Exception as e:
        await client.aclose()
        raise LoginError(f"登录流程异常: {e}") from e


# ─── 成绩获取 ───────────────────────────────────────────

async def fetch_grades() -> list[dict]:
    """获取成绩数据，自动处理登录和会话管理。"""
    global _session
    from . import parser

    if _session is None:
        _session = await login()

    client = _session
    base = cfg.get_base_url()
    grade_url = f"{base}{GRADE_QUERY_PATH}?doType=query&gnmkdm=N305005"

    for attempt in range(MAX_RETRIES):
        try:
            resp = await client.post(
                grade_url,
                data={
                    "xnm": "",
                    "xqm": "",
                    "sfzgcj": "",
                    "kcbj": "",
                    "pkey": "",
                    "_search": "false",
                    "nd": _timestamp(),
                    "queryModel.showCount": "100",
                    "queryModel.currentPage": "1",
                    "queryModel.sortName": "",
                    "queryModel.sortOrder": "asc",
                    "time": "0",
                },
            )

            # 检查是否被重定向到 CAS（会话过期）
            if resp.status_code in (302, 301):
                location = resp.headers.get("location", "")
                if "cas.gpnu.edu.cn" in location or "wengine-auth" in location.lower():
                    logger.info("会话已过期，重新登录...")
                    invalidate_tgt()
                    await client.aclose()
                    _session = await login()
                    client = _session
                    continue

            resp.raise_for_status()
            body = resp.text
            break

        except httpx.TimeoutException:
            if attempt == MAX_RETRIES - 1:
                raise
            logger.warning("请求超时，重试 %d/%d", attempt + 1, MAX_RETRIES)
        except httpx.HTTPStatusError:
            if attempt == MAX_RETRIES - 1:
                raise
            logger.warning("HTTP 错误，重试 %d/%d", attempt + 1, MAX_RETRIES)

    return parser.parse_grade_response(body)


def _timestamp() -> str:
    import time
    return str(int(time.time() * 1000))


# ─── 异常类 ─────────────────────────────────────────────

class LoginError(Exception):
    """登录失败"""
    pass


class CookieExpiredError(Exception):
    """会话过期（保留兼容）"""
    pass
