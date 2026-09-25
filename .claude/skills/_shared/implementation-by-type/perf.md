# Performance implementation guide

Run the recorded baseline and candidate with the same workload, environment, warm-up, and repeats. Preserve
functional tests, report distribution/tolerance rather than a single favorable run, and revert if the rollback
threshold is crossed.
