import sqlite3, threading
from config import DATA
_l = threading.RLock(); _c = sqlite3.connect(DATA / "nexora.db", check_same_thread=False); _c.row_factory = sqlite3.Row
_c.executescript("""
create table if not exists projects(id text primary key,name text,created real,status text,progress real,stage text,error text,blueprint text,ref text);
create table if not exists media(id text primary key,pid text,name text,path text,kind text,w int,h int,dur real,hash text,dup int,faces int);
create table if not exists jobs(id text primary key,pid text,created real,status text,progress real,stage text,eta int,error text,out text,params text,cancel int default 0);""")
def q(sql, a=(), one=False):
    with _l:
        cur = _c.execute(sql, a); _c.commit(); r = cur.fetchall()
    return (dict(r[0]) if r else None) if one else [dict(x) for x in r]
