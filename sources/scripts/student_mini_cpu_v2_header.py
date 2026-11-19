"""Header compatibility for the v2 (question-independent) CPU firmware.

The v2 firmware reads the prompt length at run time and never references the
per-question macros below; every other line of the generated image header
(segment offsets, model shape, scale indices, special tokens) must be identical.
"""
import re

QUESTION_MACROS = ('COURSE_NANO_PROMPT_TOKENS', 'COURSE_NANO_SEGMENT_PROMPT_TOKENS_U32_SIZE',
                   'COURSE_NANO_SEGMENT_USER_UTF8_SIZE')


def checked_header_v2(original, selected):
    old = original.replace('\r\n', '\n').splitlines()
    new = selected.replace('\r\n', '\n').splitlines()
    if len(old) != len(new):
        raise ValueError('image header layout differs')
    values = {}
    for a, b in zip(old, new):
        if a == b:
            continue
        name_a = re.match(r'#define (\S+) (\d+)u$', a)
        name_b = re.match(r'#define (\S+) (\d+)u$', b)
        if not (name_a and name_b and name_a.group(1) == name_b.group(1) and name_a.group(1) in QUESTION_MACROS):
            raise ValueError('image header differs beyond the run-time prompt length: ' + a)
        values[name_a.group(1)] = (int(name_a.group(2)), int(name_b.group(2)))
    capacity = values.get('COURSE_NANO_SEGMENT_PROMPT_TOKENS_U32_SIZE')
    if capacity and capacity[1] > capacity[0]:
        raise ValueError('prompt exceeds the compiled prompt-segment capacity')
