import os.path
import sqlite3
from twisted.internet import defer
from twisted.enterprise import adbapi


class DB(object):

    def __init__(self):
        db_path = os.path.join(os.path.dirname(__file__), "data", "db.sqlite")
        self._db = adbapi.ConnectionPool(
            "sqlite3", database=db_path, timeout=30,
            # See http://twistedmatrix.com/trac/ticket/3629
            check_same_thread=False)
        self._init_db()

    def _init_db(self):
        def _init(cur):
            cur.execute("BEGIN EXCLUSIVE TRANSACTION")
            try:
                cur.execute("""CREATE TABLE accounts
                                   (jid TEXT PRIMARY KEY,
                                    password TEXT,
                                    in_use INTEGER)""")
            except sqlite3.OperationalError:
                pass
        return self._db.runInteraction(_init)

    def add_account(self, jid, password):
        return self._db.runOperation(
            "INSERT INTO accounts VALUES (?, ?, ?)", (jid, password, 0))

    def get_account(self):
        def _get_account(cur):
            cur.execute("BEGIN EXCLUSIVE TRANSACTION")
            acc = cur.execute("""SELECT jid, password FROM accounts
                                 WHERE in_use=0 LIMIT 1""").fetchone()
            if acc:
                cur.execute(
                    "UPDATE accounts SET in_use=1 WHERE jid=?", (acc[0],))
                return acc
        return self._db.runInteraction(_get_account)

    def get_all_accounts(self):
        return self._db.runQuery("SELECT jid, password FROM accounts")

    def free_jid(self, jid):
        return self._db.runOperation("""UPDATE accounts SET in_use=0
                                        WHERE jid=?""", (jid,))

db = DB()
