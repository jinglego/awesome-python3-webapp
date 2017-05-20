import logging
import asyncio
import aiomysql

def log(sql, args=()):
    logging.info('SQL:%s' % sql)

async def create_pool(loop, **kw):
    logging.info('create database connection pool...')
    # 创建一个全局的连接池避免频繁关闭和打开数据库连接
    # 如果在局部要对全局变量修改，需要在局部也要先声明该变量为全局变量
    global __pool
    __pool = await aiomysql.create_pool(
        host=kw.get('host', 'localhost'),
        port=kw.get('port', 3306),
        user=kw['user'],
        password=kw['password'],
        db=kw['db'],
        charset=kw.get('charset', 'utf8'),
        autocommit=kw.get('autocommit', True),  # 默认自动提交事务
        maxsize=kw.get('maxsize', 10),          # 连接池最多同时处理10个请求
        minsize=kw.get('minszie', 1),           # 连接池最少1个请求
        loop=loop                               # 传递消息循环event_loop实例用于异步执行
    )

async def destroy_pool():  
    global __pool  
    if __pool is not None:
        # Mark all pool connections to be closed on getting back to pool. 
        # Closed pool doesn’t allow to acquire new connections.
        # 关闭连接池, close()方法不是一个协程，不用yield from或await  
        __pool.close()
        # If you want to wait for actual closing of acquired connection 
        # please call wait_closed() after close().
        # wait_close()方法是一个协程   
        await __pool.wait_closed() 

async def select(sql, args, size=None):
    log(sql, args)
    global __pool
    # 异步等待连接池对象返回可以连接线程，with语句则封装了清理（关闭conn）和处理异常的工作
    async with __pool.get() as conn:
        # 打开一个DictCursor,它与普通游标的不同在于,以dict形式返回结果
        # 即原来返回类似的tuple结果集合 ((1000L, 0L), (2000L, 0L), (3000L, 0L))
        # 现在返回dict结果集合 ({'user_id': 0L, 'blog_id': 1000L}, {'user_id': 0L, 'blog_id': 2000L}, {'user_id': 0L, 'blog_id': 3000L})
        async with conn.cursor(aiomysql.DictCursor) as cur:
            # SQL语句的占位符是?，而MySQL的占位符是%s, 这里要做一下替换,
            # args是sql语句对应占位符的参数
            await cur.execute(sql.replace('?', '%s'), args or ())
            if size:
                # 获取指定数量（可能小于）的记录
                rs = await cur.fetchmany(size)
            else:
                # 获取所有记录
                rs = await cur.fetchall()
        logging.info('rows returned: %s' % len(rs))
        return rs

# execute()函数和select()函数所不同的是，cursor对象不返回结果集
# 而是通过rowcount返回结果数（操作影响的行号）
# 适用于INSERT、UPDATE、DELETE语句
async def execute(sql, args, autocommit=True):
    log(sql)
    async with __pool.get() as conn:
        if not autocommit:
            await conn.begin()
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(sql.replace('?', '%s'), args)
                # 返回受影响的行数
                affected = cur.rowcount
            if not autocommit:
                await conn.commit()
        except BaseException as e:
            if not autocommit:
                await conn.rollback()
            # raise不带参数，则把此处的错误往上抛
            raise
        #finally:
            # 执行完SQL语句，释放与数据库的连接，否则event loop is closed错误
            #conn.close()
        return affected

# insert插入属性时候，增加num个数量的占位符'?'
# 比如说：insert into  `User` (`password`, `email`, `name`, `id`) values (?,?,?,?) 后面这四个问号
def create_args_string(num):
    L = []
    for n in range(num):
        L.append('?')
    return ', '.join(L)

