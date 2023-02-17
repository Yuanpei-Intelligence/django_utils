from urllib import parse
from typing import cast

from django.http import HttpRequest


def get_ip(request: HttpRequest) -> str | None:
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = cast(str, x_forwarded_for).split(',')[-1].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def build_full_url(path: str, root: str) -> str:
    '''构建完整的URL

    将'/path/from/root'转换为'protocol://domain/path/from/root'。
    如果path已经是完整的URL，则直接返回。
    '''
    if not path:
        return root
    return parse.urljoin(root.rstrip('/') + '/', path)
