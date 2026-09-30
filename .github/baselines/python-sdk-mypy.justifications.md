# Justifications for the Python SDK mypy baseline

The baseline in `python-sdk-mypy.txt` records every strict-mypy finding in
`packages/python-sdk/decision_engine` as of the introduction of the type-check
lane (sdk#47). It is consumed by `mypy-baseline filter`, which lets existing
findings through but fails the lane on any *new* strict violation.

Each finding in the baseline is justified by the category it belongs to. No
baseline entry is accepted without one of the rationales below.

## Baseline categories

### `no-untyped-def`

Many internal helpers, model convenience methods, and surface-module wrappers
pre-date strict typing. They operate on runtime-validated JSON/`dict` payloads
or are thin passthroughs; adding precise annotations is a larger refactor that
will happen incrementally as the surrounding code is touched. The public
facade methods that consumers call already have typed signatures.

### `no-untyped-call` / `no-any-return`

The facade mixins forward to lazily-loaded surface modules to break import
cycles and to allow tests to monkey-patch the module loaders. Because the
modules are loaded via `importlib` and the underlying HTTP transport returns
raw JSON (`Any`), mypy cannot see the typed surface-module methods at the call
site. Runtime validation through Pydantic models and the `validate_model`
helpers guarantees the returned shapes match the declared return types.

### `assignment`

A small number of variables are reused for different value kinds (e.g. an `int`
then a `str`) inside control-plane and trigger surface helpers. These are
pre-existing local-variable patterns; correcting them is left to focused
cleanup PRs so this change stays minimal.

### `attr-defined`

- `device_headers.py` touches platform-specific `winreg` attributes that are
  not present in the type stubs used on non-Windows runners.
- `connector_surface_common.py` uses a `PageT` TypeVar bound that mypy does not
  statically resolve to the `pages` attribute.

### `override`

`models_dataset.py` overrides Pydantic `BaseModel.schema()` with a narrower
runtime signature. This is intentional to provide a dataset-specific schema
helper.

### `arg-type` / `return-value` / `var-annotated` / `unused-ignore`

Isolated pre-existing issues in request helpers and model modules. They are
recorded in the baseline rather than bundled into an unrelated CI change.

## Regenerating the baseline

After fixing a batch of existing errors, update the baseline with:

```bash
mypy --config-file packages/python-sdk/pyproject.toml \
  --strict packages/python-sdk/decision_engine \
  | mypy-baseline sync --config packages/python-sdk/pyproject.toml
```

Review the diff to ensure only fixed errors were removed.
