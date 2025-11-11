---
id: task-4
title: detect insignificant changes and don't commit
status: Done
assignee: []
created_date: "2025-11-11 09:52"
labels: []
dependencies: []
---

A few of the sites use an email-protection hash that changes every visit, so
there are spurious changes in the output.

Perhaps a simple "if changes all match regex" check or something?

Also there's at least one site that gives an "error" page but with a 200 OK, so
that's confusing as well.
