<!--<div align="center">

<picture>
  <source srcset="banner-dark.png" media="(prefers-color-scheme: dark)">
  <img src="banner.png">
</picture>

## Companion library for musiccast devices intended for the Home Assistant integration.

[![PyPI Version](https://img.shields.io/pypi/v/aiomusiccast.svg)](https://pypi.org/project/aiomusiccast)
![GitHub release (latest by date)](https://img.shields.io/github/v/release/vigonotion/aiomusiccast)
![Read the Docs](https://img.shields.io/readthedocs/aiomusiccast)
[![PyPI License](https://img.shields.io/pypi/l/aiomusiccast.svg)](https://pypi.org/project/aiomusiccast)


</div>

<br/>
-->

# crash0verride Compilation

This is a compilation of my own fixes and those of others in the upstream aiomusiccast while the maintainer(s) review the pulls in question. Changes have been made on the HA component layer to incorporate new features in the aiomusiccast library

### Actual Volume

I used the YXC integration as an example to incorporate a db based volume slider, that should be disabled by default, as this more directly correlates with the way the receiver is used than a percent value.

# Setup

## Requirements

* Python 3.10–3.14

## Installation

Install it directly into an activated virtual environment:

```text
$ pip install aiomusiccast
```

or add it to your [uv](https://docs.astral.sh/uv/) project:

```text
$ uv add aiomusiccast
```

# Usage

After installation, the package can imported:

```text
$ python
>>> import aiomusiccast
>>> aiomusiccast.__version__
```
