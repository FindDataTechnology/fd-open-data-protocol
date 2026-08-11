"""Industry classification constants and helpers.

This module defines canonical industry classification systems and provides
helper functions for parsing industry codes.
"""

from typing import Optional
import re


# Canonical industry classification systems
CLASSIFICATION_SYSTEMS = {
    "shenwan": {
        "name": "申万行业分类",
        "name_en": "Shenwan Industry Classification",
        "levels": 3,
        "prefix": "shenwan_",
        "code_pattern": r"^shenwan_(\d)_(\d{2,6})$",
        "description": "Chinese industry classification by Shenwan Research"
    },
    "gics": {
        "name": "全球行业分类标准",
        "name_en": "Global Industry Classification Standard",
        "levels": 4,
        "prefix": "gics_",
        "code_pattern": r"^gics_(\d{2,8})$",
        "description": "Global industry classification by MSCI and S&P"
    },
}


def parse_industry_code(code: str) -> Optional[dict]:
    """Parse an industry code and extract classification system and level.

    Args:
        code: Industry code (e.g., "shenwan_1_01", "gics_50")

    Returns:
        Dict with keys: system, level, numeric_code, or None if invalid

    Examples:
        >>> parse_industry_code("shenwan_1_01")
        {'system': 'shenwan', 'level': 1, 'numeric_code': '01'}
        >>> parse_industry_code("gics_50")
        {'system': 'gics', 'level': None, 'numeric_code': '50'}
    """
    for system, config in CLASSIFICATION_SYSTEMS.items():
        pattern = re.compile(config["code_pattern"])
        match = pattern.match(code)
        if match:
            groups = match.groups()
            if system == "shenwan":
                # shenwan_1_01 -> level=1, numeric_code=01
                return {
                    "system": system,
                    "level": int(groups[0]),
                    "numeric_code": groups[1]
                }
            elif system == "gics":
                # gics_50 -> level=None (determined by code length), numeric_code=50
                numeric = groups[0]
                # GICS levels: 2-digit=sector, 4-digit=industry group, 6-digit=industry, 8-digit=sub-industry
                if len(numeric) == 2:
                    level = 1
                elif len(numeric) == 4:
                    level = 2
                elif len(numeric) == 6:
                    level = 3
                elif len(numeric) == 8:
                    level = 4
                else:
                    level = None
                return {
                    "system": system,
                    "level": level,
                    "numeric_code": numeric
                }
    return None


def validate_industry_code(code: str) -> bool:
    """Validate an industry code against canonical patterns.

    Args:
        code: Industry code to validate

    Returns:
        True if valid, False otherwise

    Examples:
        >>> validate_industry_code("shenwan_1_01")
        True
        >>> validate_industry_code("invalid_code")
        False
    """
    return parse_industry_code(code) is not None


def get_classification_system(code: str) -> Optional[str]:
    """Get the classification system name from an industry code.

    Args:
        code: Industry code

    Returns:
        System name (e.g., "shenwan", "gics") or None if invalid

    Examples:
        >>> get_classification_system("shenwan_1_01")
        'shenwan'
    """
    result = parse_industry_code(code)
    return result["system"] if result else None


def get_industry_level(code: str) -> Optional[int]:
    """Get the hierarchy level from an industry code.

    Args:
        code: Industry code

    Returns:
        Level (1, 2, 3, or 4) or None if invalid

    Examples:
        >>> get_industry_level("shenwan_1_01")
        1
        >>> get_industry_level("gics_50")
        1
    """
    result = parse_industry_code(code)
    return result["level"] if result else None


def format_industry_code(system: str, level: Optional[int], numeric_code: str) -> str:
    """Format an industry code from components.

    Args:
        system: Classification system (e.g., "shenwan", "gics")
        level: Hierarchy level (for shenwan only)
        numeric_code: Numeric code portion

    Returns:
        Formatted industry code

    Examples:
        >>> format_industry_code("shenwan", 1, "01")
        'shenwan_1_01'
        >>> format_industry_code("gics", None, "50")
        'gics_50'
    """
    if system == "shenwan":
        if level is None:
            raise ValueError("Shenwan classification requires level parameter")
        return f"shenwan_{level}_{numeric_code}"
    elif system == "gics":
        return f"gics_{numeric_code}"
    else:
        raise ValueError(f"Unknown classification system: {system}")


# Common industry codes for reference
COMMON_INDUSTRIES = {
    "shenwan": {
        "1": {
            "01": "农林牧渔",
            "02": "采掘",
            "03": "化工",
            "04": "钢铁",
            "05": "有色金属",
            "06": "建筑材料",
            "07": "建筑装饰",
            "08": "电气设备",
            "09": "国防军工",
            "10": "汽车",
            "11": "机械设备",
            "12": "休闲服务",
            "13": "家用电器",
            "14": "纺织服装",
            "15": "轻工制造",
            "16": "商业贸易",
            "17": "食品饮料",
            "18": "医药生物",
            "19": "公用事业",
            "20": "交通运输",
            "21": "房地产",
            "22": "电子",
            "23": "通信",
            "24": "计算机",
            "25": "传媒",
            "26": "银行",
            "27": "非银金融",
            "28": "综合",
        }
    }
}
