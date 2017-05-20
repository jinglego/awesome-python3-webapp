#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
# 指定logging记录信息的级别level为INFO
# 级别关系：CRITICAL > ERROR > WARNING > INFO > DEBUG > NOTSET
logging.basicConfig(level=logging.INFO)

import asyncio, os, json, time
from datetime import datetime
from aiohttp import web
from jinja2 import Environment, FileSystemLoader

import orm
from coroweb import add_routes, add_static
from handlers import cookie2user, COOKIE_NAME

def index(request):
    # 不加content_type的话打开链接会直接下载
    return web.Response(body=b'<h1>Awesome Web App</h1>', content_type='text/html', charset='UTF-8')

def init_jinja2(app, **kw):
    logging.info('init jinja2...')
    options = dict(
        # 自动转义xml/html的特殊字符
        autoescape = kw.get('autoescape', True),
        # 设置代码起始字符串，相当于{% code %}
        block_start_string = kw.get('block_start_string', '{%'),
        # 设置代码的终止字符串
        block_end_string = kw.get('block_end_string', '%}'),
        # 设置变量的起始字符串，相当于{{ var }}
        variable_start_string = kw.get('variable_start_string', '{{'),
        # 设置变量的终止字符串
        variable_end_string = kw.get('variable_end_string', '}}'),
        # 自动加载修改后的模板文件
        auto_reload = kw.get('auto_reload', True)
    )
    path = kw.get('path', None)
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
    logging.info('set jinja2 template path: %s' % path)
    # FileSystemLoader(searchpath, encoding='utf-8'): Loads templates from the file system. 
    # This loader can find templates in folders on the file system and is the preferred way to load them.
    env = Environment(loader=FileSystemLoader(path), **options)
    filters = kw.get('filters', None)
    if filters is not None:
        for name, f in filters.items():
            env.filters[name] = f
    # 将jinja2的环境赋给app的__templating__属性
    app['__templating__'] = env

# 中间件，接受2个参数（1个app实例，1个handler函数），返回新的handler
# 通过装饰器实现
# 在处理请求前记录日志
async def logger_factory(app, handler):
    async def logger(request):
        logging.info('Request: %s %s' % (request.method, request.path))
        return (await handler(request))
    return logger

# 解析POST请求的数据
async def data_factory(app, handler):
    async def parse_data(request):
        if request.method == 'POST':
            if request.content_type.startswith('application/json'):
                # 将消息主体存入请求的__data__属性
                request.__data__ = await request.json()
                logging.info('request json: %s' % str(request.__data__))
            elif request.content_type.startswith('application/x-www-form-urlencoded'):
                request.__data__ = await request.post()
                logging.info('request form: %s' % str(request.__data__))
        return (await handler(request))
    return parse_data

# 解析cookie，并将登录用户绑定到request对象上。这样，后续的URL处理函数就可以直接拿到登录用户
async def auth_factory(app, handler):
    async def auth(request):
        logging.info('check user: %s %s' % (request.method, request.path))
        request.__user__ = None
        cookie_str = request.cookies.get(COOKIE_NAME)
        if cookie_str:
            user = await cookie2user(cookie_str)
            if user:
                logging.info('set current user: %s' % user.email)
                request.__user__ = user
        if request.path.startswith('/manage/') and (request.__user__ is None or not request.__user__.admin):
            return web.HTTPFound('/signin')
        return (await handler(request))
    return auth

