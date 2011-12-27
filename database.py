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

    @defer.inlineCallbacks
    def _init_db(self):
        try:
            yield self._db.runOperation("""CREATE TABLE accounts
                                            (jid TEXT PRIMARY KEY,
                                             password TEXT,
                                             in_use INTEGER)""")
        except sqlite3.OperationalError:
            pass

    def add_account(self, jid, password):
        return self._db.runOperation(
            "INSERT INTO accounts VALUES (?, ?, ?)", (jid, password, 0))

    def get_account(self):
        def _get_account(cur):
            cur.execute("PRAGMA synchronous = OFF")
            cur.execute("BEGIN EXCLUSIVE TRANSACTION")
            acc = cur.execute("""SELECT jid, password FROM accounts
                                 WHERE in_use=0 LIMIT 1""").fetchone()
            if acc:
                cur.execute(
                    "UPDATE accounts SET in_use=1 WHERE jid=?", (acc[0],))
                return acc
        return self._db.runInteraction(_get_account)

    def free_jid(self, jid):
        return self._db.runOperation("""UPDATE accounts SET in_use=0
                                        WHERE jid=?""", (jid,))

    def del_account(self, jid):
        return self._db.runOperation("""DELETE FROM accounts
                                        WHERE jid=?""", (jid,))

    def get_all_accounts(self):
        return self._db.runQuery("SELECT jid, password FROM accounts")


@defer.inlineCallbacks
def get_db():
    db = DB()
    yield db._init_db()
    defer.returnValue(db)
