# kisa -- xmpp stress tool

## Dependencies

1. python 2.6+
2. twisted 10.0+
3. pyOpenSSL 0.10+

## Install pre-requirements

* Linux (Debian example)
    1. `sudo apt-get install python`
    2. `sudo apt-get install python-twisted` (you can omit this step (twisted ships with kisa) but it recommend to install precompiled version)
    3. `sudo apt-get install python-openssl` (optional but strongly recommend -- many xmpp servers required tls)
* Windows
    1. Get the latest python 2.x from http://python.org/download/ and install it.
    2. Install the latest pyOpenSSL from http://pypi.python.org/pypi/pyOpenSSL (optional but strongly recommend -- many xmpp servers required tls).

## Usage

Basic help:
`/path/to/kisa.py --help`

Supported modes: *chat*.  
You can set default config by rename `config.py.example` to `config.py`.

## License

To the extent possible under law, the author(s) have dedicated all copyright and related and neighboring rights to this software to the public domain worldwide. This software is distributed without any warranty.  
You should have received a copy of the CC0 Public Domain Dedication along with this software. If not, see http://creativecommons.org/publicdomain/zero/1.0/