# 任何继承自Model的类（比如User），会自动通过ModelMetaclass扫描映射关系，并存储到自身的类属性如__table__、__mappings__中
class ModelMetaclass(type):

    # __new__()方法接收到的参数依次是：
    # 当前准备创建的类的对象
    # 类的名字
    # 类继承的父类集合
    # 类的方法集合
    def __new__(cls, name, bases, attrs):
        # 排除Model类本身是因为要排除对Model类的修改
        if name=='Model':
            return type.__new__(cls, name, bases, attrs)
        # 获取table名称:
        tableName = attrs.get('__table__', None) or name
        logging.info('found model: %s (table: %s)' % (name, tableName))
        # 获取所有的Field和主键名:
        mappings = dict()
        # field保存的是除主键外的属性名
        fields = []
        primaryKey = None
        for k, v in attrs.items():
            # 如果是Field类型的则加入mappings对象
            if isinstance(v, Field):
                logging.info('  found mapping: %s ==> %s' % (k, v))
                mappings[k] = v
                if v.primary_key:
                    # 找到主键:
                    if primaryKey:
                        # 如果已经有主键了，则抛出错误
                        raise RuntimeError('Duplicate primary key for field: %s' % k)
                    primaryKey = k
                else:
                    fields.append(k)
        # 如果遍历完还没找到主键，那抛出错误
        if not primaryKey:
            raise RuntimeError('Primary key not found.')
        # 防止实例属性覆盖类的同名属性，从类属性中删除Field属性，以免造成运行时错误
        for k in mappings.keys():
            attrs.pop(k)
        # %s占位符全部替换成具体的属性名，带上反引号`（也称转换符）
        # 即将除主键外的其他属性变成`id`, `name`这种形式，
        escaped_fields = list(map(lambda f: '`%s`' % f, fields))
        attrs['__mappings__'] = mappings # 保存属性和列的映射关系
        attrs['__table__'] = tableName # 表名
        attrs['__primary_key__'] = primaryKey # 主键属性名
        attrs['__fields__'] = fields # 除主键外的属性名
        # 构造默认的SELECT, INSERT, UPDATE和DELETE语句:
        attrs['__select__'] = 'select `%s`, %s from `%s`' % (primaryKey, ', '.join(escaped_fields), tableName)
        attrs['__insert__'] = 'insert into `%s` (%s, `%s`) values (%s)' % (tableName, ', '.join(escaped_fields), primaryKey, create_args_string(len(escaped_fields) + 1))
        attrs['__update__'] = 'update `%s` set %s where `%s`=?' % (tableName, ', '.join(map(lambda f: '`%s`=?' % (mappings.get(f).name or f), fields)), primaryKey)
        attrs['__delete__'] = 'delete from `%s` where `%s`=?' % (tableName, primaryKey)
        return type.__new__(cls, name, bases, attrs)

