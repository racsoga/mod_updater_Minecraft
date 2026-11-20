"""MurmurHash2 (32 bits) y fingerprint al estilo CurseForge.

CurseForge identifica cada archivo con MurmurHash2 de 32 bits, seed = 1,
calculado sobre los bytes del archivo tras eliminar los bytes de espacio en
blanco 9 (tab), 10 (LF), 13 (CR) y 32 (espacio).

Ojo: `mmh3` es MurmurHash3 y NO sirve.
"""

from __future__ import annotations

import sys
from array import array

_M = 0x5BD1E995
_MASK = 0xFFFFFFFF
_WHITESPACE = b"\t\n\r "


def murmur2(data: bytes, seed: int = 0) -> int:
    """MurmurHash2 de 32 bits (algoritmo original de Austin Appleby, little-endian)."""
    length = len(data)
    h = (seed ^ length) & _MASK
    nblocks = length >> 2

    if nblocks:
        words = array("I")
        if words.itemsize != 4:  # pragma: no cover - plataformas exóticas
            words = array("L")
        words.frombytes(data[: nblocks * 4])
        if sys.byteorder == "big":  # pragma: no cover
            words.byteswap()

        m = _M
        mask = _MASK
        for k in words:
            k = (k * m) & mask
            k ^= k >> 24
            h = ((h * m) & mask) ^ ((k * m) & mask)

    tail = data[nblocks * 4 :]
    rem = len(tail)
    if rem == 3:
        h ^= tail[2] << 16
    if rem >= 2:
        h ^= tail[1] << 8
    if rem >= 1:
        h ^= tail[0]
        h = (h * _M) & _MASK

    h ^= h >> 13
    h = (h * _M) & _MASK
    h ^= h >> 15
    return h


def normalize(data: bytes) -> bytes:
    """Quita los bytes de espacio en blanco que CurseForge ignora."""
    return data.translate(None, _WHITESPACE)


def curseforge_fingerprint(data: bytes) -> int:
    """Fingerprint CurseForge de un archivo ya leído en memoria."""
    return murmur2(normalize(data), seed=1)
