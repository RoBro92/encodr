# UI Plan

## Purpose

The UI is an operational console, not a marketing site. It should help an operator understand what the system is doing, why it made a decision, and whether intervention is required.

## Initial sections

- dashboard summary
- recent jobs and queue state
- worker status
- storage status
- policy summary and version display
- analytics overview
- authenticated files and jobs views
- read-only effective configuration view

## Design principles

- explain decisions plainly
- make risky actions obvious
- prefer operational clarity over decorative complexity
- surface policy version and worker identity in relevant views

## Milestone mapping

- Milestone 0: placeholder dashboard shell
- Milestone 9: authenticated routed UI shell with dashboard, files, jobs, system, and config pages backed by the operational API
- Milestone 10: analytics pages
- Milestone 11: storage and worker health pages
- Milestone 12: manual review flows
