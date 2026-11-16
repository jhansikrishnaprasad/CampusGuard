"""Schema v1 (the first release) as raw DDL + sample rows, used to prove migrations preserve data."""
import sqlite3

DDL = """
CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(64) UNIQUE, password_hash VARCHAR(256), role VARCHAR(16), active BOOLEAN, created_at DATETIME);
CREATE TABLE session_tokens (id INTEGER PRIMARY KEY, token_hash VARCHAR(64) UNIQUE, user_id INTEGER REFERENCES users(id) ON DELETE CASCADE, expires_at DATETIME);
CREATE TABLE videos (id INTEGER PRIMARY KEY, original_filename VARCHAR(255), stored_name VARCHAR(128) UNIQUE, preview_name VARCHAR(128),
  size_bytes INTEGER, duration_s FLOAT, fps FLOAT, width INTEGER, height INTEGER, uploaded_at DATETIME, uploaded_by VARCHAR(64),
  status VARCHAR(16), error TEXT);
CREATE TABLE analysis_jobs (id INTEGER PRIMARY KEY, video_id INTEGER REFERENCES videos(id) ON DELETE CASCADE, status VARCHAR(16), progress FLOAT,
  model_versions TEXT, settings_snapshot TEXT, warnings TEXT, cancel_requested BOOLEAN, created_at DATETIME, started_at DATETIME,
  finished_at DATETIME, processing_seconds FLOAT, error TEXT);
CREATE TABLE tracked_people (id INTEGER PRIMARY KEY, video_id INTEGER REFERENCES videos(id) ON DELETE CASCADE, job_id INTEGER REFERENCES analysis_jobs(id) ON DELETE SET NULL,
  track_ref VARCHAR(32), first_seen_s FLOAT, last_seen_s FLOAT, detections INTEGER, shirt_status VARCHAR(32), trouser_status VARCHAR(32),
  uniform_overall VARCHAR(32), id_status VARCHAR(32), uniform_samples INTEGER, id_samples INTEGER, shirt_fraction FLOAT, trouser_fraction FLOAT,
  notes TEXT, membership_status VARCHAR(32));
CREATE TABLE events (id INTEGER PRIMARY KEY, video_id INTEGER REFERENCES videos(id) ON DELETE CASCADE, job_id INTEGER REFERENCES analysis_jobs(id) ON DELETE SET NULL,
  track_ref VARCHAR(32), category VARCHAR(48), start_s FLOAT, end_s FLOAT, confidence FLOAT, model_name VARCHAR(96), model_version VARCHAR(64),
  automated_status VARCHAR(16), review_status VARCHAR(16), review_notes TEXT, summary TEXT, created_at DATETIME, CONSTRAINT ck_event_interval CHECK (end_s >= start_s));
CREATE TABLE evidence (id INTEGER PRIMARY KEY, video_id INTEGER REFERENCES videos(id) ON DELETE CASCADE, event_id INTEGER REFERENCES events(id) ON DELETE CASCADE,
  person_id INTEGER REFERENCES tracked_people(id) ON DELETE CASCADE, kind VARCHAR(16), rel_path VARCHAR(300), timestamp_s FLOAT, created_at DATETIME);
CREATE TABLE reviews (id INTEGER PRIMARY KEY, event_id INTEGER REFERENCES events(id) ON DELETE CASCADE, reviewer VARCHAR(64), decision VARCHAR(16), notes TEXT, created_at DATETIME);
CREATE TABLE model_evaluations (id INTEGER PRIMARY KEY, model_name VARCHAR(96), model_version VARCHAR(64), dataset_name VARCHAR(128), dataset_version VARCHAR(64),
  evaluated_at DATETIME, precision FLOAT, recall FLOAT, f1 FLOAT, false_positive_rate FLOAT, seconds_per_minute_footage FLOAT, notes TEXT);
CREATE TABLE settings (key VARCHAR(64) PRIMARY KEY, value TEXT);
CREATE TABLE audit_log (id INTEGER PRIMARY KEY, username VARCHAR(64), action VARCHAR(48), target VARCHAR(96), detail TEXT, created_at DATETIME);
"""


def build_v1(path):
    con = sqlite3.connect(path)
    con.executescript(DDL)
    con.execute("INSERT INTO users VALUES (1,'admin','h','admin',1,'2026-10-01')")
    con.execute("INSERT INTO videos VALUES (1,'a.mp4','s1.mp4',NULL,100,60,25,640,480,'2026-10-01','admin','completed',NULL)")
    con.execute("INSERT INTO videos VALUES (2,'b.mp4','s2.mp4',NULL,100,60,25,640,480,'2026-10-02','admin','failed','boom')")
    con.execute("""INSERT INTO analysis_jobs VALUES (1,1,'completed',1.0,NULL,NULL,'["fight recognition not run: not_configured - x"]',0,
                   '2026-10-01','2026-10-01 10:00','2026-10-01 10:05',12.5,NULL)""")
    con.execute("INSERT INTO analysis_jobs VALUES (2,2,'failed',0.3,NULL,NULL,NULL,0,'2026-10-02','2026-10-02 10:00','2026-10-02 10:01',1,'boom')")
    con.execute("INSERT INTO tracked_people VALUES (1,1,1,'T1',0,30,40,'inconsistent','ok','possible_non_compliance','uncertain',5,5,0.02,0.7,NULL,'membership_unverified')")
    con.execute("INSERT INTO tracked_people VALUES (2,1,1,'T2',0,30,40,'ok','ok','compliant','detected',5,5,0.6,0.7,NULL,'membership_unverified')")
    con.execute("INSERT INTO tracked_people VALUES (3,1,1,'T3',0,30,40,'unable_to_verify','unable_to_verify','unable_to_verify','not_configured',0,0,NULL,NULL,NULL,'membership_unverified')")
    con.execute("INSERT INTO events VALUES (1,1,1,'T1','uniform_possible_violation',0,30,NULL,'Colour-range baseline','hsv-v1','predicted','confirmed','seen','s','2026-10-01')")
    con.execute("INSERT INTO events VALUES (2,1,1,NULL,'possible_smoking',5,9,0.8,'m','1','predicted','pending_review',NULL,'s','2026-10-01')")
    con.execute("INSERT INTO reviews VALUES (1,1,'admin','confirmed','seen','2026-10-03 09:00')")
    con.execute("INSERT INTO evidence VALUES (1,1,1,NULL,'frame','video_1/x.jpg',3,'2026-10-01')")
    con.commit(); con.close()
