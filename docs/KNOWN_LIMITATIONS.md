# Known Limitations

- remote workers can register and heartbeat, but cannot execute jobs yet
- advanced scheduling, balancing, and orchestration are not implemented
- local worker execution is single-node and intentionally simple
- config is generated automatically for first run, but full in-app config editing is not implemented
- analytics are operational and concise, not BI-grade
- rich rename execution is still limited even though policy templates exist
- user management remains minimal beyond bootstrap/login/session handling
- update handling assumes a trusted release metadata source and archive download path
- automatic rollback is not implemented for failed updates; operator validation is still required
- current release is internal `v0.x`, not a fully hardened general release
