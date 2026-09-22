import re
from datetime import datetime

SESSION_TYPE_MAP = {
    'P': 'Practice',
    'Q': 'Qualifying',
    'R': 'Race',
    'FP': 'Practice',
    'PRACTICE': 'Practice',
    'QUALIFY': 'Qualifying',
    'QUALIFYING': 'Qualifying',
    'RACE': 'Race',
}

PATTERNS = [
    (re.compile(r'^(\d{4})_(\d{2})_(\d{2})_(\d{2})_(\d{2})_(.+)$'), 6),
    (re.compile(r'^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})_(.+)$'), 6),
    (re.compile(r'^(\d{2})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})_(.+)$'), 7),
]


def parse_session_name(raw_name):
    for pattern, type_group in PATTERNS:
        m = pattern.match(raw_name)
        if m:
            try:
                year = int(m.group(1))
                month = int(m.group(2))
                day = int(m.group(3))
                hour = int(m.group(4))
                minute = int(m.group(5))
                
                if year < 100:
                    year += 2000
                
                dt = datetime(year, month, day, hour, minute)
                session_code = m.group(type_group).strip().upper()
                session_name = SESSION_TYPE_MAP.get(session_code, m.group(type_group).title())
                return {
                    'datetime': dt,
                    'date_str': dt.strftime('%d/%m/%Y'),
                    'time_str': dt.strftime('%H:%M'),
                    'session': session_name,
                    'display': f"{session_name} - {dt.strftime('%d/%m/%Y %H:%M')}",
                }
            except (ValueError, IndexError):
                continue
    return {
        'datetime': None,
        'date_str': '',
        'time_str': '',
        'session': '',
        'display': raw_name.replace('_', ' ').title(),
    }
