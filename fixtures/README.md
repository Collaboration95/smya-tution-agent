# SMYA S0 fixture boundary

`fractions_contract_v1.json` is the frozen, synthetic Primary 5 fractions
contract. `seed/synthetic_centre_v1.json` contains the repeatable centre
fixture, attempts, immutable evidence, expected artifacts, denial, and
escalation paths. The only corpus is self-authored synthetic content; see
[`ADR-0001`](../docs/decisions/ADR-0001-synthetic-fractions-content.md).

Run the validation and repeatability check from the repository root:

```sh
python3 scripts/validate_s0_fixtures.py
python3 -m unittest discover -s tests -v
```

To obtain the deterministic materialised seed a future application can ingest:

```sh
python3 scripts/validate_s0_fixtures.py --render-seed > /tmp/smya-seed.json
```

The command never writes source fixtures and deliberately has no network,
database, model, or external-provider dependency.
