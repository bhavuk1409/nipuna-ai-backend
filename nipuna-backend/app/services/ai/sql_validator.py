import re

BLOCKED_KEYWORDS = [
    r"\bDROP\b",
    r"\bDELETE\b",
    r"\bTRUNCATE\b",
    r"\bALTER\b",
    r"\bCREATE\b",
    r"\bGRANT\b",
    r"\bREVOKE\b",
    r"\bEXEC\b",
    r"\bEXECUTE\b",
    r"\bxp_\b",
    r"\bsp_\b",
]


def validate_sql(sql: str) -> tuple[bool, str]:
    sql_upper = sql.upper()
    for pattern in BLOCKED_KEYWORDS:
        if re.search(pattern, sql_upper):
            cleaned = pattern.strip("\\b")
            return False, f"Blocked keyword found: {cleaned}"
    return True, ""
