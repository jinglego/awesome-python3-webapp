#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
# 指定logging记录信息的级别level为INFO
# 级别关系：CRITICAL > ERROR > WARNING > INFO > DEBUG > NOTSET
logging.basicConfig(level=logging.INFO)

import asyncio, os, json, time
from datetime import datetime
from aiohttp import web

def index(request):
    # 不加content_type的话打开链接会直接下载
    return web.Response(body=b'<h1>Awesome Web App</h1>', content_type='text/html', charset='UTF-8')

@asyncio.coroutine
def init(loop):
    """ 
    To get fully working example, you have to 
    (1)make application
    (2)register supported urls in router
    (3)create a server socket with Server as a protocol factory
    """

    # 创建web应用
    app = web.Application(loop=loop)
    # 将处理函数与对应的URL绑定，注册到创建的app.router中
    # 此处把通过GET方式传过来的对根目录的请求转发给index函数处理
    app.router.add_route('GET', '/', index)
    # 用aiohttp.RequestHandlerFactory作为协议簇创建套接字，用make_handle()创建，用来处理HTTP协议
    # yield from 返回一个创建好的，绑定IP、端口、HTTP协议簇的监听服务的协程 
    # 此处调用协程创建一个TCP服务器,绑定到"127.0.0.1:9000"socket,并返回一个服务器对象
    srv = yield from loop.create_server(app.make_handler(), '127.0.0.1', 9000)
    logging.info('server started at http://127.0.0.1:9000...')
    return srv


# 从asyncio模块中直接获取一个eventloop（事件循环）的引用
# 把需要执行的协程扔到eventloop中执行，从而实现异步IO
# loop是一个消息循环对象
loop = asyncio.get_event_loop()
# 在消息循环中执行协程
loop.run_until_complete(init(loop))
# 一直循环运行直到stop()
loop.run_forever()