"""Lower only a macro LEF DBU declaration when every coordinate is exact.

No rounding, rescaling, geometry replacement, PDK change or source overwrite.
Unsupported syntax is rejected instead of silently missing a geometry field.
"""
from decimal import Decimal
import re


def normalize(text,target_dbu=1000):
    if type(target_dbu) is not int or target_dbu!=1000:raise ValueError('frozen technology requires 1000 DBU/um')
    units=list(re.finditer(r'(?m)^(\s*DATABASE MICRONS )2000(\s*;)\s*$',text))
    if len(units)!=1:raise ValueError('expected exactly one 2000 DBU declaration')
    allowed={'VERSION','NAMESCASESENSITIVE','BUSBITCHARS','DIVIDERCHAR','UNITS','DATABASE','END',
        'MACRO','CLASS','SIZE','SYMMETRY','PIN','DIRECTION','PORT','LAYER','RECT','OBS','USE','SHAPE'}
    values=[];rectangles=0;sizes=0;macros=0
    for raw in text.splitlines():
        line=raw.strip()
        if not line:continue
        words=line.split();key=words[0]
        if key not in allowed:raise ValueError('unsupported LEF keyword: '+key)
        if key=='MACRO':macros+=1
        if key=='RECT':
            if len(words)!=6 or words[-1]!=';':raise ValueError('unsupported RECT syntax')
            coords=words[1:5];rectangles+=1
        elif key=='SIZE':
            if len(words)!=5 or words[2]!='BY' or words[-1]!=';':raise ValueError('unsupported SIZE syntax')
            coords=[words[1],words[3]];sizes+=1
        else:continue
        for token in coords:
            number=Decimal(token)
            if not number.is_finite() or number*target_dbu!=(number*target_dbu).to_integral_value():
                raise ValueError('coordinate loses precision at target DBU: '+token)
            values.append(token)
    if macros!=1 or sizes!=1 or not rectangles:raise ValueError('incomplete macro geometry')
    match=units[0];start=match.start()+len(match[1])
    output=text[:start]+str(target_dbu)+text[start+4:]
    if output[:start]+text[start:start+4]+output[start+4:]!=text:raise ValueError('unexpected geometry modification')
    return output,dict(source_dbu_per_micron=2000,target_dbu_per_micron=target_dbu,
        geometry_byte_identical=True,coordinate_count=len(values),rectangles=rectangles,
        rounding_performed=False,scale_factor=1)
