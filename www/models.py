import time
# uuid是python中生成唯一ID的库
import uuid
from orm import Model, StringField, BooleanField, FloatField, TextField

# 用当前时间与随机生成的uuid合成作为id
def next_id():
    # time.time() 返回当前时间的时间戳(相对于1970.1.1 00:00:00以秒计算的偏移量)
    # uuid4()——由伪随机数得到，有一定的重复概率，该概率可以计算出来,hex属性将uuid转为32位的16进制数
    return '%015d%s000' % (int(time.time() * 1000), uuid.uuid4().hex)

# 这是一个用户名的表
class User(Model):
    __table__ = 'users'

    # 给一个Field增加一个default参数可以让ORM自己填入缺省值，非常方便。并且，缺省值可以作为函数对象传入，在调用save()时自动计算。
    id = StringField(primary_key=True, default=next_id, ddl='varchar(50)')
    email = StringField(ddl='varchar(50)')
    passwd = StringField(ddl='varchar(50)')
    admin = BooleanField()
    name = StringField(ddl='varchar(50)')
    image = StringField(ddl='varchar(500)') # 头像
    # 日期和时间用float类型存储在数据库中，而不是datetime类型，这么做的好处是不必关心数据库的时区以及时区转换问题，排序非常简单，显示的时候，只需要做一个float到str的转换，也非常容易。
    created_at = FloatField(default=time.time)

# 这是一个博客的表
class Blog(Model):
    __table__ = 'blogs'

    id = StringField(primary_key=True, default=next_id, ddl='varchar(50)')
    user_id = StringField(ddl='varchar(50)')
    user_name = StringField(ddl='varchar(50)')
    user_image = StringField(ddl='varchar(500)')
    name = StringField(ddl='varchar(50)')
    summary = StringField(ddl='varchar(200)')
    content = TextField()
    created_at = FloatField(default=time.time)

# 这是一个评论的表
class Comment(Model):
    __table__ = 'comments'

    id = StringField(primary_key=True, default=next_id, ddl='varchar(50)')
    blog_id = StringField(ddl='varchar(50)')
    user_id = StringField(ddl='varchar(50)')
    user_name = StringField(ddl='varchar(50)')
    user_image = StringField(ddl='varchar(500)')
    content = TextField()
    created_at = FloatField(default=time.time)
    