# 将handler的返回值转换为web.Response对象，返回给客户端
async def response_factory(app, handler):
    async def response(request):
        logging.info('Response handler...')
        # 调用handler来处理URL请求，并返回结果
        r = await handler(request)
        # 若是StreamResponse，是aiohttp定义response的基类，即所有响应类型都继承自该类，直接返回
        if isinstance(r, web.StreamResponse):
            return r
        # 若是bytes，把字节流塞到response的body里，设置响应类型为流类型
        if isinstance(r, bytes):
            resp = web.Response(body=r)
            resp.content_type = 'application/octet-stream'
            return resp
        # 若是str
        if isinstance(r, str):
            # 判断是不是需要重定向，是的话直接用重定向的地址重定向
            if r.startswith("redirect:"):
                # 重定向
                return web.HTTPFound(r[9:])
            # 不是重定向的话，把字符串当做是html代码来处理
            resp = web.Response(body=r.encode("utf-8"))
            resp.content_type = 'text/html;charset=utf-8'
            return resp
        # 若是dict，则获取它的模板属性（jinja2的env）
        if isinstance(r, dict):
            template = r.get('__template__')
            # 若不存在对应模板，则将字典调整为json格式返回,并设置响应类型为json
            if template is None:
                resp = web.Response(body=json.dumps(r, ensure_ascii=False, default=lambda o: o.__dict__).encode('utf-8'))
            # 存在对应模板的,则将套用模板,用request handler的结果进行渲染
            else:
                resp = web.Response(body=app['__templating__'].get_template(template).render(**r).encode('utf-8'))
                resp.content_type = 'text/html;charset=utf-8'
                return resp
        # 若是int，此时r为状态码
        if isinstance(r, int) and r >= 100 and r < 600:
            return web.Response(r)
        # 若是tuple，此时r为状态码和错误描述
        if isinstance(r, tuple) and len(r) == 2:
            t, m = r
            if isinstance(t, int) and t >= 100 and t < 600:
                return web.Response(t, str(m))
        # default:
        resp = web.Response(body=str(r).encode('utf-8'))
        resp.content_type = 'text/plain;charset=utf-8'
        return resp
    return response

# 时间过滤器，返回固定时间格式（大概时间），用于在日志标题下方的时间显示
def datetime_filter(t):
    delta = int(time.time() - t)
    if delta < 60:
        return u'1分钟前'
    if delta < 3600:
        return u'%s分钟前' % (delta // 60)
    if delta < 86400:
        return u'%s小时前' % (delta // 3600)
    if delta < 604800:
        return u'%s天前' % (delta // 86400)
    dt = datetime.fromtimestamp(t)
    return u'%s年%s月%s日' % (dt.year, dt.month, dt.day)

async def init(loop):
    await orm.create_pool(loop=loop, host='127.0.0.1', port=3306, user='www-data', password='www-data', db='awesome')
    """ 
    To get fully working example, you have to 
    (1)make application
    (2)register supported urls in router
    (3)create a server socket with Server as a protocol factory
    """
    # 创建web应用
    app = web.Application(loop=loop, middlewares=[logger_factory, auth_factory, response_factory])
    init_jinja2(app, filters=dict(datetime=datetime_filter))
    # 将处理函数与对应的URL绑定，注册到创建的app.router中
    # 此处把通过GET方式传过来的对根目录的请求转发给index函数处理
    # app.router.add_route('GET', '/', index)
    add_routes(app, 'handlers')
    add_static(app)
    # 用aiohttp.RequestHandlerFactory作为协议簇创建套接字，用make_handle()创建，用来处理HTTP协议
    # yield from 返回一个创建好的，绑定IP、端口、HTTP协议簇的监听服务的协程 
    # 此处调用协程创建一个TCP服务器,绑定到"127.0.0.1:9000"socket,并返回一个服务器对象
    srv = await loop.create_server(app.make_handler(), '127.0.0.1', 9000)
    logging.info('server started at http://127.0.0.1:9000...')

    # await orm.destroy_pool()
    return srv


# 从asyncio模块中直接获取一个eventloop（事件循环）的引用
# 把需要执行的协程扔到eventloop中执行，从而实现异步IO
# loop是一个消息循环对象
loop = asyncio.get_event_loop()
# 在消息循环中执行协程
loop.run_until_complete(init(loop))
# 一直循环运行直到stop()
loop.run_forever()