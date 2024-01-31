import os
import json
import logging
from typing import Callable, Any, cast, ParamSpec, Concatenate, TypeVar

from ..http.dependency import HttpRequest
from ..inspect import module_filepath
from ..wrap import return_on_except, Listener, ExceptType


__all__ = [
    'Logger',
]


_loggers: dict[str, 'Logger'] = dict()
P = ParamSpec('P')
T = TypeVar('T')
R = TypeVar('R', bound=HttpRequest)
ReturnType = T | Callable[[], T]
ViewFunction = Callable[Concatenate[R, P], T]


class Logger(logging.Logger):
    '''日志记录器

    捕获错误信息的日志，提供了错误工具和视图包装器
    相比于默认Logger，提供了便于设置统一的日志级别和格式的接口
    获取的实例会被缓存，不会重复创建

    Warning:
        请不要直接使用Logger，应使用getLogger获取实例
        如果指定getLogger不初始化，使用前需要调用setup或setupConfig

    Note:
        在 pipe_size 内的日志记录（通常为 4096 字节）是原子的。
        这对于除回溯以外的大多数情况已经足够，如需保证原子性请限制回溯的深度。
        (https://stackoverflow.com/questions/47968861/does-python-logging-support-multiprocessing)
    '''

    @classmethod
    def getLogger(cls, name: str, setup: bool = True):
        if name in _loggers:
            return cast(cls, _loggers[name])
        _logger_class  = logging.getLoggerClass()
        logging.setLoggerClass(cls)
        logger = cast(cls, logging.getLogger(name))
        logging.setLoggerClass(_logger_class)
        if setup:
            logger.setup(name)
        _loggers[name] = logger
        return logger

    def setup(self, name: str, handle: bool = True) -> None:
        self.setupConfig()
        if handle: self.add_default_handler(name)

    def setupConfig(self) -> None:
        from django.conf import settings
        self.debug_mode = settings.DEBUG
        self.format = '{asctime} [{levelname}] {message}'
        self.format_style = '{'
        self.stack_level = 8
        self.setLevel(logging.INFO)

    def add_default_handler(self, name: str, *paths: str, format: str = None) -> None:
        base_dir = os.path.join(*paths)
        os.makedirs(base_dir, exist_ok=True)
        file_path = os.path.join(base_dir, name + '.log')
        handler = logging.FileHandler(file_path, encoding='UTF8', mode='a')
        formatter = logging.Formatter(format or self.format, style=self.format_style)
        handler.setFormatter(formatter)
        self.addHandler(handler)

    def findCaller(self, stack_info: bool = False, stacklevel: int = 1):
        filepath, lineno, funcname, sinfo = super().findCaller(stack_info, stacklevel + 1)
        filepath = module_filepath(filepath)
        return filepath, lineno, funcname, sinfo

    def makeRecord(self, *args, **kwargs):
        record = super().makeRecord(*args, **kwargs)
        try:
            record.module, record.filename = record.pathname.rsplit('.', 1)
        except:
            record.module, record.filename = record.pathname, record.pathname
        return record

    def _log(self, level, msg, args, exc_info = None, extra = None,
             stack_info = False, stacklevel = 1) -> None:
        if stack_info:
            stacklevel += self.stack_level
        stacklevel += 1
        return super()._log(level, msg, args, exc_info, extra, stack_info, stacklevel)

    @staticmethod
    def format_request(request: HttpRequest) -> str:
        return '\n'.join(Logger._request_msgs(request))

    @classmethod
    def _request_msgs(cls, request: HttpRequest) -> list[str]:
        msgs = []
        msgs.append('URL: ' + request.get_full_path())
        if request.user.is_authenticated:
            msgs.append('User: ' + request.user.__str__())  # Traceable Call
        if request.method is not None:
            msgs.append('Method: ' + request.method)
            if request.method.lower() == 'POST':
                try:
                    msgs.append('Data: ' + json.dumps(request.POST.dict()))
                except:
                    msgs.append('Failed to jsonify post data.')
        return msgs

    def on_exception(self, message: str = '', *,
                     request: HttpRequest | None = None,
                     raise_exc: bool | None = None) -> None:
        '''
        Log exception and raise it if needed.

        Args:
            message (str, optional): 基础日志信息. Defaults to ''.
            request (HttpRequest, optional): 记录请求信息. Defaults to None.
            raise_exc (bool, optional): 是否抛出异常，不提供则根据debug模式决定
        '''
        if request is not None:
            msgs = self._request_msgs(request)
            if message:
                msgs.append(message)
            message = '\n'.join(msgs)
        self.exception(message, stacklevel=2)
        if raise_exc is None:
            raise_exc = self.debug_mode
        if raise_exc:
            raise

    def secure_view(
        self, message: str = '', *,
        raise_exc: bool | None = None,
        fail_value: ReturnType[Any] = None,
        exc_type: ExceptType[Exception] = Exception
    ) -> Callable[[ViewFunction[R, P, T]], ViewFunction[R, P, T]]:
        listener = self.listener(message, as_view=True, raise_exc=raise_exc)
        return return_on_except(fail_value, exc_type, listener)

    def secure_func(
        self, message: str = '', *,
        raise_exc: bool | None = False,
        fail_value: ReturnType[Any] = None,
        exc_type: ExceptType[Exception] = Exception
    ) -> Callable[[Callable[P, T]], Callable[P, T]]:
        listener = self.listener(message, as_view=False, raise_exc=raise_exc)
        return return_on_except(fail_value, exc_type, listener)

    def _get_request_arg(self, request: HttpRequest, *args, **kwargs) -> HttpRequest:
        return request

    def _traceback_msgs(self, exc_info: Exception, func: Callable) -> list[str]:
        msgs = []
        msgs.append(f'Except {exc_info.__class__.__name__}: {exc_info}')
        msgs.append(f'Function: {func.__module__}.{func.__qualname__}')
        return msgs

    def _arg_msgs(self, args: tuple, kwargs: dict) -> list[str]:
        msgs = []
        if args: msgs.append(f'Args: {args}')
        if kwargs: msgs.append(f'Keywords: {kwargs}')
        return msgs

    def listener(self, message: str = '', *,
                 as_view: bool = False,
                 raise_exc: bool | None = None) -> Listener[Exception]:
        def _listener(exc: Exception, func: Callable, args: tuple, kwargs: dict):
            msgs = []
            if as_view:
                request = self._get_request_arg(*args, **kwargs)
                msgs.extend(self._request_msgs(request))
            else:
                msgs.extend(self._traceback_msgs(exc, func))
                msgs.extend(self._arg_msgs(args, kwargs))
            if message:
                msgs.append(message)
            self.on_exception('\n'.join(msgs), raise_exc=raise_exc)
        return _listener
