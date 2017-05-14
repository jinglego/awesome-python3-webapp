import asyncio, os, inspect, logging
import functools
from urllib import parse
from aiohttp import web
from apis import APIError

# 装饰器就是接受一个函数作为参数，并返回一个函数的高阶函数
# 如果decorator本身需要传入参数（如这里的path），那就需要编写一个返回decorator的高阶函数
# 即要三层函数，调用起来类似now = log('execute')(now)
def get(path):
    '''
    Define decorator @get('/path')
    '''
    def decorator(func):
        # 函数也是对象，有__name__属性
        # 但经过decorator装饰之后的函数，它们的__name__已经从原来的'fun'变成了'wrapper'
        # 不需要编写wrapper.__name__ = func.__name__这样的代码，用functools.wraps即可
        @functools.wraps(func)
        def wrapper(*args, **kw):
            return func(*args, **kw)
        # 添加__method__属性，设定请求方法为GET
        wrapper.__method__ = 'GET'
        # 添加__route__属性，设定请求路径为参数path
        wrapper.__route__ = path
        # 这样，一个函数通过@get()的装饰就附带了URL信息
        return wrapper
    return decorator

def post(path):
    '''
    Define decorator @post('/path')
    '''
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kw):
            return func(*args, **kw)
        # 添加__method__属性，设定请求方法为POST
        wrapper.__method__ = 'POST'
        wrapper.__route__ = path
        return wrapper
    return decorator

# inspect模块的四大用处：
# 1. type checking
# 2. getting source code
# 3. inspecting classes and functions（下面用了这个，获取类和函数的参数）
# 4. examining the interpreter stack

# 获取没有默认值的命名关键字参数（形参）
def get_required_kw_args(fn):
    args = []
    # 用signature()去获得一个Signature对象
    # parameters属性: An ordered mapping of parameters’ names to the corresponding Parameter objects.
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        # inspect.Parameter的kind类型有5种：
        # POSITIONAL_ONLY 位置参数
        # POSITIONAL_OR_KEYWORD 关键字或位置参数
        # VAR_POSITIONAL 可变参数*args
        # KEYWORD_ONLY 命名关键字参数，跟在*或*args后面
        # VAR_KEYWORD 关键字参数**kwargs
        if param.kind == inspect.Parameter.KEYWORD_ONLY and param.default == inspect.Parameter.empty:
            # param.default == inspect.Parameter.empty 参数的默认值为空
            args.append(name)
    return tuple(args)

# 获取命名关键字参数
def get_named_kw_args(fn):
    args = []
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            args.append(name)
    return tuple(args)

# 是否命名关键字参数
def has_named_kw_args(fn):
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            return True

# 是否关键字参数
def has_var_kw_arg(fn):
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            return True

# 是否有参数名为request的参数，且是最后一个
def has_request_arg(fn):
    sig = inspect.signature(fn)
    params = sig.parameters
    found = False
    for name, param in params.items():
        if name == "request":
            found = True
            continue
        # request参数必须是最后一个位置参数或关键字参数
        if found and (param.kind != inspect.Parameter.VAR_POSITIONAL and param.kind != inspect.Parameter.KEYWORD_ONLY and param.kind != inspect.Parameter.VAR_KEYWORD):
            raise ValueError('request parameter must be the last named parameter in function: %s%s' % (fn.__name__, str(sig)))
    return found

