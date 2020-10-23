import os
import sqlite3 as sql


class DB:

    def __init__(self, path, feeds):
        db_exists = False
        if os.path.exists(path):
            db_exists = True

        self.__conn     = sql.connect(path)
        self.__cur      = self.__conn.cursor()

        if not db_exists:
            self.__initialize_tables(feeds)
        self.__select_feeds()

    def __initialize_tables(self, feeds):
        self.__cur.execute("""CREATE TABLE FEEDS(
                                  ID            INTEGER         PRIMARY KEY,
                                  FEED          TEXT)""")
        self.__cur.executemany("""INSERT INTO FEEDS(FEED)
                                  VALUES(?)""", 
                               [(feed, ) for feed in feeds])

        self.__cur.execute("""CREATE TABLE STATES(
                                  ID            INTEGER         PRIMARY KEY,
                                  FEED_ID       INTEGER,
                                  [VALUE]       FLOAT,
                                  [TIMESTAMP]   TIMESTAMP)""")
        self.__conn.commit()
    def __select_feeds(self):
        # select order matters in creating dictionary from key-value pairs
        self.__cur.execute("""SELECT FEED,
                                     ID
                              FROM FEEDS""")
        self.__feed_ids = dict(self.__cur.fetchall())

    def insert_cur_state(self, feed, value, timestamp):
        self.__cur.execute("""INSERT INTO STATES(FEED_ID, [VALUE], [TIMESTAMP])
                              VALUES(?, ?, ?)""", 
                           (self.__feed_ids[feed], value, timestamp))
        self.__conn.commit()
    def select_prev_state(self, feed):
        self.__cur.execute("""SELECT [VALUE]
                              FROM STATES
                              WHERE FEED_ID = ?
                              ORDER BY ID DESC
                              LIMIT 1""", 
                           (self.__feed_ids[feed], ))
        row = self.__cur.fetchone()
        if row:
            return row[0]
        return None

    def delete_old_state_records(self, old_time):
        self.__cur.execute("""DELETE FROM STATES 
                              WHERE TIMESTAMP < ?""", 
                          (old_time,))
