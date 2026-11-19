"""Exact external SDRAM initialization for the frozen 128-bit, four-bank CPU.

Only testbench memory contents change. CPU ROM, mapped RTL and simulator
executable are not transformed. Original bank images must first round-trip.
"""
import re


def bank_images(blob):
    if not blob or len(blob)%4:raise ValueError('nonempty 32-bit loader words required')
    # The pinned LiteDRAM initializer pads its 32-bit list to 16 words.
    padded=blob+bytes((-len(blob))%64)
    banks=[[] for _ in range(4)]
    for offset in range(0,len(padded),16):
        bank=(offset//16//512)%4
        banks[bank].append(int.from_bytes(padded[offset:offset+16],'little'))
    return banks


def parse_bank(text):
    words=text.split()
    if any(not re.fullmatch('[0-9a-fA-F]{32}',word) for word in words):
        raise ValueError('expected explicit 128-bit SDRAM words')
    return [int(word,16) for word in words]


def checked_original(blob,texts):
    if len(texts)!=4 or [parse_bank(text) for text in texts]!=bank_images(blob):
        raise ValueError('frozen loader/bank layout does not round-trip exactly')


def checked_header(original,selected):
    # CRLF/LF normalization only; even an innocuous changed macro needs a new ROM.
    if original.replace('\r\n','\n')!=selected.replace('\r\n','\n'):
        raise ValueError('selected image requires a different firmware header')


def changed_loader(old_loader,old_image,new_image,baseline_bytes):
    if type(baseline_bytes) is not int or baseline_bytes<=0 or len(old_image)!=len(new_image):
        raise ValueError('frozen image offset/size required')
    if old_loader[baseline_bytes:baseline_bytes+len(old_image)]!=old_image:
        raise ValueError('old model image not present at frozen loader offset')
    tail=old_loader[baseline_bytes+len(old_image):]
    if len(old_loader)%1936 or len(tail)>=1936 or any(tail):
        raise ValueError('unexpected loader transport padding')
    return old_loader[:baseline_bytes]+new_image+tail
