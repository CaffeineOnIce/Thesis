"""Reliable uplink: publish with QoS 1; if the link is down, queue in SQLite and flush in order later."""
import json, sqlite3, threading, time

class Uplink:
    def __init__(self, client, db_path, flush_every_s=10):
        self.client = client                      # a connected paho client (loop_start() already called)
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.lock = threading.Lock()
        self.db.execute("CREATE TABLE IF NOT EXISTS queue (id INTEGER PRIMARY KEY, topic TEXT, payload TEXT, queued_at REAL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS sent (topic TEXT, ts INTEGER, bytes INTEGER, sent_at REAL, was_queued INTEGER)")
        self.db.commit()
        threading.Thread(target=self._flusher, args=(flush_every_s,), daemon=True).start()

    def _try(self, topic, payload):
        if not self.client.is_connected():
            return False
        info = self.client.publish(topic, payload, qos=1)
        try:
            info.wait_for_publish(timeout=5)
        except (RuntimeError, ValueError):
            return False
        return info.is_published()

    def send(self, topic, payload: str):
        with self.lock:
            pending = self.db.execute("SELECT COUNT(*) FROM queue").fetchone()[0]
            if pending == 0 and self._try(topic, payload):          # keep order: never overtake the queue
                self._log(topic, payload, 0); return True
            self.db.execute("INSERT INTO queue (topic, payload, queued_at) VALUES (?,?,?)", (topic, payload, time.time()))
            self.db.commit(); return False

    def _log(self, topic, payload, was_queued):
        ts = json.loads(payload).get("ts")
        self.db.execute("INSERT INTO sent VALUES (?,?,?,?,?)", (topic, ts, len(payload.encode()), time.time(), was_queued))
        self.db.commit()

    def flush(self):
        with self.lock:
            for qid, topic, payload in self.db.execute("SELECT id, topic, payload FROM queue ORDER BY id").fetchall():
                if not self._try(topic, payload):
                    break
                self.db.execute("DELETE FROM queue WHERE id = ?", (qid,))
                self._log(topic, payload, 1)
            self.db.commit()

    def _flusher(self, every):
        while True:
            time.sleep(every)
            try:
                self.flush()
            except Exception as e:          # never let the flusher die
                print("flush error:", e)
