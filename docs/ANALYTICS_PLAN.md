# Analytics Plan

## Current analytics baseline

- tracked-file counts by lifecycle/compliance/protected/4K state
- job counts by status
- plan counts by action
- verification/replacement outcome counts
- measured input/output size savings where available
- recent activity summaries
- plan-intent media summaries
- latest-probe summaries for selected media characteristics

## Purpose

Current analytics are operational. They support dashboards, reporting, troubleshooting, and capacity awareness. They are not BI-grade and do not attempt to be a general reporting platform.

## Source of truth

- persisted tracked-file/job/plan/probe history
- measured job sizes where available
- persisted verification/replacement outcomes
- explicit distinction between probe-derived and plan-intent-derived metrics

## Current UI use

- dashboard cards and breakdowns
- reports page summary sections

## Future work

- richer time-series trends
- remote-worker analytics
- review/hold trend reporting
- export/report-builder features