# 用RequestHandler()来封装一个URL处理函数
# 目的就是从URL函数中分析其需要接收的参数，从request中获取必要的参数
# 调用URL函数，然后把结果转换为web.Response对象
class RequestHandler(object):

    # RequestHandler()时会执行__init__
    def __init__(self, app, fn):
        self._app = app
        self._func = fn
        self._has_request_arg = has_request_arg(fn)
        self._has_var_kw_arg = has_var_kw_arg(fn)
        self._has_named_kw_args = has_named_kw_args(fn)
        self._named_kw_args = get_named_kw_args(fn)
        self._required_kw_args = get_required_kw_args(fn)

    # 定义了__call__()方法，这个类就相当于一个函数，因此可以将其实例视为函数
    # RequestHandler()()时会执行__call__
    async def __call__(self, request):
        # A BaseRequest/Request are dict-like objects, allowing them to be used for sharing data among Middlewares and Signals handlers.
        kw = None
        if self._has_var_kw_arg or self._has_named_kw_args or self._required_kw_args:
            if request.method == 'POST':
                if not request.content_type:
                    return web.HTTPBadRequest('Missing Content-Type.')
                ct = request.content_type.lower()
                if ct.startswith('application/json'):
                    # aiohttp文档 request的coroutine json(*, loads=json.loads)
                    # Read request body decoded as json. Accepts str and returns dict with parsed JSON. 
                    params = await request.json()
                    if not isinstancce(params, dict):
                        return web.HTTPBadRequest('JSON body must be object.')
                    kw = params
                # 两者表示消息主题是表单
                # application/x-www-form-urlencoded: 
                # The body of the HTTP message sent to the server is essentially one giant query string --
                # name/value pairs are separated by the ampersand (&), 
                # and names are separated from values by the equals symbol (=).
                # multipart/form-data: 
                # With this method of transmitting name/value pairs, each pair is represented as a "part" in a MIME message. 
                # Parts are separated by a particular string boundary.
                # Each part has its own set of MIME headers like Content-Type, and particularly Content-Disposition, which can give each part its "name."
                elif ct.startswith('application/x-www-form-urlencoded') or ct.startswith('multipart/form-data'):
                    # aiohttp文档 request的coroutine post()
                    # A coroutine that reads POST parameters from request body.
                    # Returns MultiDictProxy instance filled with parsed data.
                    # MultiDictProxy provides a dynamic view on the multidict’s entries, which means that when the multidict changes, the view reflects these changes.
                    params = await request.post()
                    kw = dict(**params)
                else:
                    return web.HTTPBadRequest('Unsupported Content-Type: %s' % request.content_type)
            if request.method == 'GET':
                # query_string: The query string in the URL
                qs = request.query_string
                if qs:
                    kw = dict()
                    # parse.parse_qs解析query，相当于把check_keywords=yes&area=default解析成{'check_keywords': ['yes'], 'area': ['default']}
                    for k, v in parse.parse_qs(qs, True).items():
                        kw[k] = v[0]
        if kw is None:
            # match_info貌似是@get装饰器里的参数？
            # Resource may have variable path also. For instance, a resource
            # with the path '/a/{name}/c' would match all incoming requests
            # with paths such as '/a/b/c', '/a/1/c', and '/a/etc/c'.

            # A variable part is specified in the form {identifier}, where the
            # identifier can be used later in a request handler to access the
            # matched value for that part. This is done by looking up the
            # identifier in the Request.match_info mapping:
            kw = dict(**request.match_info)
        else:
            if not self._has_var_kw_arg and self._named_kw_args:
                # remove all unamed kw:
                copy = dict()
                for name in self._named_kw_args:
                    if name in kw:
                        copy[name] = kw[name]
                kw = copy
            # check named arg:
            for k, v in request.match_info.items():
                if k in kw:
                    logging.warning('Duplicate arg name in named arg and kw args: %s' % k)
                kw[k] = v
        # 给request参数赋值
        if self._has_request_arg:
            kw['request'] = request
        # check required kw:
        if self._required_kw_args:
            for name in self._required_kw_args:
                if not name in kw:
                    return web.HTTPBadRequest('Missing argument: %s' % name)
        logging.info('call with args: %s' % str(kw))
        try:
            # 执行handler模块里的函数
            r = await self._func(**kw)
            return r
        except APIError as e:
            return dict(error=e.error, data=e.data, message=e.message)

# 添加静态页面的路径
def add_static(app):
    # os.path.abspath(__file__), 返回当前脚本的绝对路径(包括文件名)
    # os.path.dirname(), 去掉文件名,返回目录路径
    # os.path.join(), 将分离的各部分组合成一个路径名
    # 就是将本文件同目录下的static目录(即www/static/)加入到应用的路由管理器中
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
    # add_static(prefix, path, *, name=None, expect_handler=None, chunk_size=256*1024, response_factory=StreamResponse, show_index=False, follow_symlinks=False)
    # Adds a router and a handler for returning static files.
    app.router.add_static('/static/', path)
    logging.info('add static %s => %s' % ('/static/', path))

# 注册一个URL处理函数
def add_route(app, fn):
    method = getattr(fn, '__method__', None)
    path = getattr(fn, '__route__', None)
    if path is None or method is None:
        raise ValueError('@get or @post not defined in %s.' % str(fn))
    if not asyncio.iscoroutinefunction(fn) and not inspect.isgeneratorfunction(fn):
        fn = asyncio.coroutine(fn)
    logging.info('add route %s %s => %s(%s)' % (method, path, fn.__name__, ', '.join(inspect.signature(fn).parameters.keys())))
    # add_route(method, path, handler, *, name=None, expect_handler=None)
    # 处理方法为RequestHandler的自省函数 '__call__'
    app.router.add_route(method, path, RequestHandler(app, fn))

# 自动把handlers模块的所有符合条件的函数注册了
# 形如add_routes(app, 'handlers')
def add_routes(app, module_name):
    n = module_name.rfind('.')
    if n == (-1):
        # __import__同import语句同样的功能，通常在动态加载时可以使用到这个函数
        # __import__('os',globals(),locals(),['path','pip'])等价于from os import path, pip
        # globals, locals -- determine how to interpret the name in package context
        mod = __import__(module_name, globals(), locals())
    else:
        name = mudule_name[n+1:]
        # 取得子模块对象？如datetime.datetime
        mod = getattr(__import__(module_name[:n], globals(), locals(), [name]), name)
    # dir函数的作用是列出对象的所有特性（以及模块的所有函数、类、变量等），返回属性名str组成的list
    for attr in dir(mod):
        # 忽略以_开头的属性与方法,_xx或__xx(前导1/2个下划线)指示方法或属性为私有的,__xx__指示为特殊变量
        if attr.startswith('_'):
            continue
        fn = getattr(mod, attr)
        if callable(fn):
            method = getattr(fn, '__method__', None)
            path = getattr(fn, '__route__', None)
            if method and path:
                add_route(app, fn)








































