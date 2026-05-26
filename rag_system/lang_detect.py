"""Language detection for document routing."""


def detect_lang(text: str) -> dict:
    """Analyze text character composition. Returns dict with ratios."""
    if not text:
        return {'cn_ratio': 0, 'en_ratio': 0, 'total': 0}
    cn = sum(1 for c in text if '一' <= c <= '鿿' or '㐀' <= c <= '䶿')
    en = sum(1 for c in text if c.isascii() and c.isalpha())
    total = cn + en or 1
    return {'cn_ratio': cn / total, 'en_ratio': en / total, 'total': total, 'cn': cn, 'en': en}


def route_to_kbs(text: str) -> list:
    """Decide which KB configs a document should go to. Returns list of config names."""
    lang = detect_lang(text)
    targets = []
    if lang['cn_ratio'] > 0.4:
        targets.append('pro')
    if lang['en_ratio'] > 0.4:
        targets.append('en')
    if not targets:
        targets.append('pro')  # default
    return targets
