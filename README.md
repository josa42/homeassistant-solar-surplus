# Solar Surplus

[![License](https://img.shields.io/github/license/josa42/homeassistant-solar-surplus?style=flat-square)](LICENSE)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=flat-square)](https://hacs.xyz/)

A Home Assistant integration that hands the power your solar panels produce
beyond what the house uses to the consumers you choose, in the order you choose,
and can always tell you why a consumer is on or off.

> [!NOTE]
> Nothing is released yet.

<br><br>

## Development

```bash
make install    # create the venv and install the test dependencies
make test       # run the tests
make lint       # run ruff
make dev-up     # start a local Home Assistant on http://localhost:8123
make dev-logs   # follow its logs
make dev-down   # stop it
```

`make dev-up` mounts `custom_components/` into the container, so a
`make dev-restart` picks up code changes.

<br><br>

## License

MIT, see [LICENSE](LICENSE).
