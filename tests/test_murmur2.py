import random
import struct

import pytest

from mod_updater.murmur2 import curseforge_fingerprint, murmur2, normalize

M = 0x5BD1E995
MASK = 0xFFFFFFFF


def murmur2_reference(data: bytes, seed: int) -> int:
    """Traducción literal del MurmurHash2.cpp original (byte a byte)."""
    length = len(data)
    h = (seed ^ length) & MASK
    i = 0
    while length >= 4:
        k = data[i] | (data[i + 1] << 8) | (data[i + 2] << 16) | (data[i + 3] << 24)
        k = (k * M) & MASK
        k ^= k >> 24
        k = (k * M) & MASK
        h = (h * M) & MASK
        h ^= k
        i += 4
        length -= 4
    if length == 3:
        h ^= data[i + 2] << 16
    if length >= 2:
        h ^= data[i + 1] << 8
    if length >= 1:
        h ^= data[i]
        h = (h * M) & MASK
    h ^= h >> 13
    h = (h * M) & MASK
    h ^= h >> 15
    return h


def test_empty_seed0_is_zero():
    assert murmur2(b"", 0) == 0


def test_empty_seed1_by_hand():
    # h = 1 ^ 0 = 1; h ^= 0; h *= M; h ^= h >> 15
    h = 1
    h = (h * M) & MASK
    h ^= h >> 15
    assert murmur2(b"", 1) == h


def test_single_block_by_hand():
    data = b"abcd"
    k = struct.unpack("<I", data)[0]
    k = (k * M) & MASK
    k ^= k >> 24
    k = (k * M) & MASK
    h = ((1 ^ 4) * M) & MASK
    h ^= k
    h ^= h >> 13
    h = (h * M) & MASK
    h ^= h >> 15
    assert murmur2(data, 1) == h


@pytest.mark.parametrize("length", list(range(0, 17)) + [255, 1024, 4097])
@pytest.mark.parametrize("seed", [0, 1, 0x9747B28C])
def test_matches_reference(length, seed):
    rnd = random.Random(length * 31 + seed)
    data = bytes(rnd.getrandbits(8) for _ in range(length))
    assert murmur2(data, seed) == murmur2_reference(data, seed)


def test_result_is_32_bit():
    rnd = random.Random(7)
    for _ in range(50):
        data = bytes(rnd.getrandbits(8) for _ in range(rnd.randint(0, 200)))
        assert 0 <= murmur2(data, 1) <= MASK


def test_normalize_removes_only_cf_whitespace():
    assert normalize(b"a\tb\nc\rd e") == b"abcde"
    # 11 (VT) y 12 (FF) NO se quitan
    assert normalize(b"a\x0bb\x0cc") == b"a\x0bb\x0cc"


def test_fingerprint_ignores_whitespace():
    assert curseforge_fingerprint(b"hello world\r\n") == curseforge_fingerprint(b"helloworld")
    assert curseforge_fingerprint(b"hello world") == murmur2(b"helloworld", 1)
