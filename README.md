# xmpp stress tool

## Dependens

1. python 2.6+
2. twisted 10.0+
3. pyOpenSSL 0.10+

## Install pre-requirements

* Linux (Debian example)
    1. `sudo apt-get install python`
    2. `sudo apt-get install python-twisted` (you can omit this step (twisted ships with kisa) but it recommend to install precompiled version)
    3. `sudo apt-get install python-openssl` (optional but strongly recommend -- many xmpp servers required tsl)
* Windows
    1. Get the latest python 2.x from http://python.org/download/ and install it.
    2. Install the latest pyOpenSSL from http://pypi.python.org/pypi/pyOpenSSL (optional but strongly recommend -- many xmpp servers required tsl).

## Usage

Basic help:
`/path/to/kisa.py --help`

Supported modes: *chat*. Additional modes coming soon.
You can set default config by rename `config.py.example` to `config.py`.
