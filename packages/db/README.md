# DB Package

Database models, migrations, and repository helpers for persistent file, job, worker, and policy state.

This package exists so schema and persistence concerns can evolve independently from the API and worker entry points.

Current scope:

- initial SQLAlchemy models for tracked files, probe snapshots, plan snapshots, and jobs
- Alembic bootstrap and an initial migration
- repository helpers for persisting Milestones 1 to 3 outputs
