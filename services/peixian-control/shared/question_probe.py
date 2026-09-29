"""Compact option-count probe results. Times, coordinates and totals only; no identities or text."""
VERSION = 'question-probe-v1'
MAX_POINTS = 2000


def _text(value):
    return value[:19] if isinstance(value, str) else None


def _coord(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def digest(kind, response):
    """Reduce a raw provider response to what option counting needs; None when unusable."""
    if not isinstance(response, dict) or response.get('code') != 200:
        return None
    data = response if kind in ('night', 'community', 'warnings') else response.get('data')
    if not isinstance(data, dict):
        return None
    if kind == 'tracks':
        points = data.get('points')
        if not isinstance(points, list):
            return None
        return {'points': [[_text(p.get('captureTime')), _coord(p.get('lon')), _coord(p.get('lat')),
                            str(p.get('deviceName') or '')[:40]]
                           for p in points[:MAX_POINTS] if isinstance(p, dict)]}
    if kind == 'incidents':
        rows = data.get('rows')
        if not isinstance(rows, list) or type(data.get('total')) is not int:
            return None
        return {'total': data['total'],
                'rows': [[str(r.get('jjbh') or r.get('cjbh') or i)[:40], _text(r.get('cjsj')),
                          _coord(r.get('gisX')), _coord(r.get('gisY'))]
                         for i, r in enumerate(rows[:MAX_POINTS]) if isinstance(r, dict)]}
    if type(data.get('total')) is not int or data['total'] < 0:
        return None
    return {'total': data['total']}
