# awesome-python3-webapp 注释

花了好几个周末，终于在2017.5.21学完了✌️

来自廖雪峰的Python教程的实战项目，主要包含一下几个关键部分：
* app.py是主入口
* ORM框架，可以通过一个类来操作数据库中的一个表（用metaclass动态地创建类或者修改类，封装SQL）
* Web框架，注册URL处理函数，封装URL处理函数（从URL函数中分析其需要接收的参数，从Request中获取必要的参数）
* 具体的各URL处理函数，由定义的get()和post()装饰器将URL信息绑在一个函数上
* 中间件，把通用的模块（如logger_factory、response_factory等）抽出来，不用在每个URL的handler里都写
* 页面渲染，采用jinja2模版，负责对handler返回的结果进行显示（替换变量）
* 前端页面，由HTML、CSS、Javasript组成，使用UIkit、Vue(不懂前端😭)

期间参考了好几份注释，对他们表示感谢：
* [Engine-Treasure](https://github.com/Engine-Treasure/awesome-python3-webapp)
* [KaimingWan](https://github.com/KaimingWan/PureBlog)
* [ReedSun](https://github.com/ReedSun/Preeminent)
* [xwlyy](https://github.com/xwlyy/awesome-python3-webapp)
* [zhouxinkai](https://github.com/zhouxinkai/awesome-python3-webapp)
