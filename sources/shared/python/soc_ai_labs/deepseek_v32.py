"""Minimal status enum retained by the released LiteX contract."""
from enum import IntEnum

class Status(IntEnum):
    OK = 0
    INVALID_ARGUMENT = 1
    BUSY = 2
    FAULT = 3
