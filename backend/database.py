"""
SmartCare - Database setup

Reads DATABASE_URL from the environment so the same code works locally
(SQLite, no setup needed) and in production (Render's managed Postgres).

Local dev:  no DATABASE_URL set -> falls back to sqlite:///./smartcare.db
Render:     Render injects DATABASE_URL automatically when you attach the
            Postgres instance defined in render.yaml - no manual copying
            of connection strings needed.

IMPORTANT: SQLite is fine on your laptop but must NOT be used on Render's
free web service tier - that tier has an ephemeral filesystem, so a local
.db file is wiped on every redeploy/restart/spin-down. Postgres is the
only option that actually persists data on Render's free plan.
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./smartcare.db")

# Render (and some other providers) hand out URLs starting with
# "postgres://", but SQLAlchemy 2.x + psycopg2 require "postgresql://".
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
