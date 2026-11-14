<div align="center">

<picture>
  <source srcset="https://raw.githubusercontent.com/crash0verride11/aiomusiccast/aiomusiccast-co/banner-dark.png" media="(prefers-color-scheme: dark)">
  <img src="https://raw.githubusercontent.com/crash0verride11/aiomusiccast/aiomusiccast-co/banner.png" alt="aiomusiccast">
</picture>

## Asyncio library for Yamaha MusicCast devices

[![PyPI Version](https://img.shields.io/pypi/v/aiomusiccast-co.svg)](https://pypi.org/project/aiomusiccast-co)
[![CI](https://github.com/crash0verride11/aiomusiccast/actions/workflows/ci.yml/badge.svg?branch=aiomusiccast-co)](https://github.com/crash0verride11/aiomusiccast/actions/workflows/ci.yml)
[![Python Versions](https://img.shields.io/pypi/pyversions/aiomusiccast-co.svg)](https://pypi.org/project/aiomusiccast-co)
[![License](https://img.shields.io/pypi/l/aiomusiccast-co.svg)](https://github.com/crash0verride11/aiomusiccast/blob/aiomusiccast-co/LICENSE.md)

</div>

<br/>

`aiomusiccast-co` is a maintained fork of [aiomusiccast](https://github.com/vigonotion/aiomusiccast), the library
behind Home Assistant's Yamaha MusicCast integration. Upstream is no longer actively maintained, so this fork continues
from its last release (0.15.0) under a new name.

## What's new compared to aiomusiccast 0.15.0

- **Actual volume:** read and set the zone volume in dB, matching the receiver's display.
- **Zone scenes:** list a zone's scenes and recall them.
- **Surround AI:** on/off control for receivers that support it.
- **Speaker pattern** and **device category** support.
- Fixes for devices that omit the zone, input or sound program lists.
- A longer HTTP timeout (8s), and the package now ships `py.typed`.

See the [changelog](https://github.com/crash0verride11/aiomusiccast/blob/aiomusiccast-co/CHANGELOG.md) for details.

## Home Assistant

Home Assistant's core Yamaha MusicCast integration still uses upstream `aiomusiccast`, so it doesn't get these
added features. Where a feature applies to Home Assistant, support for it has been added to
[yamaha-musiccast-co](https://github.com/crash0verride11/yamaha-musiccast-co), a custom component version of the
integration that can be installed through HACS.

# Setup

## Requirements

* Python 3.11+

## Installation

```text
$ pip install aiomusiccast-co
```

or add it to your [uv](https://docs.astral.sh/uv/) project:

```text
$ uv add aiomusiccast-co
```

The distribution is `aiomusiccast-co`; the import name is `aiomusiccast_co`. It installs alongside upstream
`aiomusiccast` without conflict.

# Usage

```python
import asyncio

from aiohttp import ClientSession

from aiomusiccast_co import MusicCastDevice


async def main() -> None:
    async with ClientSession() as session:
        device = MusicCastDevice("192.168.1.50", session)
        await device.fetch()

        print(device.data.model_name, device.data.network_name)
        for zone_id, zone in device.data.zones.items():
            print(zone_id, zone.power, zone.current_volume)

        await device.set_volume_level("main", 0.3)


asyncio.run(main())
```

To get push updates instead of polling, register a callback with `device.register_callback(...)` and call
`await device.device.enable_polling()`, which starts the UDP event listener.

## Migrating from aiomusiccast

Install `aiomusiccast-co` in place of `aiomusiccast` and change the imports:

```python
# before
from aiomusiccast import MusicCastDevice
# after
from aiomusiccast_co import MusicCastDevice
```

The API is otherwise the same as upstream 0.15.0, with the additions above.

# Contributing

See [CONTRIBUTING.md](https://github.com/crash0verride11/aiomusiccast/blob/aiomusiccast-co/CONTRIBUTING.md).

# Credits

Originally written by [Tom Schneider (@vigonotion)](https://github.com/vigonotion) and contributors; `pyamaha.py` is
based on [rsc-dev/pyamaha](https://github.com/rsc-dev/pyamaha). Released under the MIT License.
