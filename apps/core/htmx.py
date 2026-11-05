def is_htmx(request) -> bool:
    return request.headers.get('HX-Request') == 'true'
