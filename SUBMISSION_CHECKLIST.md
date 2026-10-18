# Buyer assignment completion checklist

## Must replace with official information
- [ ] Official seller/team names and public URLs
- [ ] Correct offer cutoff and results release time/timezone
- [ ] Instructor-approved rules and customer model parameters
- [ ] Official price-file schema, including whether bundles are allowed
- [ ] Official product inventory and offer data
- [ ] Public deployment URL
- [ ] Authentication/access policy for any admin actions
- [ ] Instructor approval for data publication and model assumptions

## Test evidence to save
- [ ] `python -m unittest discover -s tests -v` passes
- [ ] Run a seeded simulation and record the seed
- [ ] Run same seed from identical starting state and verify same outcome
- [ ] Test invalid price, missing field, negative quantity, and duplicate offers
- [ ] Verify stock never goes below zero
- [ ] Verify inventory carries over to the next day
- [ ] Verify downloads contain the expected rows
- [ ] Verify audit log adds an event for each run/reset/replay
- [ ] Verify replay comparisons do not change live inventory or transactions
- [ ] Test public URL from a different browser/device

## Written report
- [ ] Explain utility function and customer types
- [ ] Explain how customers choose sellers and when they buy nothing
- [ ] State all assumptions and parameters
- [ ] Report validation and reproducibility evidence
- [ ] Compare results across seeds or scenarios while holding other inputs constant
- [ ] Discuss limitations and possible bias in the model