# 定义所有ORM映射的基类Model
# 使既可以像字典那样通过[]访问key值（继承了字典类），也可以通过.访问key值（实现特殊方法__getattr__和__setattr__）
# 通过ModelMetaclass元类来构造类
class Model(dict, metaclass=ModelMetaclass):

    # 这里调用了Model的父类dict的初始化方法
    def __init__(self, **kw):
        super(Model, self).__init__(**kw)

    # 只有在没有找到属性的情况下，才调用__getattr__，已有的属性，不会在__getattr__中查找
    # 因为字典类的key不是属性，相当于用.无法获取属性，默认会使用__getattr__方法，此时返回字典类的value，与取属性效果一致
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(r"'Model' object has no attribute '%s'" % key)

    def __setattr__(self, key, value):
        self[key] = value

    # #上面两个方法是用来获取和设置**kw转换而来的dict的值，而下面的getattr是用来获取当前实例的属性值
    def getValue(self, key):
        # 获取某个具体的值，肯定存在的情况下使用该函数,否则会使用__getattr()__
        return getattr(self, key, None)

    def getValueOrDefault(self, key):
        value = getattr(self, key, None)
        if value is None:
            # self.__mapping__在metaclass中，用于保存不同实例属性在Model基类中的映射关系
            field = self.__mappings__[key]
            if field.default is not None:
                value = field.default() if callable(field.default) else field.default
                logging.debug('using default value for %s: %s' % (key, str(value)))
                setattr(self, key, value)
        return value
    
    # classmethod这个装饰器是类方法的意思，即可以不创建实例直接调用类方法让，所有子类调用class方法
    # 表示参数cls被绑定到类的类型对象(在这里即为<class '__main__.User'> )而不是实例对象
    @classmethod
    async def find(cls, pk):
        ' find object by primary key. '
        # 之前已将数据库的select操作封装在了select函数中,传入了三个参数分别是 sql、args、size
        rs = await select('%s where `%s`=?' % (cls.__select__, cls.__primary_key__), [pk], 1)
        if len(rs) == 0:
            return None
        # **表示关键字参数，将rs[0]即结果集合中的第一个（也是唯一一个）转换成关键字参数元组，rs[0]为dict
        # 通过<class '__main__.User'>(位置参数元组)，产生一个实例对象
        # 注意,我们在select函数中,打开的是DictCursor,它会以dict的形式返回结果
        return cls(**rs[0])

    @classmethod
    async def findAll(cls, where=None, args=None, **kw):
        sql = [cls.__select__]
        if where:
            sql.append('where')
            sql.append(where)
        if args is None:
            args = []
        orderBy =  kw.get('orderBy', None)
        if orderBy:
            sql.append('order by')
            sql.append(orderBy)
        # LIMIT 子句可以被用于指定 SELECT 语句返回的记录数（范围）
        limit = kw.get('limit', None)
        if limit is not None:
            sql.append('limit')
            if isinstance(limit, int):
                # 返回第x行
                sql.append('?')
                args.append(limit)
            elif isinstance(limit, tuple) and len(limit) == 2:
                # 返回第x到y行
                sql.append('?, ?')
                # extend() 函数用于在列表末尾一次性追加另一个序列中的多个值（用新列表扩展原来的列表）
                args.extend(limit)
            else:
                raise ValueError('Invalid limit value: %s' % str(limit))
        rs = await select(' '.join(sql), args)
        return [cls(**r) for r in rs]

    @classmethod
    async def findNumber(cls, selectField, where=None, args=None):
        # 根据WHERE条件查找，但返回的是整数，适用于select count(*)类型的SQL
        ' find number by select and where. '
        # 这里的 _num_ 为别名，任何客户端都可以按照这个名称引用这个列，就像它是个实际的列一样
        sql = ['select %s _num_ from `%s`' % (selectField, cls.__table__)]
        # sql = ['select count(%s) _num_ from `%s`' % (selectField, cls.__table__)]
        if where:
            sql.append('where')
            sql.append(where)
        rs = await select(' '.join(sql), args, 1)
        if len(rs) == 0:
            return None
        return rs[0]['_num_']

    async def save(self):
        # 这个是实例方法
        # arg是保存所有Model实例属性和主键的list,使用getValueOrDefault方法的好处是保存默认值
        args = list(map(self.getValueOrDefault, self.__fields__))
        # 我们在定义__insert__时,将主键放在了末尾.因为属性与值要一一对应,因此通过append的方式将主键加在最后
        args.append(self.getValueOrDefault(self.__primary_key__))
        rows = await execute(self.__insert__, args)
        if rows != 1:
            logging.warn('failed to insert record: affected rows: %s' % rows)

    async def update(self):
        # 只能更新此次给出的有新值的属性，因此不能使用getValueOrDefault方法
        args = list(map(self.getValue, self.__fields__))
        args.append(self.getValue(self.__primary_key__))
        rows = await execute(self.__update__, args)
        if rows != 1:
            logging.warn('failed to update by primary key: affected rows: %s' % rows)

    async def remove(self):
        args = [self.getValue(self.__primary_key__)]
        rows = await execute(self.__delete__, args)
        if rows != 1:
            logging.warn('failed to remove by primary key: affected rows: %s' % rows)

# 属性的基类，给其他具体Model类继承，负责保存(数据库)表的一组字段名和字段类型  
class Field(object):

    # 表的字段包含名字、类型、是否为表的主键和默认值
    def __init__(self, name, column_type, primary_key, default):
        self.name = name
        self.column_type = column_type
        self.primary_key = primary_key
        self.default = default

    # 返回表名字, 字段名:字段类型
    def __str__(self):
        return '<%s, %s:%s>' % (self.__class__.__name__, self.column_type, self.name)

class StringField(Field):

    # String一般不作为主键，所以默认False，DDL是数据定义语言，为了配合mysql，所以默认设定为100的长度
    def __init__(self, name=None, primary_key=False, default=None, ddl='varchar(100)'):
        super().__init__(name, ddl, primary_key, default)

class BooleanField(Field):

    def __init__(self, name=None, default=False):
        super().__init__(name, 'boolean', False, default)

class IntegerField(Field):

    def __init__(self, name=None, primary_key=False, default=0):
        super().__init__(name, 'biginit', primary_key, default)

class FloatField(Field):

    def __init__(self, name=None, primary_key=False, default=0.0):
        super().__init__(name, 'real', primary_key, default)

class TextField(Field):

    def __init__(self, name=None, default=None):
        # 这个是不能作为主键的对象，所以这里直接就设定成False了
        super().__init__(name, 'text', False, default)  
