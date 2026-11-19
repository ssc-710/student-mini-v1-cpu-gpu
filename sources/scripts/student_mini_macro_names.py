"""Resolve exact OpenDB macro names; preserve all generated placement geometry."""
import re


def resolve_placement(source):
    pattern = r'-macro_name \{([^{}\n]+)\}'
    names = re.findall(pattern, source)
    if not names or len(names) != len(set(names)) or len(names) != source.count('-macro_name'):
        raise ValueError('missing/duplicate/unsupported macro name declaration')
    if any('\\' in name or ';' in name for name in names):
        raise ValueError('expected original logical macro names')
    prefix = r'''# Exact name normalization only. No change to coordinates, orientation or RTL.
set student_mini_macro_names [dict create]
foreach inst [[ord::get_db_block] getInsts] {
  if {[[$inst getMaster] getType] ne "BLOCK"} { continue }
  set actual [$inst getName]
  regsub -all {\\([\[\]])} $actual {\1} logical
  if {[dict exists $student_mini_macro_names $logical]} {
    error "Ambiguous normalized macro name: $logical"
  }
  dict set student_mini_macro_names $logical $actual
}
proc student_mini_macro_instance {logical} {
  global student_mini_macro_names
  if {![dict exists $student_mini_macro_names $logical]} {
    error "Missing actual macro instance: $logical"
  }
  return [dict get $student_mini_macro_names $logical]
}
'''
    prefix += f'if {{[dict size $student_mini_macro_names] != {len(names)}}} {{ error "Actual macro count differs" }}\n'
    result = re.sub(pattern, lambda match: '-macro_name [student_mini_macro_instance {'+match[1]+'}]', source)
    return prefix+result, names
